"""Fill OCR/models/ so the deployment never needs the network.

Run this **on a machine with internet access** -- your laptop, a build
agent, anywhere github.com and huggingface.co resolve. It downloads every
weight the pipeline needs and lays them out under `OCR/models/` in the
shape `deid/model_store.py` expects. Then copy that one directory to the
Cloudera AI project and the job runs entirely offline.

    # stage 1's models, under the OCR venv
    .venv-ocr/bin/python scripts/stage_models.py --stage ocr

    # stage 2's, under the NLP venv
    .venv-nlp/bin/python scripts/stage_models.py --stage nlp

    # or `make models`, which does both

Two virtualenvs means two runs: each stage can only download what it can
import, and `--stage` is required rather than sniffed because guessing
would let a half-installed environment report success.

## Why it copies instead of pointing at the caches

paddle, huggingface and spaCy each have their own cache layout in a
different place under `$HOME`, none of which survives being moved to
another machine (HF's is a blob store behind symlinks; spaCy's is a pip
package). The store is a flat, self-contained copy: `tar` it, move it,
done.

Re-running is cheap and safe -- anything already present is left alone
unless `--force` is given.
"""
import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store  # noqa: E402

# This script is the one thing that is *supposed* to reach the network,
# so it turns the offline default off for its own process before
# anything imports transformers and latches HF_HUB_OFFLINE.
os.environ["DEID_OFFLINE"] = "0"
for _var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    os.environ.pop(_var, None)

from deid.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(message)s", stream=sys.stdout
)
log = logging.getLogger("stage_models")

# The NER repo carries TF, Flax and ONNX copies of the same weights. We
# need the PyTorch one and the tokenizer, and nothing else -- this turns
# a ~1.5GB download into ~440MB.
TRANSFORMERS_ALLOW = [
    "config.json",
    "pytorch_model.bin",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
    "added_tokens.json",
]


def _target(kind: str, name: str) -> Path:
    """The canonical location for a model, names kept verbatim."""
    return model_store.models_dir() / kind / name.strip().strip("/")


def _already_there(kind: str, name: str, force: bool) -> bool:
    existing = model_store.find(kind, name)
    if existing is None or force:
        return False
    log.info("  already staged at %s", existing)
    return True


def _copy_tree(source: Path, target: Path) -> None:
    """Copy into place, resolving symlinks.

    `symlinks=False` is the important part: the HuggingFace cache stores
    every file as a symlink into a blob directory, and a store full of
    dangling links is worse than no store at all -- it passes the
    "directory exists" check and fails at load time on the other machine.
    """
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False, ignore=shutil.ignore_patterns(
        ".cache", ".git*", "*.msgpack", "*.h5", "*.onnx", "__pycache__"
    ))


def stage_paddle(name: str, device: str, force: bool) -> bool:
    """PaddleOCR downloads into ~/.paddlex/official_models on first
    construction, so we build the pipeline and then copy what landed.

    There is no public "download this model to here" API -- PaddleX
    resolves names against its own cache dir -- so provoke-then-copy is
    the supported shape rather than a workaround.
    """
    log.info("paddle: %s", name)
    if _already_there(model_store.PADDLE_DIR, name, force):
        return True

    try:
        from paddlex.inference.utils.official_models import official_models

        source = Path(official_models[name])
    except Exception as exc:
        log.error("  FAILED to download: %s", exc)
        return False

    if not source.is_dir():
        log.error("  paddle reported %s but it does not exist", source)
        return False

    target = _target(model_store.PADDLE_DIR, name)
    _copy_tree(source, target)
    log.info("  -> %s", target)
    return True


def stage_spacy(name: str, force: bool) -> bool:
    """spaCy models ship as pip packages hosted on github (blocked on the
    target), so what gets staged is the *loadable directory* inside the
    installed package -- the one holding config.cfg. spacy.load() takes a
    path just as happily as a package name.
    """
    log.info("spacy: %s", name)
    if _already_there(model_store.SPACY_DIR, name, force):
        return True

    try:
        import spacy

        try:
            nlp = spacy.load(name)
        except OSError:
            log.info("  not installed, downloading")
            from spacy.cli.download import download

            download(name)
            nlp = spacy.load(name)
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False

    source = Path(nlp.path) if nlp.path else None
    if source is None or not (source / "config.cfg").is_file():
        log.error("  loaded %s but found no config.cfg to copy from", name)
        return False

    target = _target(model_store.SPACY_DIR, name)
    _copy_tree(source, target)
    log.info("  -> %s", target)
    return True


def stage_transformers(name: str, force: bool) -> bool:
    """snapshot_download with a local_dir, so the result is a plain
    directory of real files rather than the symlinked blob cache.

    Retried because this is the ~440MB artifact and the one most likely
    to be interrupted; huggingface_hub resumes partial blobs, so a retry
    continues rather than restarting.
    """
    log.info("transformers: %s", name)
    if _already_there(model_store.TRANSFORMERS_DIR, name, force):
        return True

    target = _target(model_store.TRANSFORMERS_DIR, name)

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        log.error("  FAILED: huggingface_hub not importable: %s", exc)
        return False

    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            snapshot_download(
                repo_id=name,
                local_dir=str(target),
                allow_patterns=TRANSFORMERS_ALLOW,
                # Single worker is slower in theory and far more stable in
                # practice than parallel range requests on a flaky link.
                max_workers=1,
            )
            break
        except Exception as exc:
            log.warning("  attempt %d/%d failed: %s", attempt, attempts, exc)
            if attempt == attempts:
                log.error("  FAILED: giving up")
                return False

    # Prove it loads here rather than discovering on Cloudera that the
    # tokenizer files were excluded by allow_patterns.
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        AutoTokenizer.from_pretrained(str(target), local_files_only=True)
        AutoModelForTokenClassification.from_pretrained(
            str(target), local_files_only=True
        )
    except Exception as exc:
        log.error("  staged but does not load offline: %s", exc)
        return False

    log.info("  -> %s", target)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        required=True,
        choices=("ocr", "nlp"),
        help="Which virtualenv this is running under",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite models already in the store",
    )
    args = parser.parse_args()

    config = load_config()
    log.info("model store: %s", model_store.models_dir())

    if args.stage == "ocr":
        results = {
            f"paddle/{config.det_model}": stage_paddle(
                config.det_model, config.device, args.force
            ),
            f"paddle/{config.rec_model}": stage_paddle(
                config.rec_model, config.device, args.force
            ),
        }
    else:
        results = {
            f"spacy/{config.spacy_model}": stage_spacy(
                config.spacy_model, args.force
            ),
            f"transformers/{config.transformers_model}": stage_transformers(
                config.transformers_model, args.force
            ),
        }

    log.info("--- %s stage summary ---", args.stage)
    for name, ok in results.items():
        log.info("%-60s %s", name, "OK" if ok else "FAILED")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
