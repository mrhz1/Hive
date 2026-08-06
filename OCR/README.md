# OCR PDF De-identifier

Scans PDFs with OCR, detects PII/PHI, and writes a genuinely redacted
PDF. Pure Python, no Docker, no system binaries — built to run as a
Cloudera AI job and be triggered by the FastAPI/Hive service with a path
to process.

> **Deploying this?** [`DEPLOY.md`](DEPLOY.md) is the runbook: every
> command from empty checkout to a Job the dashboard's De-identify button
> triggers, including the Application → Job wiring code. This file is the
> reference for how the thing works.

**Models** (all pinned in `deid/config.py`, swappable by env var):

| role | model |
|---|---|
| OCR detection | `PP-OCRv6_medium_det` (PaddleOCR ≥3.7.0) |
| OCR recognition | `PP-OCRv6_medium_rec` |
| tokenization/lemmatization | spaCy `en_core_web_sm` |
| NER | `StanfordAIMI/stanford-deidentifier-base` via Presidio |

## Two virtualenvs, and why

**PaddleOCR and Presidio cannot be installed together.** The conflict is
exact:

```
paddleocr → paddlex           pins  PyYAML==6.0.2
presidio-analyzer ≥ 2.2.363   needs pyyaml>=6.0.3
```

pip has no solution. Reproduce it in one line:

```bash
uv pip compile - <<< $'paddleocr>=3.7.0\npresidio-analyzer==2.2.364'
# × No solution found when resolving dependencies
```

Pinning presidio back to 2.2.362 *does* resolve today. That is the wrong
fix: it freezes de-identification — the part of this system with actual
compliance consequences — at whatever release happens to predate the
clash, and it breaks again the next time either package moves. Beyond the
metadata, the two stacks each ship their own OpenMP runtime, and torch
(~3GB with CUDA, ~200MB CPU-only) is dead weight in the OCR half.

So the pipeline runs as two processes:

```
                 scripts/run_deid.py          ← stdlib only, no venv needed
                   ├── stage 1  .venv-ocr     paddleocr + paddlepaddle + PyMuPDF
                   │      ↓  spans JSON (text + pixel geometry)
                   └── stage 2  .venv-nlp     presidio + transformers + torch + PyMuPDF
                          ↓  redacted PDF + text + report
```

`run_deid.py` is the **orchestrator** and imports nothing outside the
standard library, so the Cloudera runtime's stock python can run it with
nothing installed. Only the two stage subprocesses need dependencies.

The handoff file holds raw OCR text, so **it is PHI**. It lives in a 0700
temp directory written 0600 and deleted in a `finally`. `DEID_KEEP_WORK_DIR`
keeps it for debugging and must stay off in production.

Note that stage 2 redacts the **original** PDF using stage 1's geometry —
it never re-rasterises, and a stage-2 failure cannot leave a
half-redacted file behind.

## The model store, and why models never download

**Cloudera AI blocks `github.com` and `huggingface.co`**, which is where
all four models normally come from. pip works; model weights do not
arrive over pip.

So the weights live in `OCR/models/`, are loaded **by path**, and are
moved to Cloudera as a file copy. Nothing downloads at job time — see
[`models/README.md`](models/README.md) for the layout and the transfer.

```
models/
  paddle/PP-OCRv6_medium_det/                       133MB, both det+rec
  paddle/PP-OCRv6_medium_rec/
  spacy/en_core_web_sm/                             15MB
  transformers/StanfordAIMI/stanford-deidentifier-base/   419MB
```

Directory names are the model identifiers verbatim — the same strings
`deid/config.py` pins — so swapping a model means dropping in a folder
with the matching name, not editing code. `deid/model_store.py` resolves
them.

`DEID_OFFLINE` defaults to **on**, which means two things: the
HuggingFace offline switches are set before transformers is imported, so
a stray `from_pretrained("org/name")` anywhere in the dependency tree
fails fast instead of hanging on a blocked host until the job times out;
and a model missing from the store raises immediately, naming the
directory it looked in. Set `DEID_OFFLINE=0` only on a machine with
egress.

