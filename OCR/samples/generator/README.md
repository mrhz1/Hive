# Test document generator

Creates two 20-page fake clinical documents in `../`, with the expected
text and PHI for each.

| output | |
|---|---|
| `ocr_test_printed_20p.pdf` | typed hospital record, has a text layer |
| `ocr_test_handwritten_aged_20p.pdf` | old handwritten chart, scanned image only (no text layer) |
| `*.groundtruth.txt` | expected text per page |
| `*.phi.txt` | expected PHI, `TYPE<TAB>value` |

All names, IDs and addresses are made up.

## Generate

```bash
pip install reportlab pillow

mkdir -p ../fonts && cd ../fonts
B=https://raw.githubusercontent.com/google/fonts/main
curl -sfLo Caveat.ttf              "$B/ofl/caveat/Caveat%5Bwght%5D.ttf"
curl -sfLo IndieFlower-Regular.ttf "$B/ofl/indieflower/IndieFlower-Regular.ttf"
curl -sfLo ShadowsIntoLight.ttf    "$B/ofl/shadowsintolight/ShadowsIntoLight.ttf"
curl -sfLo HomemadeApple.ttf       "$B/apache/homemadeapple/HomemadeApple-Regular.ttf"
curl -sfLo ReenieBeanie.ttf        "$B/ofl/reeniebeanie/ReenieBeanie.ttf"
cd -

python make_printed.py ..
python make_handwritten.py ..
```

## Options (make_handwritten.py)

- `DPI`: 200 by default, lower makes OCR harder
- the seed in `main()`: change it for different stains and skew
- `INKS`, `PAGE_HAND`, `FONTS`: handwriting and ink per page
- end of `render_page`: blur, contrast, noise and JPEG quality

All text is in `content.py`.
