"""Render the 20-page handwritten ward chart as an aged, scanned-looking PDF.

Each page is drawn as a raster image at 200 dpi: aged paper, ruled lines,
stains, punch holes, then handwriting composited with per-word jitter, ink
density variation and bleed, then a small page skew and scanner artefacts.
"""
import math
import os
import random
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content import HANDWRITTEN_PHI, handwritten_pages  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FONTDIR = os.path.join(os.path.dirname(HERE), "fonts")

DPI = 200
W, H = int(8.5 * DPI), int(11 * DPI)          # 1700 x 2200

LEFT = 250
RIGHT = W - 130
TOP = 210
BOTTOM = H - 190
TEXTW = RIGHT - LEFT

LINE_H = 58.0
BLANK_H = 30.0

# per-font point size and a vertical nudge, tuned so the hands look the
# same size on the page despite very different font metrics
FONTS = {
    "ashcroft":  ("Caveat.ttf", 62, 0),
    "cavanaugh": ("IndieFlower-Regular.ttf", 46, -4),
    "nurse":     ("ShadowsIntoLight.ttf", 50, -2),
    "pemberton": ("HomemadeApple.ttf", 38, -6),
    "okamura":   ("ReenieBeanie.ttf", 58, 2),
    "chowdhury": ("Caveat.ttf", 58, 0),
}

# which hand wrote which page (1-indexed)
PAGE_HAND = {
    1: "ashcroft", 2: "ashcroft", 3: "ashcroft", 4: "ashcroft", 5: "nurse",
    6: "ashcroft", 7: "ashcroft", 8: "ashcroft", 9: "cavanaugh",
    10: "cavanaugh", 11: "ashcroft", 12: "cavanaugh", 13: "ashcroft",
    14: "pemberton", 15: "nurse", 16: "chowdhury", 17: "okamura",
    18: "nurse", 19: "ashcroft", 20: "ashcroft",
}

INKS = [
    (28, 34, 74),      # blue-black fountain pen
    (24, 26, 40),      # near black
    (52, 40, 28),      # faded brown ink
    (34, 44, 92),      # brighter blue biro
]

_cache = {}


