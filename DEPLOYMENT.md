# Deploying to Cloudera AI

Three deployable units:

| Unit | Cloudera type | Entry point |
|---|---|---|
| Dashboard | Application | `npm run build` → serve `frontend/dist` |
| API | Application | `uvicorn app.main:app --host 0.0.0.0 --port $CDSW_APP_PORT` |
| De-identification | **Job** | `python scripts/deid_worker.py` |

## Why the OCR is a Job, not a Model or Application

The pipeline takes ~30s per page (~105s for a one-page scan including
model load), so it does not fit a synchronous Model endpoint. It could be
an always-on Application, but that means owning the queue and concurrency
yourself for no benefit at low volume.

A Job fits because `patient_files` already describes an async workflow:

```
pending -> processing -> done | failed
```

The API marks `pending`; something drains it. Batching matters: model
load is paid once per **run**, not once per file.

## The one thing that makes the move cheap

`app/deid.py::run_deidentification(file_id)` is the only code that
de-identifies a file. Both triggers call it:

- **now** — `POST /files/{id}/deidentify` queues it in a FastAPI
  `BackgroundTask`
- **later** — `scripts/deid_worker.py` drains the pending queue

Switching therefore changes *scheduling*, not behaviour. To move the work
off the API process entirely, change the endpoint to only mark `pending`
(drop the `background.add_task` line) and schedule the worker.

The OCR stack is invoked as a **subprocess**, not imported, so ~3GB of ML
dependencies stay out of the API process — and that is the same shape a
Job uses. Only `DEID_PYTHON` differs.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `HIVE_HOST` / `HIVE_PORT` / `HIVE_DB` / `HIVE_AUTH` / `HIVE_USER` | — | `HIVE_AUTH=GSSAPI` in production |
| `CORS_ORIGINS` | localhost dev ports | Set to the deployed dashboard origin |
| `FILE_STORAGE_DIR` | `storage/patient_files` | Must be visible to **both** the API and the job |
| `DEID_PYTHON` | `OCR/.venv/bin/python` | Interpreter with the OCR stack |
| `DEID_SCRIPT` | `OCR/scripts/run_deid.py` | |
| `DEID_TIMEOUT_SECONDS` | `1800` | Per file |
| `DEID_BATCH_LIMIT` | `0` (no limit) | Cap files per job run |
| `DEID_RETRY_STALE_MINUTES` | `0` (off) | Re-claim rows stuck in `processing` |
| `VITE_API_BASE_URL` | — | Dashboard → API |
| `VITE_DEV_USER_ID` | — | **Leave unset in production**; the platform supplies identity |

## Three things that will bite you

**1. Shared storage.** The API writes uploads and the job reads them, so
they must see the same filesystem. Project storage works within one
Cloudera project but is NFS-backed. At volume, move to S3/ADLS and store
the object key in `file_path`. Decide before you have production data —
migrating stored paths afterwards is painful.

**2. Bake the model weights in.** The NER model alone took ~14 minutes to
download. If that happens at job startup, runs will time out. Build a
custom runtime image with the dependencies and weights baked in
(`OCR/scripts/download_models.py` fetches them), rather than
`pip install`ing ~3GB at job start.

**3. Run one worker at a time.** Hive has no reliable compare-and-set, so
two overlapping runs can both claim the same `pending` row and process it
twice. The status guard narrows the window; it does not close it. Do not
schedule overlapping runs.

## Identity in production

There is no login. `app/security.py::_current_user_id` reads an
`X-User-Id` header, which is a **local stand-in**. On Cloudera the
authenticated principal arrives from the platform — change that one
function and nothing else. Leave `VITE_DEV_USER_ID` unset so the
dashboard sends no header and the switcher does not render.

## When to graduate from Job to Application

If a user ever *waits* for a result, or the queue grows faster than one
batch drains it. Run a small always-on worker with models loaded once and
keep the Job as a sweeper. The `deid_status` contract does not change —
only who drains it.
