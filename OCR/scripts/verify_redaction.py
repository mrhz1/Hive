"""Verify a redacted PDF by re-OCRing it and looking for known PII."""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid.config import load_config  # noqa: E402
from deid.ocr_engine import OcrEngine  # noqa: E402
from deid.pdf_io import open_pdf, render_pages  # noqa: E402

SAMPLE_SECRETS = [
    "Jonathan Michael Reyes",
    "04/17/1952",
    "AB4429173",
    "543-22-9087",
    "555-0182",
    "j.reyes1952@example.com",
    "1428 Elm Street",
    "62704",
    "Amanda Whitfield",
    "Samuel Okonkwo",
    "BCBS-7741820394",
]

SAMPLE_MUST_KEEP = [
    "chest pain",
    "troponins",
    "ejection fraction",
]


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--expect-absent", action="append", default=None)
    ap.add_argument("--expect-present", action="append", default=None)
    args = ap.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    for noisy in ("ppocr", "paddle", "paddlex"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

    secrets = args.expect_absent or SAMPLE_SECRETS
    keepers = args.expect_present or (
        SAMPLE_MUST_KEEP if args.expect_absent is None else []
    )

    config = load_config()
    doc = open_pdf(args.pdf)

    layer_text = "".join(doc[i].get_text() for i in range(doc.page_count))

    # 2. What the pixels actually show now.
    engine = OcrEngine(config)
    ocr_text_parts = []
    for rendered in render_pages(doc, config.dpi):
        spans = engine.read_page(rendered.image)
        ocr_text_parts.append("\n".join(s.text for s in spans))
    doc.close()

    ocr_text = "\n".join(ocr_text_parts)
    haystack = normalise(layer_text + "\n" + ocr_text)

    print(f"--- verifying {args.pdf} ---")
    print(f"residual text-layer chars: {len(layer_text.strip())}")
    print(f"re-OCR'd chars: {len(ocr_text.strip())}\n")

    leaked = [s for s in secrets if normalise(s) in haystack]
    missing = [k for k in keepers if normalise(k) not in haystack]

    for secret in secrets:
        status = "LEAKED " if normalise(secret) in haystack else "removed"
        print(f"  [{status}] {secret}")

    if keepers:
        print()
        for keeper in keepers:
            status = "kept   " if normalise(keeper) not in [
                normalise(m) for m in missing
            ] else "LOST   "
            print(f"  [{status}] {keeper}")

    print()
    if leaked:
        print(f"FAIL: {len(leaked)} PII value(s) survived redaction: {leaked}")
        return 1
    if missing:
        print(f"WARN: over-redacted, expected content missing: {missing}")
        return 2
    print("PASS: no PII survived; expected clinical content intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