## Setup

On a machine **with** network access:

```bash
cd OCR
make venvs        # .venv-ocr and .venv-nlp, both python3.10
make install      # both requirement sets; torch comes from the CPU index
make models       # fill models/ from the network — ~570MB, a few minutes
make check-models # load every staged model with the network switched off
make preflight    # interpreters resolvable, models present?
```

Or by hand:

```bash
python3.10 -m venv .venv-ocr && python3.10 -m venv .venv-nlp

.venv-ocr/bin/pip install -r requirements-ocr.txt
.venv-ocr/bin/python scripts/stage_models.py --stage ocr

# torch from the CPU index FIRST, or pip pulls the ~3GB CUDA build.
.venv-nlp/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-nlp/bin/pip install -r requirements-nlp.txt
.venv-nlp/bin/python scripts/stage_models.py --stage nlp
```

Never `pip install -r requirements-ocr.txt -r requirements-nlp.txt` into
one environment. That is the thing that does not work.

Two staging runs, not one, for the same reason: each virtualenv can only
download what it can import.

Then move `models/` to the target and re-run `make check-models` **there**.
That is the check that matters — `--preflight` verifies the directories
exist, which catches an incomplete copy but not a corrupt one, and a
truncated `pytorch_model.bin` otherwise surfaces several minutes into
the first real job.

## Usage

Run with any python — the orchestrator needs no dependencies:

```bash
# one file
python3 scripts/run_deid.py --input doc.pdf --output-dir out/

# a directory
python3 scripts/run_deid.py --input /data/pdfs --recursive --output-dir out/

# env-var form (how a Cloudera job usually passes arguments)
DEID_INPUT=/data/pdfs DEID_OUTPUT_DIR=/data/out python3 scripts/run_deid.py

# is the deployment wired up at all?
python3 scripts/run_deid.py --preflight
```

Point `DEID_OCR_PYTHON` / `DEID_NLP_PYTHON` at the two venvs if they are
not at `OCR/.venv-ocr` and `OCR/.venv-nlp` (on Cloudera AI they must be
absolute paths).

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

# Verification only re-reads, so it runs in the OCR env.
.venv-ocr/bin/python scripts/verify_redaction.py out/doc_deid.pdf \
    --expect-absent "Jane Doe" --expect-absent "543-22-9087"
