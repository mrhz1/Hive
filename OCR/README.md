# OCR PDF De-identifier

Scans PDFs with OCR, detects PII/PHI, and writes a genuinely redacted
PDF. Pure Python, no Docker, no system binaries — built to run as a
Cloudera AI job and later be triggered by the FastAPI/Hive service with a
path to process.

**Models** (both pinned in `deid/config.py`, swappable by env var):

| role | model |
|---|---|
| OCR detection | `PP-OCRv6_medium_det` (PaddleOCR ≥3.7.0) |
| OCR recognition | `PP-OCRv6_medium_rec` |
| tokenization/lemmatization | spaCy `en_core_web_sm` |
| NER | `StanfordAIMI/stanford-deidentifier-base` via Presidio |

## Setup

```bash
cd OCR
python3.10 -m venv .venv                     # Presidio supports 3.10–3.13
.venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m spacy download en_core_web_sm
.venv/bin/python scripts/download_models.py  # pre-fetch all weights
```

Install torch from the CPU index **first** — otherwise pip pulls the
~2.5GB CUDA build for what is a CPU job.

`scripts/download_models.py` is not optional in practice: Cloudera AI job
runs shouldn't be pulling hundreds of MB on first request, and may have
no egress at all. Run it at environment build time.

## Usage

```bash
# one file
.venv/bin/python scripts/run_deid.py --input doc.pdf --output-dir out/

# a directory
.venv/bin/python scripts/run_deid.py --input /data/pdfs --recursive --output-dir out/

# env-var form (how a Cloudera job usually passes arguments)
DEID_INPUT=/data/pdfs DEID_OUTPUT_DIR=/data/out .venv/bin/python scripts/run_deid.py
```

For each `doc.pdf` you get `doc_deid.pdf`, `doc_deid.txt` (de-identified
text, entities replaced by `<PERSON>` etc.), and `doc_deid.report.json`
(counts, models, settings, per-page stats).

Exit codes: `0` all OK, `1` everything failed, `2` partial. A JSON summary
goes to stdout so the caller can parse it.

### Verifying a redaction

A report saying "20 entities redacted" proves 20 boxes were drawn, not
that the information is gone. `verify_redaction.py` re-OCRs the output the
way an attacker would and fails if any secret survives — in the pixels or
in a leftover text layer:

```bash
make run && make verify        # against the synthetic sample
.venv/bin/python scripts/verify_redaction.py out/doc_deid.pdf \
    --expect-absent "Jane Doe" --expect-absent "543-22-9087"
```

It also checks that content which *should* survive still does — a
redactor that blacks out the whole page would otherwise pass a leak test
while being useless. Exit `0` clean, `1` leak, `2` over-redacted.

Current result on the synthetic discharge summary: all 11 planted
identifiers removed, `chest pain` / `troponins` / `ejection fraction`
retained, 0 residual text-layer characters.

## How it works

