# OCR de-identification

Finds and redacts PII/PHI in PDF, DICOM and Word files. The output keeps
the same format as the input.

- PDF: OCR the pages, black out PII (the content under the box is removed,
  not just covered), clean metadata.
- DICOM: OCR the image, black out text burned into the pixels, clean the
  tags, remove private tags.
- Word: replace PII in the text, clean the document properties.

Deployment steps are in [DEPLOY.md](DEPLOY.md).

Models (set in `deid/config.py`):

| | model |
|---|---|
| OCR detection | `PP-OCRv6_medium_det` (PaddleOCR) |
| OCR recognition | `PP-OCRv6_medium_rec` |
| spaCy | `en_core_web_sm` |
| NER | `StanfordAIMI/stanford-deidentifier-base` (via Presidio) |

## Two venvs

PaddleOCR and Presidio can't be installed together (PaddleX pins
`PyYAML==6.0.2`, Presidio needs `>=6.0.3`). So the pipeline runs in two
processes:

```
scripts/run_deid.py           standard library only
  ├── stage 1  .venv-ocr      paddleocr + PyMuPDF   -> spans JSON (text + boxes)
  └── stage 2  .venv-nlp      presidio + torch      -> redacted file + text + report
```

The spans JSON contains the OCR text, so it's PHI. It's written to a
private temp folder and deleted afterwards. Stage 2 redacts the original
file using the boxes from stage 1.

## Models

CML can't reach GitHub or Hugging Face, so the models are stored in
`OCR/models/` and loaded from there (see [models/README.md](models/README.md)).
`DEID_OFFLINE=true` (default) blocks any download attempt, so a missing
model fails right away.

## Setup

On a machine with internet:

```bash
cd OCR
make venvs
make install        # torch comes from the CPU index
make models         # ~570MB
make check-models   # load every model offline
make preflight
```

## Usage

```bash
python3 scripts/run_deid.py --input doc.pdf --output-dir out/
python3 scripts/run_deid.py --input /data/pdfs --recursive --output-dir out/
DEID_INPUT=/data/pdfs DEID_OUTPUT_DIR=/data/out python3 scripts/run_deid.py
python3 scripts/run_deid.py --preflight
```

For `doc.pdf` you get `doc_deid.pdf`, `doc_deid.txt` (text with `<PERSON>`
etc.) and `doc_deid.report.json`. A JSON summary is printed to stdout.
Exit code 0 = ok, 1 = all failed, 2 = some failed.

Put many files in one call, the models load once per call.

### Checking a redaction

```bash
make run && make verify
.venv-ocr/bin/python scripts/verify_redaction.py out/doc_deid.pdf \
    --expect-absent "Jane Doe" --expect-absent "543-22-9087"
```

It OCRs the output again and checks the given values are gone, and that
normal clinical text is still there. Exit 0 = ok, 1 = leak,
2 = over-redacted. On the sample file all 11 test identifiers are removed.

## How it works

1. Stage 1: render each page at `OCR_DPI`, run PaddleOCR, save text + box
   per line.
2. Stage 2: join the lines into page text, run Presidio, map each entity
   back to its box, redact the original file.

Metadata goes through the same analyzer, so values are replaced in place
(`PatientName: Doe^Jane -> <PERSON>`) and useful fields like `Modality` stay.
Fields that always contain a name (DICOM PN tags, PDF/Word author) are set
to `<REMOVED>` if the analyzer finds nothing. For DICOM:

- only text VRs (`PN`, `LO`, `SH`, `ST`, `LT`, `UT`, `UC`) are redacted,
  `CS` codes are left alone
- dates and numbers are emptied
- UIDs are not changed
- private tags are removed
- sequences are checked too

## Settings

| var | default | |
|---|---|---|
| `OCR_DET_MODEL` / `OCR_REC_MODEL` | `PP-OCRv6_medium_*` | |
| `OCR_DPI` | `200` | lower than ~150 hurts small text |
| `OCR_DEVICE` | `cpu` | `gpu:0` if available |
| `OCR_MIN_CONFIDENCE` | `0.5` | |
| `OCR_CPU_THREADS` | `8` | |
| `DEID_SCORE_THRESHOLD` | `0.35` | low on purpose, better to over-redact |
| `DEID_ENTITIES` | see `config.py` | comma-separated |
| `DEID_REDACT_WHOLE_SPAN` | `false` | `true` blacks out the whole line |
| `DEID_BOX_PADDING` | `2.0` | pixels |
| `DEID_REPORT_INCLUDE_VALUES` | `false` | puts the found PII in the report, debugging only |
| `DEID_MODELS_DIR` | `OCR/models` | |
| `DEID_OFFLINE` | `true` | |
| `DEID_OCR_PYTHON` / `DEID_NLP_PYTHON` | `OCR/.venv-*/bin/python` | |
| `DEID_WORK_DIR` | temp dir | |
| `DEID_KEEP_WORK_DIR` | `false` | debugging only, leaves PHI on disk |
| `DEID_LOG_STAGE_OUTPUT` | `false` | |

## Custom recognizers

The Stanford model only has `VENDOR, DATE, HCW, HOSPITAL, ID, PATIENT,
PHONE`. `deid/recognizers.py` adds:

- `STREET_ADDRESS` and `US_ZIP_CODE`
- `AGE` (only ages over 89, as HIPAA requires)
- `MRN`

Presidio's built-in recognizers (SSN, email, credit card, etc.) run too.
Overlapping results are merged in `analyzer.py` (`merge_overlapping`).

## Known issues

- oneDNN crashes the detector on paddlepaddle 3.3.1, so
  `OCR_ENABLE_MKLDNN` is off by default.
- DICOM decoding needs `pylibjpeg`, `pylibjpeg-libjpeg` and
  `pylibjpeg-openjpeg` in both venvs, otherwise most compressed CT/MR files
  fail. Output is written uncompressed.
- The Hugging Face cache uses symlinks, so don't copy it directly.
  `stage_models.py` copies real files.
- PaddleOCR and Presidio try to download models if you pass a name instead
  of a path. `model_store.py` always passes paths.
- spaCy warnings can include document text, so stage stderr is only logged
  on failure (or with `DEID_LOG_STAGE_OUTPUT`).
- OCR mistakes carry over: text the OCR misreads may not be detected.
  Check low-quality scans.
- Entity labels in the report aren't always right, but the text is still
  redacted.
- English only.

## Layout

```
OCR/
  requirements-ocr.txt   stage 1 (don't install both into one venv)
  requirements-nlp.txt   stage 2
  deid/
    config.py        settings and model names
    model_store.py   finds models on disk, offline mode
    spans.py         data passed between stages
    results.py       results and exit codes
    mapping.py       text offsets <-> boxes
    pdf_io.py        PDF render + redact
    pipeline.py      runs the two stages (stdlib only)
    ocr_engine.py    PaddleOCR wrapper          (.venv-ocr)
    stage_ocr.py     stage 1                    (.venv-ocr)
    analyzer.py      Presidio setup             (.venv-nlp)
    recognizers.py   custom recognizers         (.venv-nlp)
    stage_nlp.py     stage 2                    (.venv-nlp)
  scripts/
    run_deid.py          entry point
    stage_ocr.py / stage_nlp.py
    stage_models.py      download models
    check_models.py      load models offline
    verify_redaction.py  check the output for leaks
    make_sample_pdf.py   test document
  models/
```

Shared modules (`config`, `spans`, `mapping`, `pdf_io`, `pipeline`, ...)
must not import from the stage-specific ones.
