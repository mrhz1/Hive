"""Stage 1 entrypoint. Runs under the OCR virtualenv.

Not called directly in normal use -- scripts/run_deid.py spawns it. Run
it by hand only to debug the OCR half in isolation:

    .venv-ocr/bin/python scripts/stage_ocr.py \\
        --manifest work/ocr-manifest.json --result work/ocr-result.json

Logging goes to stderr, never stdout: paddle writes its own banner to
stdout at import and the orchestrator reads results from --result, so
stdout here is not a channel anyone should rely on.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store  # noqa: E402

# Before deid.stage_ocr pulls paddle in: paddlex snapshots its flags into
# module constants at import time, so the download-source switches only
# take effect if they are set first.
model_store.apply_offline_env()

from deid.config import load_config  # noqa: E402
from deid.spans import read_manifest  # noqa: E402
from deid.stage_ocr import run_stage  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR stage (paddle)")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--log-level", default=os.environ.get("DEID_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("ppocr", "paddle", "paddlex", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    jobs = read_manifest(args.manifest)
    outcomes = run_stage(jobs, load_config())

    # 0600: these name patient files. Written last so its existence is
    # the orchestrator's signal that the stage got far enough to report.
    fd = os.open(args.result, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(outcomes, fh)

    failed = [o for o in outcomes if o["status"] != "ok"]
    if failed and len(failed) == len(outcomes):
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
