"""Job entrypoint: de-identify one PDF, a list of PDFs, or a directory."""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List

# Allow running as `python scripts/run_deid.py` from the OCR directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid.pipeline import (  # noqa: E402
    describe_environment,
    preflight,
    run_pipeline,
)
from deid.documents import (  # noqa: E402
    EXTENSIONS,
    is_supported,
    supported_globs,
)
from deid.results import exit_code, summarise  # noqa: E402


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        # stderr, so the summary on stdout stays machine-readable.
        stream=sys.stderr,
    )


def collect_inputs(raw_inputs: List[str], recursive: bool) -> List[Path]:
    """Every supported document under the given paths, in order."""
    found: List[Path] = []
    for raw in raw_inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            for pattern in supported_globs(recursive):
                found.extend(sorted(p for p in path.glob(pattern) if p.is_file()))
        elif path.is_file():
            if is_supported(str(path)):
                found.append(path)
            else:
                logging.warning(
                    "unsupported format, skipping: %s (handled: %s)",
                    path,
                    ", ".join(sorted(EXTENSIONS)),
                )
        else:
            logging.warning("input not found, skipping: %s", path)
    # Deduplicate while preserving order.
    seen, unique = set(), []
    for p in sorted(found):
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
        "--work-dir",
        default=os.environ.get("DEID_WORK_DIR"),
        help=(
            "Where the intermediate OCR handoff is written. Defaults to a "
            "0700 temp dir that is deleted afterwards. The handoff holds "
            "raw OCR text (PHI) -- do not point this somewhere shared."
        ),
    )
    parser.add_argument(
        "--progress-file",
        default=os.environ.get("DEID_PROGRESS_FILE"),
        help=(
            "Rewritten as the run advances, so a caller in another "
            "container can show a progress bar. Must be somewhere that "
            "caller can read -- unlike --work-dir it holds no PHI, only "
            "a page count and the file's own name."
        ),
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Check both stage interpreters exist, print them, and exit.",
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

    problems = preflight()

    if args.preflight:
        print(
            json.dumps(
                {"environment": describe_environment(), "problems": problems}, indent=2
            )
        )
        return 0 if not problems else 1

    if problems:
        for problem in problems:
            log.error("preflight: %s", problem)
        return 1

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

    log.info("starting: %d file(s) | %s", len(pdfs), describe_environment())

    results = run_pipeline(
        [str(p) for p in pdfs],
        output_dir=args.output_dir,
        suffix=args.suffix,
        work_dir=args.work_dir,
        progress_path=args.progress_file,
    )

    # Printed as JSON so the calling job/service can parse it from stdout.
    print(json.dumps(summarise(results), indent=2))
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
