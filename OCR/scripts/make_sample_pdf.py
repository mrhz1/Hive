"""Generate a synthetic clinical-note PDF for testing.

All values are fabricated. Produces a *scanned-style* PDF by default:
the text is rendered, rasterised, and re-embedded as an image, so there
is no text layer and OCR is genuinely exercised (which is the case this
job exists for).

    python scripts/make_sample_pdf.py samples/sample_scanned.pdf
    python scripts/make_sample_pdf.py samples/sample_digital.pdf --keep-text
"""
import argparse
import sys
from pathlib import Path

import fitz

LINES = [
    ("GENERAL HOSPITAL - DISCHARGE SUMMARY", 16, True),
    ("", 11, False),
    ("Patient Name: Jonathan Michael Reyes", 11, False),
    ("Date of Birth: 04/17/1952", 11, False),
    ("Age: 94 years old", 11, False),
    ("MRN: AB4429173", 11, False),
    ("SSN: 543-22-9087", 11, False),
    ("Phone: (415) 555-0182", 11, False),
    ("Email: j.reyes1952@example.com", 11, False),
    ("Address: 1428 Elm Street, Apt 3B", 11, False),
    ("City: Springfield, IL 62704", 11, False),
    ("", 11, False),
    ("Admission Date: 03/02/2026", 11, False),
    ("Discharge Date: 03/09/2026", 11, False),
    ("Attending Physician: Dr. Amanda Whitfield", 11, False),
    ("Referring Provider: Dr. Samuel Okonkwo, Mercy Clinic", 11, False),
    ("", 11, False),
    ("CLINICAL COURSE", 13, True),
    ("The patient was admitted with acute chest pain and shortness of", 11, False),
    ("breath. Serial troponins were negative. Echocardiogram showed an", 11, False),
    ("ejection fraction of 55 percent with no wall motion abnormality.", 11, False),
    ("Mr. Reyes responded well to diuresis and was transitioned to oral", 11, False),
    ("medication on hospital day three.", 11, False),
    ("", 11, False),
    ("Insurance ID: BCBS-7741820394", 11, False),
    ("Billing Contact: billing@generalhospital.example.org", 11, False),
    ("Follow-up scheduled with Dr. Whitfield on 03/21/2026.", 11, False),
]


def build(output: str, keep_text: bool, dpi: int = 200) -> None:
    doc = fitz.open()
    page = doc.new_page()  # Letter by default

    y = 60
    for text, size, bold in LINES:
        if text:
            page.insert_text(
                (60, y),
                text,
                fontsize=size,
                fontname="helv" if not bold else "hebo",
                color=(0, 0, 0),
            )
        y += size + 8

    if keep_text:
        doc.save(output, garbage=3, deflate=True)
        doc.close()
        print(f"wrote digital (text-layer) PDF: {output}")
        return

    # Rasterise to remove the text layer -> a "scanned" document.
    scale = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    scanned = fitz.open()
    spage = scanned.new_page(width=page.rect.width, height=page.rect.height)
    spage.insert_image(spage.rect, pixmap=pix)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    scanned.save(output, garbage=3, deflate=True)
    scanned.close()
    doc.close()
    print(f"wrote scanned-style (image-only) PDF: {output}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("output", nargs="?", default="samples/sample_scanned.pdf")
    ap.add_argument(
        "--keep-text",
        action="store_true",
        help="Keep the text layer instead of rasterising",
    )
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    build(args.output, args.keep_text, args.dpi)
    return 0


if __name__ == "__main__":
    sys.exit(main())