Per page: rasterise at `OCR_DPI` → PP-OCRv6 det+rec → join line spans into
page text (tracking each span's character range) → Presidio analyse →
map entity character offsets back to pixel boxes → redact.

Models load once per job run and are reused across every page and file —
that load dominates cost, so batch many PDFs into one invocation rather
than one process per file.

### Redaction is real, not cosmetic

Redaction uses PyMuPDF's `add_redact_annot` + `apply_redactions(images=
PDF_REDACT_IMAGE_PIXELS)`, which **removes** the underlying content and
blanks image pixels inside the box. Drawing black rectangles would leave
any text layer selectable underneath — the classic redaction failure that
has leaked documents in the real world. This matters for PDFs that have
both a scan and an embedded text layer.

## Configuration

All env vars, all with defaults — nothing branches on environment, only
values change between local and Cloudera AI.

| var | default | notes |
|---|---|---|
| `OCR_DET_MODEL` / `OCR_REC_MODEL` | `PP-OCRv6_medium_*` | `_small_`/`_tiny_` are faster, less accurate |
| `OCR_DPI` | `200` | below ~150 recognition degrades on small print |
| `OCR_DEVICE` | `cpu` | `gpu:0` if the job node has one |
| `OCR_MIN_CONFIDENCE` | `0.5` | drop noisy OCR spans |
| `DEID_SCORE_THRESHOLD` | `0.35` | deliberately low — see below |
| `DEID_ENTITIES` | see `config.py` | comma-separated override |
| `DEID_REDACT_WHOLE_SPAN` | `false` | `true` = redact the whole OCR line if any part is PII |
| `DEID_BOX_PADDING` | `2.0` | pixels of growth around each box |
| `DEID_REPORT_INCLUDE_VALUES` | `false` | off by design — see below |

**Why the threshold is low (0.35).** For de-identification a false
positive costs a redacted word; a false negative leaks PHI. The asymmetry
justifies over-redacting.

**Why `DEID_REPORT_INCLUDE_VALUES` defaults off.** A report listing the
PII you just redacted is itself a PHI leak, and it would land next to the
sanitised output. Turn it on only for debugging, never in production.

**`DEID_REDACT_WHOLE_SPAN`.** Default off: within an OCR line, the box is
narrowed proportionally to the entity's character range, so "Patient:
John Smith" redacts only the name. That estimate assumes even character
widths, which proportional fonts violate — `DEID_BOX_PADDING` absorbs the
error. Set `DEID_REDACT_WHOLE_SPAN=true` for the conservative mode: any
line containing PII is covered entirely. Slower to read, impossible to
under-redact.

## Accuracy notes

`stanford-deidentifier-base` emits only `VENDOR, DATE, HCW, HOSPITAL, ID,
PATIENT, PHONE` (verified against the model's `config.json`). Two gaps
follow, both closed in `deid/recognizers.py`:

- **No location/address label.** HIPAA Safe Harbor requires removing
  geographic subdivisions below state level, so custom pattern
  recognizers add `STREET_ADDRESS` and `US_ZIP_CODE`.
- **No age handling.** Safe Harbor treats ages > 89 as identifiers, so
  `AGE` matches only those — redacting every age would destroy clinical
  utility for no privacy gain.

Also added: `MRN` (context-driven, since formats vary per site). Presidio's
built-in pattern/checksum recognizers (SSN, credit card, IBAN, email, IP,
passport, driver's licence…) run alongside the NER model and fire
independently of it.

To tune further: raise `stride` or switch `aggregation_strategy` in
`deid/analyzer.py`, add site-specific patterns to `deid/recognizers.py`,
or add `context` words — Presidio boosts a pattern's score when context
words appear nearby, which is what makes the bare 5-digit ZIP pattern
usable rather than noise.

## Gotchas hit while building this

**oneDNN crashes the PP-OCRv6 detector on paddlepaddle 3.3.1.** Inference
dies with `NotImplementedError: ConvertPirAttribute2RuntimeAttribute not
support [pir::ArrayAttribute<pir::DoubleAttribute>]` from the PIR
executor's oneDNN path. `OCR_ENABLE_MKLDNN` therefore defaults to
`false`, which makes PaddleX pick `run_mode="paddle"`. oneDNN is normally
a CPU speedup, so re-test and re-enable it on a newer paddlepaddle.

**Presidio returns overlapping spans.** The NER model tags
"Springfield, IL" as ORGANIZATION while the ZIP recognizer tags
"IL 62704" — same characters, two detections. Left as-is this corrupts
the redacted text (inserting one tag mangles another) and doubles the
boxes. `merge_overlapping()` in `deid/analyzer.py` collapses them into
disjoint spans, keeping the highest-scoring label. On the sample this cut
32 raw detections to 20 real ones.

**The NER model download is the slow part** (~440MB `pytorch_model.bin`,
no safetensors in the repo). `scripts/fetch_ner_model.py` downloads it
with resume + retries and `max_workers=1`, which survives a flaky link
far better than parallel range requests. It took ~14 minutes here.

## Limitations

- **OCR errors propagate.** A name the OCR misreads is a name the NER
  model may not recognise, and an entity that is never detected is never
  redacted. Low-quality scans need a higher `OCR_DPI` and should be spot
  checked.
- **Verification is a separate step.** `run_deid.py` does not
  automatically re-OCR its own output; `verify_redaction.py` does, but you
  have to run it (and tell it what to look for). Wiring it into the job as
  a mandatory gate is the right move for a compliance workflow.
- **Entity labels are approximate.** "Insurance ID: BCBS-7741820394" gets
  tagged `PHONE_NUMBER` on the sample. It is still redacted, which is what
  matters here, but do not treat the report's label breakdown as ground
  truth for analytics.
- **English only.** The NLP config is `en`; PP-OCRv6 itself handles 50
  languages, so multilingual support needs a matching NER model.

## Layout

```
OCR/
  deid/
    config.py        env-driven config, model pins, entity mapping
    ocr_engine.py    PaddleOCR PP-OCRv6 wrapper -> OcrSpan list
    analyzer.py      Presidio + transformers NLP engine
    recognizers.py   custom address/ZIP/MRN/age recognizers
    mapping.py       char offsets <-> pixel boxes
    pdf_io.py        rasterise + true redaction (PyMuPDF)
    pipeline.py      orchestration, reporting
  scripts/
    run_deid.py         job entrypoint (CLI or env vars)
    download_models.py  pre-fetch all weights
    make_sample_pdf.py  synthetic test document
```
