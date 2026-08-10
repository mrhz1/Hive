"""Fill OCR/models/ so the deployment never needs the network."""
import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store  # noqa: E402

os.environ["DEID_OFFLINE"] = "0"
for _var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    os.environ.pop(_var, None)

from deid.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(message)s", stream=sys.stdout
)
log = logging.getLogger("stage_models")

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
    """Copy into place, resolving symlinks."""
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, symlinks=False, ignore=shutil.ignore_patterns(
        ".cache", ".git*", "*.msgpack", "*.h5", "*.onnx", "__pycache__"
    ))


def stage_paddle(name: str, device: str, force: bool) -> bool:
    """PaddleOCR downloads into ~/.paddlex/official_models on first construction, so we build the pipeline and then copy what landed."""
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
    """spaCy models ship as pip packages hosted on github (blocked on the target), so what gets staged is the *loadable directory* inside the installed package -- the one holding config.cfg."""
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
    """snapshot_download with a local_dir, so the result is a plain directory of real files rather than the symlinked blob cache."""
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
                max_workers=1,
            )
            break
        except Exception as exc:
            log.warning("  attempt %d/%d failed: %s", attempt, attempts, exc)
            if attempt == attempts:
                log.error("  FAILED: giving up")
                return False

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
