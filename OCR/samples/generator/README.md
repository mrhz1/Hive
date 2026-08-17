# OCR test-corpus generator

Builds the two 20-page synthetic clinical documents in `../`, together with
line-level ground truth and the expected PHI entity list for each.

| output | what it is |
|---|---|
| `ocr_test_printed_20p.pdf` | Modern typeset inpatient record. Digital-born, has a real text layer. |
| `ocr_test_handwritten_aged_20p.pdf` | Old ward chart, six different hands, aged paper, stains, skew, JPEG scan artefacts. **No text layer** — pure raster, so OCR is genuinely exercised. |
| `*.groundtruth.txt` | Rendered text, per page, for CER/WER scoring. |
| `*.phi.txt` | `TYPE<TAB>surface form` — expected entities for PHI recall scoring. |

All names, MRNs, SSNs, addresses, phone numbers, insurance IDs and NPIs are
fabricated.

## Regenerating

```bash
pip install reportlab pillow

# handwriting fonts (OFL / Apache 2.0), fetched into ../fonts/
mkdir -p ../fonts && cd ../fonts
B=https://raw.githubusercontent.com/google/fonts/main
curl -sfLo Caveat.ttf            "$B/ofl/caveat/Caveat%5Bwght%5D.ttf"
curl -sfLo IndieFlower-Regular.ttf "$B/ofl/indieflower/IndieFlower-Regular.ttf"
curl -sfLo ShadowsIntoLight.ttf  "$B/ofl/shadowsintolight/ShadowsIntoLight.ttf"
curl -sfLo HomemadeApple.ttf     "$B/apache/homemadeapple/HomemadeApple-Regular.ttf"
curl -sfLo ReenieBeanie.ttf      "$B/ofl/reeniebeanie/ReenieBeanie.ttf"
cd -

python make_printed.py ..
python make_handwritten.py ..      # ~30 s, 200 dpi
```

## Knobs

`make_handwritten.py`

- `DPI` — 200 by default. 300 gives a larger, cleaner scan; 150 makes OCR
  meaningfully harder.
- `random.Random(20260817)` in `main()` — the seed. Change it for a fresh
  set of stains, skews and ink densities over the same text, i.e. a second
  independent test document.
- `INKS`, `PAGE_HAND`, `FONTS` — which hand and ink colour each page uses.
- The scanner block at the end of `render_page` — blur radius, contrast,
  noise and `quality=74` on the JPEG. Lower these for a harder corpus.

`content.py` holds all text for both documents and the PHI inventories. Edit
there; both renderers and both ground-truth files follow automatically.
