"""Render the printed 20-page clinical record + its ground-truth text."""
import os
import sys

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from content import PRINTED_HEADER, PRINTED_PHI, printed_pages  # noqa: E402

PW, PH = LETTER
ML, MR = 0.85 * inch, 0.85 * inch
MT, MB = 0.95 * inch, 0.85 * inch
COLW = PW - ML - MR

BODY = "Times-Roman"
BODY_B = "Times-Bold"
BODY_I = "Times-Italic"
SANS = "Helvetica"
SANS_B = "Helvetica-Bold"


def wrap(text, font, size, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = w if not cur else cur + " " + w
        if pdfmetrics.stringWidth(trial, font, size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


class Renderer:
    def __init__(self, path):
        self.c = canvas.Canvas(path, pagesize=LETTER)
        self.c.setTitle("Inpatient Record - Whitfield, Grace E. - MRN 40-77-1592")
        self.c.setAuthor("Saint Bartholomew Regional Medical Center")
        self.c.setSubject("Synthetic clinical record for OCR testing")
        self.gt = []          # ground-truth lines for the current page
        self.pages_gt = []

    # -- primitives ------------------------------------------------------
    def text(self, x, y, s, font, size, gt=True):
        self.c.setFont(font, size)
        self.c.drawString(x, y, s)
        if gt and s.strip():
            self.gt.append(s)

    def chrome(self, pageno):
        c = self.c
        c.setFont(SANS_B, 8)
        c.drawString(ML, PH - 0.62 * inch, PRINTED_HEADER[0].upper())
        c.setFont(SANS, 8)
        c.drawRightString(PW - MR, PH - 0.62 * inch, PRINTED_HEADER[1])
        c.setLineWidth(0.6)
        c.line(ML, PH - 0.70 * inch, PW - MR, PH - 0.70 * inch)
        c.line(ML, MB - 0.24 * inch, PW - MR, MB - 0.24 * inch)
        c.setFont(SANS, 7.5)
        c.drawString(ML, MB - 0.40 * inch,
                     "Whitfield, Grace E.   MRN 40-77-1592   DOB 03/14/1951")
        c.drawRightString(PW - MR, MB - 0.40 * inch, "Page %d of 20" % pageno)
        c.drawCentredString(PW / 2, MB - 0.40 * inch, "CONFIDENTIAL - PHI")
        self.gt.insert(0, PRINTED_HEADER[0].upper())
        self.gt.insert(1, PRINTED_HEADER[1])
        self.gt.append("Whitfield, Grace E.   MRN 40-77-1592   DOB 03/14/1951")
        self.gt.append("CONFIDENTIAL - PHI")
        self.gt.append("Page %d of 20" % pageno)

    # -- blocks ----------------------------------------------------------
    def page(self, blocks, pageno):
        c = self.c
        self.gt = []
        y = PH - MT

        for blk in blocks:
            kind = blk[0]

            if kind == "h1":
                y -= 4
                self.text(ML, y, blk[1], SANS_B, 13.5)
                y -= 17

            elif kind == "h2":
                y -= 8
                self.text(ML, y, blk[1], SANS_B, 10.5)
                y -= 12

            elif kind == "rule":
                c.setLineWidth(1.1)
                c.line(ML, y + 4, PW - MR, y + 4)
                y -= 6

            elif kind == "space":
                y -= blk[1]

            elif kind == "p":
                for ln in wrap(blk[1], BODY, 11, COLW):
                    self.text(ML, y, ln, BODY, 11)
                    y -= 13.7
                y -= 4

            elif kind == "small":
                for ln in wrap(blk[1], BODY_I, 8.8, COLW):
                    self.text(ML, y, ln, BODY_I, 8.8)
                    y -= 10
                y -= 3

            elif kind == "sig":
                y -= 6
                self.text(ML, y, blk[1], BODY_I, 10)
                y -= 13

            elif kind == "bullets":
                for item in blk[1]:
                    ind = ML + 14
                    lines = wrap(item, BODY, 11, COLW - 14)
                    self.text(ML + 4, y, "•", BODY, 11, gt=False)
                    for i, ln in enumerate(lines):
                        self.text(ind, y, ln, BODY, 11)
                        y -= 13.7
                    y -= 3
                y -= 3

            elif kind == "numbered":
                for n, item in enumerate(blk[1], 1):
                    ind = ML + 20
                    lines = wrap(item, BODY, 11, COLW - 20)
                    self.text(ML + 2, y, "%d." % n, BODY, 11, gt=False)
                    self.gt.append("%d. %s" % (n, lines[0]))
                    self.text(ind, y, lines[0], BODY, 11, gt=False)
                    y -= 13.7
                    for ln in lines[1:]:
                        self.text(ind, y, ln, BODY, 11)
                        y -= 13.7
                    y -= 3
                y -= 3

            elif kind == "kv2":
                pairs = blk[1]
                colw = COLW / 2
                for i in range(0, len(pairs), 2):
                    row = pairs[i:i + 2]
                    gtparts = []
                    for j, (k, v) in enumerate(row):
                        x = ML + j * colw
                        self.text(x, y, k + ":", SANS_B, 9.2, gt=False)
                        kw = pdfmetrics.stringWidth(k + ":", SANS_B, 9.2)
                        vx = x + max(kw + 6, 104)
                        avail = colw - (vx - x) - 8
                        vlines = wrap(v, BODY, 9.8, avail)
                        self.text(vx, y, vlines[0], BODY, 9.8, gt=False)
                        if len(vlines) > 1:
                            self.text(vx, y - 11.5, " ".join(vlines[1:]), BODY, 9.8,
                                      gt=False)
                        gtparts.append("%s: %s" % (k, v))
                    self.gt.append("   ".join(gtparts))
                    y -= 23 if any(len(wrap(v, BODY, 9.8, colw - 112)) > 1
                                   for _, v in row) else 13.6
                y -= 5

            elif kind == "table":
                hdrs, rows, widths = blk[1], blk[2], blk[3]
                scale = COLW / float(sum(widths))
                widths = [w * scale for w in widths]
                xs = [ML]
                for w in widths[:-1]:
                    xs.append(xs[-1] + w)
                rowh = 15.2

                c.setFillGray(0.88)
                c.rect(ML, y - 4, COLW, rowh, stroke=0, fill=1)
                c.setFillGray(0.0)
                for x, h in zip(xs, hdrs):
                    self.text(x + 3, y, h, SANS_B, 8.8, gt=False)
                self.gt.append(" | ".join(hdrs))
                y -= rowh

                c.setLineWidth(0.4)
                for r in rows:
                    cell_lines = [wrap(str(v), BODY, 9.3, w - 6)
                                  for v, w in zip(r, widths)]
                    nl = max(len(cl) for cl in cell_lines)
                    h = rowh + (nl - 1) * 10.4
                    for x, cl in zip(xs, cell_lines):
                        yy = y
                        for ln in cl:
                            self.text(x + 3, yy, ln, BODY, 9.3, gt=False)
                            yy -= 10.4
                    self.gt.append(" | ".join(str(v) for v in r))
                    c.line(ML, y - 4, PW - MR, y - 4)
                    y -= h
                c.setLineWidth(0.4)
                for x in xs[1:]:
                    pass
                y -= 6

        self.chrome(pageno)
        self.pages_gt.append(self.gt)
        c.showPage()

    def save(self):
        self.c.save()


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    pdf = os.path.join(outdir, "ocr_test_printed_20p.pdf")
    r = Renderer(pdf)
    for i, blocks in enumerate(printed_pages(), 1):
        r.page(blocks, i)
    r.save()

    gt = os.path.join(outdir, "ocr_test_printed_20p.groundtruth.txt")
    with open(gt, "w", encoding="utf-8") as f:
        for i, lines in enumerate(r.pages_gt, 1):
            f.write("=== PAGE %d ===\n" % i)
            f.write("\n".join(lines))
            f.write("\n\n")

    phi = os.path.join(outdir, "ocr_test_printed_20p.phi.txt")
    with open(phi, "w", encoding="utf-8") as f:
        f.write("# Expected PHI entities - printed document\n")
        f.write("# format: TYPE<TAB>surface form\n")
        for k in sorted(PRINTED_PHI):
            for v in PRINTED_PHI[k]:
                f.write("%s\t%s\n" % (k, v))

    nwords = sum(len(" ".join(p).split()) for p in r.pages_gt)
    print("printed  : %s (%.0f KB, %d words)"
          % (pdf, os.path.getsize(pdf) / 1024.0, nwords))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
