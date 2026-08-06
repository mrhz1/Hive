"""Stage 2 entrypoint. Runs under the NLP virtualenv.

Not called directly in normal use -- scripts/run_deid.py spawns it. Run
it by hand only to debug PII detection against spans stage 1 already
produced (which is why DEID_KEEP_WORK_DIR exists):

    .venv-nlp/bin/python scripts/stage_nlp.py \\
        --manifest work/nlp-manifest.json --result work/nlp-result.json

Logging goes to stderr for the same reason as stage 1.
"""
import argparse
import json
import logging
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store  # noqa: E402

# Before anything imports transformers: the library reads HF_HUB_OFFLINE
# into a module constant at import time, so setting it afterwards has no
# effect. deid.stage_nlp pulls in torch/transformers transitively, which
# is why this sits above that import rather than inside main().
model_store.apply_offline_env()

from deid.config import load_config  # noqa: E402
from deid.spans import read_manifest  # noqa: E402
from deid.stage_nlp import run_stage  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PII detection + redaction stage")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--log-level", default=os.environ.get("DEID_LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("transformers", "urllib3", "filelock", "presidio-analyzer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # This one is not noise-suppression, it is a PHI control.
    # spacy_huggingface_pipelines warns about unalignable entities and
    # quotes the *document* into the warning message -- so a routine
    # tokenization hiccup writes patient names into the job log, which is
    # exactly what this pipeline exists to prevent. The warning tells us
    # nothing actionable: an entity that cannot be aligned is one
    # Presidio never sees, and the redaction is unaffected.
    warnings.filterwarnings(
        "ignore",
        message="Skipping annotation.*",
        module="spacy_huggingface_pipelines.*",
    )

    jobs = read_manifest(args.manifest)
    results = run_stage(jobs, load_config())

    fd = os.open(args.result, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump([r.to_dict() for r in results], fh)

    failed = [r for r in results if r.status != "ok"]
    if failed and len(failed) == len(results):
        return 1
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
