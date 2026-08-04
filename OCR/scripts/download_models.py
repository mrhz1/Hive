"""Pre-download every model the job needs.

Run this once at image/environment build time. Cloudera AI job runs
should not be downloading hundreds of MB on first request -- and may not
have egress at all. Downloading here makes the first real job fast and
surfaces network problems at setup time instead of mid-run.

    python scripts/download_models.py
"""
import logging
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid.config import load_config  # noqa: E402

logging.basicConfig(
    level=logging.INFO, format="%(levelname)-7s %(message)s", stream=sys.stdout
)
log = logging.getLogger("download_models")


def download_spacy(model: str) -> bool:
    log.info("spaCy: %s", model)
    try:
        import spacy

        try:
            spacy.load(model)
            log.info("  already present")
            return True
        except OSError:
            pass
        subprocess.check_call([sys.executable, "-m", "spacy", "download", model])
        spacy.load(model)
        return True
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False


def download_transformers(model: str) -> bool:
    log.info("transformers: %s", model)
    try:
        from transformers import AutoModelForTokenClassification, AutoTokenizer

        AutoTokenizer.from_pretrained(model)
        AutoModelForTokenClassification.from_pretrained(model)
        return True
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False


def download_paddle(det_model: str, rec_model: str, device: str) -> bool:
    """PaddleOCR fetches weights lazily on first construction, so simply
    building the pipeline pulls both det and rec models."""
    log.info("PaddleOCR: det=%s rec=%s", det_model, rec_model)
    try:
        from paddleocr import PaddleOCR

        PaddleOCR(
            text_detection_model_name=det_model,
            text_recognition_model_name=rec_model,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device=device,
        )
        return True
    except Exception as exc:
        log.error("  FAILED: %s", exc)
        return False


def main() -> int:
    config = load_config()
    results = {
        "spacy": download_spacy(config.spacy_model),
        "transformers": download_transformers(config.transformers_model),
        "paddleocr": download_paddle(
            config.det_model, config.rec_model, config.device
        ),
    }

    log.info("--- summary ---")
    for name, ok in results.items():
        log.info("%-14s %s", name, "OK" if ok else "FAILED")

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
