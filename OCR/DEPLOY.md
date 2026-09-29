# OCR / de-identification deployment

OCR-specific steps. For the whole system (Hive, API, dashboard) see
`../DEPLOYMENT.md`.

Cloudera AI blocks GitHub and Hugging Face, so the models are downloaded on
another machine and copied over. The job loads them from disk with
downloads turned off.

## 1. Build the venvs (locally)

PaddleOCR and Presidio need different PyYAML versions, so they have separate
venvs. Never install both requirement files into one venv.

```bash
cd OCR
make venvs
make install
```

Or by hand:

```bash
python3.10 -m venv .venv-ocr
python3.10 -m venv .venv-nlp
.venv-ocr/bin/pip install -r requirements-ocr.txt
# CPU torch first, otherwise pip downloads the ~3GB CUDA build
.venv-nlp/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv-nlp/bin/pip install -r requirements-nlp.txt
```

## 2. Download the models (on a machine with internet)

```bash
make models          # or stage_models.py --stage ocr / --stage nlp
make check-models    # load them all with network off
```

About 15 minutes, ~570MB:

```
OCR/models/
├── paddle/PP-OCRv6_medium_det/
├── paddle/PP-OCRv6_medium_rec/
├── spacy/en_core_web_sm/
└── transformers/StanfordAIMI/stanford-deidentifier-base/
```

Folder names match the model names in `deid/config.py`.

## 3. Test locally

```bash
python3 scripts/run_deid.py --preflight
make run      # expect "files_ok": 1 and "entities_redacted": 20
make verify   # re-OCRs the output and checks no PII is left
```

`make verify` exits 0 if clean, 1 if something leaked, 2 if it
over-redacted (removed content that should stay).

## 4. Copy to Cloudera AI

The code goes through git. `OCR/models/` isn't in git, so:

```bash
tar czf ~/models.tar.gz models
```

and upload `models.tar.gz` to the project.

## 5. Set up on Cloudera AI

In a Session (Python 3.10, 2 vCPU / 4 GiB):

```bash
cd /home/cdsw/OCR
make venvs install
tar xzf ~/models.tar.gz
make check-models
python3 scripts/run_deid.py --preflight
```

In the preflight output, an empty path under `resolved` means that model is
missing. After a runtime change rebuild the venvs:
`make distclean && make venvs install` (models are kept).

## 6. Run it by hand

```bash
# one file
python3 scripts/run_deid.py --input <file> --output-dir /home/cdsw/out

# a folder
python3 scripts/run_deid.py --input /home/cdsw/storage/patient_files --recursive --output-dir /home/cdsw/out
```

`run_deid.py` only uses the standard library, so any python can run it. It
starts the two stages in their venvs. Put many files in one call, models
load once per call.

Output per file: `<name>_deid.<ext>`, `<name>_deid.txt` and
`<name>_deid.report.json`. Exit code 0 = all ok, 1 = all failed,
2 = some failed.

| Input | Stages | Removed |
|---|---|---|
| PDF | OCR + NER | text on the page, metadata |
| DICOM | OCR + NER | text burned into the image, identifying tags, private tags |
| DOC/DOCX | NER only | body, tables, headers/footers, properties (`.doc` comes back as `.docx`) |

Through the queue (what the Job runs):

```bash
cd /home/cdsw
python scripts/deid_worker.py --file-id <file-id>
python scripts/deid_worker.py              # all queued/pending files
python scripts/deid_worker.py --limit 20
DEID_RETRY_STALE_MINUTES=120 python scripts/deid_worker.py
```

Only run one at a time.

## 7. Job

See step 4 in `../DEPLOYMENT.md`. Job needs 2 vCPU / 8 GiB and these
variables:

```
FILE_STORAGE_DIR=/home/cdsw/storage/patient_files
DEID_OCR_PYTHON=/home/cdsw/OCR/.venv-ocr/bin/python
DEID_NLP_PYTHON=/home/cdsw/OCR/.venv-nlp/bin/python
HIVE_HOST / HIVE_PORT / HIVE_DB / HIVE_AUTH / HIVE_USER
```

Job runs don't get command-line arguments, use `DEID_FILE_ID`,
`DEID_BATCH_LIMIT` and `DEID_RETRY_STALE_MINUTES`.

Optional: a second scheduled job (`deidentify-sweep`, same script, no
`DEID_FILE_ID`, every 15 min, `DEID_RETRY_STALE_MINUTES=120`) to pick up
rows stuck in `processing` after a crash. `DEID_RETRY_STALE_MINUTES` counts
from upload time, so set it longer than a run takes.

To test the API call to the Job from a Session:

```bash
python -c "from app.cloudera import is_configured, start_deid_job_run; print(is_configured()); print(start_deid_job_run({'DEID_FILE_ID': '<file-id>'}))"
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Row stuck in `queued` | Job didn't start. Check `CML_DEID_JOB_ID` and the API log (`deid_job_dispatch_failed`) |
| Row stuck in `processing` | Run died. Run `deid_worker.py --file-id <id>` or use the sweep job |
| `model ... missing from the model store` | Models not copied, redo step 5 |
| Run hangs then fails | Trying to download, check `DEID_OFFLINE` and `DEID_MODELS_DIR` |
| `ocr stage interpreter not found` | Wrong `DEID_OCR_PYTHON`/`DEID_NLP_PYTHON`, or venvs need rebuilding |
| API uses a lot of memory | `DEID_BACKEND` is still `inline` |
| Job out of memory | Give it 8 GiB |
| Import error mentioning the other stage | Both requirement files installed in one venv |