def font(key, size=None):
    name, base, _ = FONTS[key]
    size = int(size or base)
    k = (name, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(os.path.join(FONTDIR, name), size)
    return _cache[k]


def measure(f, s):
    b = f.getbbox(s)
    return b[2] - b[0]


def wrap_px(text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = w if not cur else cur + " " + w
        if measure(f, t) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


# --------------------------------------------------------------------------
# paper
# --------------------------------------------------------------------------

def make_paper(rng, ruled, margin_rule, line_h=LINE_H):
    base = rng.randint(214, 226)
    img = Image.new("RGB", (W, H), (base + 14, base + 4, base - 26))
    d = ImageDraw.Draw(img, "RGBA")

    # broad tonal blotches - uneven ageing across the sheet
    for _ in range(rng.randint(14, 22)):
        cx, cy = rng.randint(-200, W + 200), rng.randint(-200, H + 200)
        r = rng.randint(240, 900)
        a = rng.randint(6, 20)
        dark = rng.random() < 0.7
        col = (150, 122, 74, a) if dark else (255, 250, 232, a)
        blob = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
        ImageDraw.Draw(blob).ellipse((0, 0, 2 * r, 2 * r), fill=col)
        blob = blob.filter(ImageFilter.GaussianBlur(r / 3.0))
        img.paste(blob, (cx - r, cy - r), blob)

    # foxing - small rust-coloured age spots
    for _ in range(rng.randint(50, 110)):
        cx, cy = rng.randint(0, W), rng.randint(0, H)
        r = rng.randint(2, 11)
        a = rng.randint(14, 46)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(126, 88, 44, a))

    # edge darkening / handling grime
    edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ed = ImageDraw.Draw(edge)
    band = rng.randint(60, 130)
    for i in range(band):
        a = int(30 * (1 - i / float(band)) ** 2)
        if a <= 0:
            continue
        ed.rectangle((i, i, W - 1 - i, H - 1 - i), outline=(120, 92, 50, a))
    edge = edge.filter(ImageFilter.GaussianBlur(9))
    img = Image.alpha_composite(img.convert("RGBA"), edge).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # a coffee-cup ring, occasionally
    if rng.random() < 0.25:
        cx, cy = rng.randint(300, W - 300), rng.randint(300, H - 300)
        r = rng.randint(120, 190)
        ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(ring).ellipse((cx - r, cy - r, cx + r, cy + r),
                                     outline=(122, 84, 38, 40), width=rng.randint(6, 14))
        ring = ring.filter(ImageFilter.GaussianBlur(3))
        img = Image.alpha_composite(img.convert("RGBA"), ring).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

    # fold crease
    if rng.random() < 0.55:
        y = rng.choice([H // 3, H // 2, 2 * H // 3]) + rng.randint(-40, 40)
        cr = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        cd = ImageDraw.Draw(cr)
        cd.line((0, y, W, y + rng.randint(-8, 8)), fill=(110, 88, 52, 46), width=3)
        cd.line((0, y - 4, W, y - 4 + rng.randint(-8, 8)),
                fill=(255, 252, 238, 60), width=3)
        cr = cr.filter(ImageFilter.GaussianBlur(2.5))
        img = Image.alpha_composite(img.convert("RGBA"), cr).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

    # ruled lines
    if ruled:
        y = TOP + line_h - 14
        while y < BOTTOM + 40:
            a = rng.randint(26, 46)
            d.line((LEFT - 70, y + rng.uniform(-1.5, 1.5),
                    RIGHT + 60, y + rng.uniform(-1.5, 1.5)),
                   fill=(96, 118, 150, a), width=2)
            y += line_h
    if margin_rule:
        x = LEFT - 46
        d.line((x, 60, x + rng.uniform(-3, 3), H - 60),
               fill=(168, 74, 74, rng.randint(48, 78)), width=3)

    # three-hole punch down the left edge
    for hy in (int(H * 0.18), int(H * 0.5), int(H * 0.82)):
        hy += rng.randint(-14, 14)
        hx = rng.randint(52, 66)
        r = 22
        d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=(196, 186, 162, 255))
        d.ellipse((hx - r, hy - r, hx + r, hy + r), outline=(140, 126, 96, 200),
                  width=3)

    # paper grain
    noise = Image.effect_noise((W, H), 26).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    img = Image.blend(img, Image.merge("RGB", (noise, noise, noise)), 0.055)
    return img


# --------------------------------------------------------------------------
# handwriting
# --------------------------------------------------------------------------

def draw_line(layer, x, y, text, f, ink, rng):
    """Draw one line word by word with jitter, onto an RGBA ink layer."""
    if layer is None:
        return
    d = ImageDraw.Draw(layer)
    cx = x + rng.uniform(-6, 6)
    baseline_drift = rng.uniform(-0.010, 0.010)
    space = measure(f, "n ") - measure(f, "n")
    for word in text.split(" "):
        if not word:
            cx += space
            continue
        dy = rng.uniform(-3.5, 3.5) + (cx - x) * baseline_drift
        a = rng.randint(196, 255)
        if rng.random() < 0.06:          # a word gone over twice, darker
            a = 255
        col = (ink[0], ink[1], ink[2], a)
        d.text((cx, y + dy), word, font=f, fill=col)
        cx += measure(f, word) + space * rng.uniform(0.9, 1.22)


def lay_out(blocks, hand, ink, rng, scale, layer):
    """Place (and, when layer is not None, draw) one page. Returns (y, gt).

    Word-level jitter adds a little width, so text is wrapped to a slightly
    narrower column than the ink is allowed to occupy.
    """
    _, base_size, nudge = FONTS[hand]
    f = font(hand, base_size * scale)
    f_title = font(hand, base_size * scale * 1.18)
    lh = LINE_H * scale
    wrapw = TEXTW - 60

    gt, y = [], TOP + nudge * scale

    for blk in blocks:
        k = blk[0]

        if k == "b":
            y += BLANK_H * scale

        elif k == "hr":
            if layer is not None:
                yy = y + 6
                ImageDraw.Draw(layer).line(
                    (LEFT - 10, yy, RIGHT - rng.randint(0, 120), yy + rng.uniform(-4, 4)),
                    fill=(ink[0], ink[1], ink[2], 220), width=3)
            y += BLANK_H * scale

        elif k == "t":
            s = blk[1]
            if hand == "pemberton":      # this hand's capitals are unreadable
                s = s.title()
            draw_line(layer, LEFT + rng.uniform(0, 40), y, s, f_title, ink, rng)
            gt.append(s)
            y += lh * 1.15

        elif k == "sig":
            y += 10 * scale
            draw_line(layer, LEFT + rng.uniform(360, 520), y, blk[1], f_title, ink, rng)
            gt.append(blk[1])
            y += lh

        elif k == "kv":
            label, val = blk[1], blk[2]
            if label:
                draw_line(layer, LEFT, y, label + ":", f, ink, rng)
            vx = LEFT + 420 * scale
            vlines = wrap_px(val, f, RIGHT - vx - 40)
            for i, ln in enumerate(vlines):
                draw_line(layer, vx, y + i * lh, ln, f, ink, rng)
            gt.append(("%s: %s" % (label, val)) if label else val)
            y += lh * len(vlines)

        elif k == "l":
            s, ff = blk[1], f
            if measure(f, s) > wrapw:    # squeeze an over-long ruled line
                ff = font(hand, base_size * scale * wrapw / float(measure(f, s)) * 0.97)
            draw_line(layer, LEFT, y, s, ff, ink, rng)
            gt.append(s)
            y += lh

        elif k == "p":
            for i, ln in enumerate(wrap_px(blk[1], f, wrapw)):
                draw_line(layer, LEFT + (28 if i == 0 else 0), y, ln, f, ink, rng)
                gt.append(ln)
                y += lh

    return y, gt


def render_page(blocks, pageno, rng):
    hand = PAGE_HAND[pageno]
    ink = INKS[rng.randrange(len(INKS))]

    # dry pass: how tall is the page at full size? cram the hand if it overruns
    probe = random.Random(pageno * 7919)
    need, _ = lay_out(blocks, hand, ink, probe, 1.0, None)
    avail = BOTTOM - TOP
    scale = 1.0
    if need - TOP > avail:
        scale = max(0.80, avail / float(need - TOP))
        print("  page %2d: cramming to %.0f%% to fit" % (pageno, scale * 100))

    ruled = pageno not in (1, 15, 16)
    paper = make_paper(rng, ruled, margin_rule=rng.random() < 0.6,
                       line_h=LINE_H * scale)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    y, gt = lay_out(blocks, hand, ink, rng, scale, layer)

    overflow = y > BOTTOM + LINE_H
    if overflow:
        print("  ! page %d still overruns by %.0f px" % (pageno, y - BOTTOM))

    # ink bleed into the paper fibres
    bleed = layer.filter(ImageFilter.GaussianBlur(2.2))
    bleed.putalpha(bleed.getchannel("A").point(lambda v: int(v * 0.40)))
    page = Image.alpha_composite(paper.convert("RGBA"), bleed)
    page = Image.alpha_composite(page, layer.filter(ImageFilter.GaussianBlur(0.6)))
    page = page.convert("RGB")

    # show-through of writing on the reverse of the sheet
    if rng.random() < 0.5:
        ghost = layer.transpose(Image.FLIP_LEFT_RIGHT)
        ghost = ghost.filter(ImageFilter.GaussianBlur(4))
        ghost.putalpha(ghost.getchannel("A").point(lambda v: int(v * 0.10)))
        page = Image.alpha_composite(page.convert("RGBA"), ghost).convert("RGB")

    # scanner: small skew, soft focus, contrast loss, sensor noise
    ang = rng.uniform(-1.1, 1.1)
    fill = page.getpixel((W // 2, 30))
    page = page.rotate(ang, resample=Image.BICUBIC, fillcolor=fill)
    page = page.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    page = ImageEnhance.Contrast(page).enhance(rng.uniform(0.86, 0.97))
    page = ImageEnhance.Brightness(page).enhance(rng.uniform(0.97, 1.04))

    n = Image.effect_noise((W, H), rng.randint(8, 16)).convert("L")
    page = Image.blend(page, Image.merge("RGB", (n, n, n)), 0.035)

    # a dark scanner edge on one side, as when the lid does not close flat
    if rng.random() < 0.4:
        sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        wdt = rng.randint(18, 46)
        if rng.random() < 0.5:
            sd.rectangle((0, 0, wdt, H), fill=(20, 16, 10, 150))
        else:
            sd.rectangle((W - wdt, 0, W, H), fill=(20, 16, 10, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(14))
        page = Image.alpha_composite(page.convert("RGBA"), sh).convert("RGB")

    return page, gt, overflow


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    pdf_path = os.path.join(outdir, "ocr_test_handwritten_aged_20p.pdf")
    c = canvas.Canvas(pdf_path, pagesize=LETTER)
    c.setTitle("Ward Chart - Brennan, Arthur L. - Unit No. 22-84-016")
    c.setAuthor("Providence Mercy Hospital")
    c.setSubject("Synthetic handwritten record for OCR testing")

    rng = random.Random(20260817)
    all_gt, bad = [], []
    tmp = os.path.join(outdir, "_pages")
    os.makedirs(tmp, exist_ok=True)

    for i, blocks in enumerate(handwritten_pages(), 1):
        img, gt, over = render_page(blocks, i, rng)
        if over:
            bad.append(i)
        jp = os.path.join(tmp, "p%02d.jpg" % i)
        img.save(jp, "JPEG", quality=74, optimize=True)
        c.drawImage(ImageReader(jp), 0, 0, width=LETTER[0], height=LETTER[1])
        c.showPage()
        all_gt.append(gt)
    c.save()

    gt_path = os.path.join(outdir, "ocr_test_handwritten_aged_20p.groundtruth.txt")
    with open(gt_path, "w", encoding="utf-8") as fh:
        for i, lines in enumerate(all_gt, 1):
            fh.write("=== PAGE %d ===\n" % i)
            fh.write("\n".join(lines))
            fh.write("\n\n")

    phi_path = os.path.join(outdir, "ocr_test_handwritten_aged_20p.phi.txt")
    with open(phi_path, "w", encoding="utf-8") as fh:
        fh.write("# Expected PHI entities - handwritten document\n")
        fh.write("# format: TYPE<TAB>surface form\n")
        for k in sorted(HANDWRITTEN_PHI):
            for v in HANDWRITTEN_PHI[k]:
                fh.write("%s\t%s\n" % (k, v))

    nwords = sum(len(" ".join(p).split()) for p in all_gt)
    print("handwritten: %s (%.1f MB, %d words)%s"
          % (pdf_path, os.path.getsize(pdf_path) / 1048576.0, nwords,
             "  OVERFLOW ON %s" % bad if bad else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