```

It also checks that content which *should* survive still does — a
redactor that blacks out the whole page would otherwise pass a leak test
while being useless. Exit `0` clean, `1` leak, `2` over-redacted.

Current result on the synthetic discharge summary: all 11 planted
identifiers removed, `chest pain` / `troponins` / `ejection fraction`
retained, 0 residual text-layer characters.

## How it works

**Stage 1** (`.venv-ocr`), per page: rasterise at `OCR_DPI` → PP-OCRv6
det+rec → spans (text + confidence + pixel box) → one JSON per PDF.

**Stage 2** (`.venv-nlp`), per page: join line spans into page text
(tracking each span's character range) → Presidio analyse → map entity
character offsets back to pixel boxes → redact the original PDF.

Models load once per **stage run** and are reused across every page and
file in it — that load dominates cost, so batch many PDFs into one
invocation rather than one process per file. Splitting the pipeline does
not change that: each stage still pays its own load exactly once, and the
paddle models are unloaded before torch is even imported, which halves
peak memory versus the old single-process design.

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
| `DEID_MODELS_DIR` | `OCR/models` | the local model store; a read-only mount is fine |
| `DEID_OFFLINE` | `true` | load models by path only, never download |
| `DEID_OCR_PYTHON` | `OCR/.venv-ocr/bin/python` | stage 1 interpreter |
| `DEID_NLP_PYTHON` | `OCR/.venv-nlp/bin/python` | stage 2 interpreter |
| `DEID_WORK_DIR` | a 0700 temp dir | where the PHI-bearing handoff lands |
| `DEID_KEEP_WORK_DIR` | `false` | debugging only — leaves OCR text on disk |
| `DEID_LOG_STAGE_OUTPUT` | `false` | forward stage stderr even on success |

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
no safetensors in the repo). `scripts/stage_models.py` fetches it with
resume + retries and `max_workers=1`, which survives a flaky link far
better than parallel range requests. It took ~14 minutes here — and it
happens once, on a machine with egress, never on the job node.

**The HuggingFace cache is symlinks, not files.** Every blob in
`~/.cache/huggingface` is a symlink into a content-addressed store, so
copying that directory to another machine produces a model store full of
dangling links — which passes a "does the directory exist?" check and
fails at load time on the far side. `stage_models.py` resolves them
(`snapshot_download(local_dir=...)`, `copytree(symlinks=False)`); the
store is real files only.

**PaddleOCR takes a bare model name as permission to download.** Passing
`text_detection_model_dir` / `text_recognition_model_dir` is what makes
it load locally instead. PaddleX has no offline flag, and before
downloading it probes huggingface/modelscope/aistudio/BOS for
reachability — on a network that drops rather than refuses, that probe is
a multi-minute stall before you even get the real error.
`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK` (set by
`model_store.apply_offline_env()`) skips it.

**Presidio downloads spaCy models it cannot find.**
`SpacyNlpEngine._download_spacy_model_if_needed()` calls
`spacy.cli.download` unless the name is a package *or a path that
exists*. The wheel it would fetch is hosted on github, which is blocked —
so a path is the only offline-safe form, and that is what
`deid/analyzer.py` passes.

**The NLP libraries quote your documents into their warnings.**
`spacy_huggingface_pipelines` emits `UserWarning: Skipping annotation ...
for doc '<the document>'` on any entity it cannot align — with the
patient's name in the message. Forwarding stage stderr to the job log
therefore re-leaks exactly what the pipeline removes. `stage_nlp.py`
filters that warning at source, and `pipeline.py` forwards stage stderr
only on failure (or under `DEID_LOG_STAGE_OUTPUT`). Anything new added to
either stage's logging needs the same scrutiny.

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

Which environment a module belongs to is not a convention, it is a
constraint: importing across the line is how the venv split silently
stops working.

```
OCR/
  requirements-ocr.txt   stage 1 deps           ─┐ never install
  requirements-nlp.txt   stage 2 deps           ─┘ into one venv

  deid/
    ── both envs (stdlib / pure python only) ──
    config.py        env-driven config, model pins, entity mapping
    model_store.py   resolves models/ by path; enforces offline
    spans.py         the stage-boundary types + JSON handoff
    results.py       per-document/page results, summary, exit codes
    mapping.py       char offsets <-> pixel boxes
    pdf_io.py        rasterise + true redaction (PyMuPDF, numpy)
    pipeline.py      the orchestrator itself — stdlib only

    ── .venv-ocr only (imports paddle) ──
    ocr_engine.py    PaddleOCR PP-OCRv6 wrapper -> OcrSpan list
    stage_ocr.py     PDF -> spans JSON

    ── .venv-nlp only (imports presidio/torch) ──
    analyzer.py      Presidio + transformers NLP engine
    recognizers.py   custom address/ZIP/MRN/age recognizers
    stage_nlp.py     spans JSON -> redacted PDF

  scripts/
    run_deid.py         job entrypoint (CLI or env vars), no deps
    stage_ocr.py        stage 1 entrypoint   (.venv-ocr)
    stage_nlp.py        stage 2 entrypoint   (.venv-nlp)
    stage_models.py     fill models/ from the network, --stage ocr|nlp
    check_models.py     load every staged model offline, --stage ocr|nlp
    verify_redaction.py re-OCR the output and hunt for leaks (.venv-ocr)
    make_sample_pdf.py  synthetic test document (.venv-ocr)

  models/              the weights, loaded by path, never downloaded
    README.md            layout + how to move it to Cloudera AI
```

The rule in one line: **nothing in the "both envs" group may import from
the two below it.** `pdf_io.py` and `mapping.py` in particular are shared,
which is why the dataclasses they pass around live in `spans.py` rather
than next to the code that produces them.
