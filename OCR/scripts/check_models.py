"""Prove the staged models load offline, in this virtualenv."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid import model_store  # noqa: E402

model_store.apply_offline_env()

from deid.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(message)s", stream=sys.stdout
)
log = logging.getLogger("check_models")


def check_paddle(config) -> bool:
    log.info("paddle: det=%s rec=%s", config.det_model, config.rec_model)
    try:
        from deid.ocr_engine import OcrEngine

        # _load() is the same call the stage makes, model dirs and all.
        OcrEngine(config)._load()
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False
    log.info("  OK")
    return True


def check_spacy(config) -> bool:
    log.info("spacy: %s", config.spacy_model)
    try:
        import spacy

        path = model_store.resolve(model_store.SPACY_DIR, config.spacy_model)
        spacy.load(path, disable=["parser", "ner"])
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False
    log.info("  OK")
    return True


def check_transformers(config) -> bool:
    log.info("transformers: %s", config.transformers_model)
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        path = model_store.resolve(
            model_store.TRANSFORMERS_DIR, config.transformers_model
        )
        AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForTokenClassification.from_pretrained(
            path, local_files_only=True
        )
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False

    labels = sorted(set(model.config.id2label.values()))
    log.info("  OK -- labels: %s", ", ".join(labels))

    from deid.config import MODEL_TO_PRESIDIO_ENTITY

    unmapped = [
        label
        for label in labels
        if label != "O" and label not in MODEL_TO_PRESIDIO_ENTITY
    ]
    if unmapped:
        log.warning(
            "  model emits labels with no Presidio mapping (they will be "
            "ignored): %s",
            ", ".join(unmapped),
        )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("ocr", "nlp"))
    args = parser.parse_args()

    config = load_config()
    log.info("model store: %s (offline=%s)", model_store.models_dir(),
             model_store.offline())

    missing = model_store.missing_models(config)
    for problem in missing:
        log.error(problem)
    if missing:
        return 1

    if args.stage == "ocr":
        results = {"paddle": check_paddle(config)}
    else:
        results = {
            "spacy": check_spacy(config),
            "transformers": check_transformers(config),
        }

    log.info("--- %s stage summary ---", args.stage)
    for name, ok in results.items():
        log.info("%-14s %s", name, "OK" if ok else "FAILED")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
