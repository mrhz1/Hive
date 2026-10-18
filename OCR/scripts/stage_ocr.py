import argparse
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store

model_store.apply_offline_env()

from deid.config import load_config
from deid.spans import read_manifest
from deid.stage_ocr import run_stage, serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="OCR stage (paddle)")
    parser.add_argument("--manifest")
    parser.add_argument("--result")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--log-level", default=os.environ.get("DEID_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)
    if not args.serve and not (args.manifest and args.result):
        parser.error("--manifest and --result are required unless --serve is given")

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("ppocr", "paddle", "paddlex", "urllib3", "filelock"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.serve:
        out = os.fdopen(os.dup(1), "w", encoding="utf-8")
        os.dup2(2, 1)
        serve(load_config(), sys.stdin, out)
        return 0

    jobs = read_manifest(args.manifest)
    outcomes = run_stage(jobs, load_config())

    fd = os.open(args.result, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(outcomes, fh)

    failed = [o for o in outcomes if o["status"] != "ok"]
    if failed and len(failed) == len(outcomes):
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
