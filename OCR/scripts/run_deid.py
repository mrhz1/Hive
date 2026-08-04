"""Job entrypoint: de-identify one PDF, a list of PDFs, or a directory.

Designed to be the Cloudera AI job script. Input can come from argv or
from env vars (Cloudera jobs commonly pass arguments as environment
variables), so the same script works either way without branching on
environment:

    python scripts/run_deid.py --input /path/doc.pdf --output-dir /path/out
    DEID_INPUT=/path/doc.pdf DEID_OUTPUT_DIR=/path/out python scripts/run_deid.py

Exit codes: 0 all succeeded, 1 every file failed, 2 partial failure.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# Allow running as `python scripts/run_deid.py` from the OCR directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid.config import load_config  # noqa: E402
from deid.pipeline import Deidentifier  # noqa: E402


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    # These are chatty at INFO and drown out the job's own output.
    for noisy in ("ppocr", "paddle", "transformers", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def collect_inputs(raw_inputs: List[str], recursive: bool) -> List[Path]:
    pdfs: List[Path] = []
    for raw in raw_inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            pdfs.extend(sorted(p for p in path.glob(pattern) if p.is_file()))
        elif path.is_file():
            pdfs.append(path)
        else:
            logging.warning("input not found, skipping: %s", path)
    # Deduplicate while preserving order.
    seen, unique = set(), []
    for p in pdfs:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="OCR + PII de-identification for PDFs")
    parser.add_argument(
        "--input",
        "-i",
        action="append",
        default=None,
        help="PDF file or directory (repeatable). Falls back to $DEID_INPUT.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        default=None,
        help="Where outputs are written. Falls back to $DEID_OUTPUT_DIR.",
    )
    parser.add_argument(
        "--recursive", action="store_true", help="Recurse into input directories"
    )
    parser.add_argument(
        "--suffix",
        default=os.environ.get("DEID_OUTPUT_SUFFIX", "_deid"),
        help="Appended to the output filename stem (default: _deid)",
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("DEID_LOG_LEVEL", "INFO")
    )
    args = parser.parse_args(argv)

    if not args.input:
        env_input = os.environ.get("DEID_INPUT")
        args.input = [i for i in env_input.split(",") if i.strip()] if env_input else []
    if not args.output_dir:
        args.output_dir = os.environ.get("DEID_OUTPUT_DIR")

    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    log = logging.getLogger("run_deid")

    if not args.input:
        log.error("no input given (use --input or $DEID_INPUT)")
        return 1
    if not args.output_dir:
        log.error("no output dir given (use --output-dir or $DEID_OUTPUT_DIR)")
        return 1

    pdfs = collect_inputs(args.input, args.recursive)
    if not pdfs:
        log.error("no PDF files found in: %s", ", ".join(args.input))
        return 1

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    log.info(
        "starting: %d file(s) | ocr=%s/%s | ner=%s | dpi=%d",
        len(pdfs),
        config.det_model,
        config.rec_model,
        config.transformers_model,
        config.dpi,
    )

    # Model load happens on first use and is the expensive part; doing it
    # once here keeps per-file cost to actual work.
    deidentifier = Deidentifier(config)

    results = []
    for pdf in pdfs:
        stem = pdf.stem + args.suffix
        result = deidentifier.process_pdf(
            source_path=str(pdf),
            output_pdf=str(output_dir / f"{stem}.pdf"),
            output_text=str(output_dir / f"{stem}.txt"),
            output_report=str(output_dir / f"{stem}.report.json"),
        )
        results.append(result)

    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status != "ok"]

    summary = {
        "files_total": len(results),
        "files_ok": len(ok),
        "files_failed": len(failed),
        "entities_redacted": sum(r.total_entities for r in ok),
        "boxes_applied": sum(r.total_boxes for r in ok),
        "failures": [{"path": r.source_path, "error": r.error} for r in failed],
    }
    # Printed as JSON so the calling job/service can parse it from stdout.
    print(json.dumps(summary, indent=2))

    if failed and not ok:
        return 1
    if failed:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
