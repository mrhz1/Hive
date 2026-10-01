# Deploying on Cloudera AI

Steps to deploy everything on Cloudera AI (CML). Do them in order.

| Part | CML type | Entry point |
|---|---|---|
| Hive schema | Session (once) | `python scripts/init_db.py` |
| De-identification | Job | `scripts/deid_worker.py` |
| Intake | Job | `scripts/intake_run.py` |
| API | Application | `scripts/start_api.sh` |
| Dashboard | Application | `scripts/start_dashboard.sh` |

The dashboard is a React build, so it's served by a small Flask app
(`scripts/serve_frontend.py`) that also proxies `/api` to the API.

## 0. Requirements

- A CML workspace and permission to create a project
- A Hive Virtual Warehouse (or Data Hub with HiveServer2)
- Python 3.10 runtime (impyla/thrift-sasl has issues on newer versions)
- PyPI access from the workspace
- Another machine with internet access to download the models (~570MB),
  since CML blocks GitHub and Hugging Face

## 1. Create the project

Create a project from Git (Project → New Project → Git). Then set the
environment variables in Project Settings → Advanced → Environment
Variables (see `.env.example` for the full list):

| Variable | Value |
|---|---|
| `HIVE_HOST` | HiveServer2 host (from the JDBC URL) |
| `HIVE_PORT` | `10000` (binary) or `443` (HTTP) |
| `HIVE_DB` | `hive_patients` |
| `HIVE_AUTH` | `GSSAPI` |
| `HIVE_USER` | your workload user |
| `FILE_STORAGE_DIR` | `/home/cdsw/storage/patient_files` (absolute) |
| `INTAKE_DIR` | incoming folder on the shared volume |
| `DATA_DIR` | pending data folder (original, de-identified, failed...) until submitted, same disk as `INTAKE_DIR`, e.g. `/home/cdsw/Backend/storage/pending_data` |
| `SUBMITTED_DATA_DIR` | where submitting moves an application's files, same layout, e.g. `/home/cdsw/Backend/storage/submitted_data` |
| `DEID_BACKEND` | `cml_job` |
| `DEID_OCR_PYTHON` | `/home/cdsw/OCR/.venv-ocr/bin/python` |
| `DEID_NLP_PYTHON` | `/home/cdsw/OCR/.venv-nlp/bin/python` |
| `CML_DEID_JOB_ID` | set after step 4 |
| `CML_INTAKE_JOB_ID` | set after step 4b |

Don't set `VITE_DEV_USERNAME` in production. The platform sends the
`REMOTE-USER` header.

## 2. Hive database and tables

Start a Session (Python 3.10) and run:

```bash
pip install -r requirements-dev.txt
python scripts/check_hive.py
```

Create the database (in Hue or beeline) and the tables:

```sql
CREATE DATABASE IF NOT EXISTS hive_patients;
```

```bash
python scripts/init_db.py      # creates tables from sql/schema.sql + admin/viewer logins
python scripts/verify_acid.py  # checks INSERT/UPDATE/DELETE work
```

All tables must be managed ORC tables with `transactional=true`, otherwise
UPDATE and DELETE fail. External tables won't work.

## 3. OCR virtualenvs

PaddleOCR and Presidio need different PyYAML versions, so there are two
venvs (see `OCR/README.md`):

```bash
cd /home/cdsw/OCR
make venvs
make install
```

If the runtime version changes, rebuild them: `make distclean && make venvs install`.

## 3b. Copy the models

On a machine with internet:

```bash
cd OCR
make models
tar czf models.tar.gz models
```

Upload `models.tar.gz` to the project, then in a Session:

```bash
cd /home/cdsw/OCR
tar xzf ~/models.tar.gz
make check-models   # loads every model offline
make preflight      # checks interpreters and model folders
make run && make verify
```

`make verify` re-OCRs the redacted sample and fails if any test PII is
still there. Keep `DEID_OFFLINE` on (default) so a missing model fails
right away instead of trying to download.

## 4. De-identification Job

Jobs → New Job:

| Field | Value |
|---|---|
| Name | `deidentify` |
| Script | `scripts/deid_worker.py` |
| Schedule | Manual |
| Resources | 2 vCPU / 8 GiB (the NER model needs the memory) |

Copy the job id from the URL (`.../jobs/<job-id>`) into `CML_DEID_JOB_ID`.

Notes:

- Job runs don't receive command-line arguments, use env variables
  (`DEID_FILE_ID`, `DEID_BATCH_LIMIT`, `DEID_RETRY_STALE_MINUTES`).
- If the job can't find the repo, set `HIVE_REPO_ROOT=/home/cdsw` as a
  real environment variable (not in `.env.local`).
- Keep it on Manual and only create one Job. The API starts one run at a
  time (`app/deid_queue.py`), because CML rejects a second run of the same
  Job while one is active.
- Run the API with a single replica.

Optional tuning:

| Variable | Default | |
|---|---|---|
| `DEID_DISPATCH_POLL_SECONDS` | 10 | how often to check the running job |
| `DEID_DISPATCH_IDLE_SECONDS` | 60 | how often to check for queued rows when idle |
| `DEID_DISPATCH_MAX_RUN_SECONDS` | 10800 | max wait for one run |
| `DEID_DISPATCH_BACKOFF_SECONDS` | 60 | wait after an error |

## 4b. Intake Job

Jobs → New Job:

| Field | Value |
|---|---|
| Name | `intake` |
| Script | `scripts/intake_run.py` |
| Schedule | Manual (started by the Start button on the Intake page) |
| Resources | as many vCPU / GiB as the workers need (8 GiB per worker) |
| Environment | `INTAKE_DIR`, `DATA_DIR`, `SUBMITTED_DATA_DIR`, `DEID_WORKERS`, `DEID_WORKER_CPU_THREADS`, plus the Hive variables |

Copy the job id from the URL into `CML_INTAKE_JOB_ID` on the API
Application. See the Intake section in `README-local.md` for how it works
and how to size the workers.

## 5. API Application

Applications → New Application:

| Field | Value |
|---|---|
| Name / subdomain | `patients-api` |
| Script | `scripts/start_api.sh` |
| Resources | 1 vCPU / 2 GiB |

The API doesn't need the OCR venvs when `DEID_BACKEND=cml_job`.

After it starts, the log should show `deid_backend backend=cml_job`. If it
shows `deid_backend_misconfigured`, `CML_DEID_JOB_ID` is missing.

If `CDSW_APIV2_KEY` isn't injected, create a v2 API key (User Settings →
API Keys) and set `CML_API_KEY`.

### Permissions on an existing database

`init_db.py` only seeds permissions on a new database. On an existing one:

```bash
python scripts/grant_permissions.py --list
python scripts/grant_permissions.py --role admin --all-missing
python scripts/grant_permissions.py --role viewer --grant files:read,files:view_original,files:view_deidentified,files:metadata,files:deid_metadata
```

Users need to sign out and back in after that.

| Permission | Allows |
|---|---|
| `files:read` | browse de-identified files |
| `files:download` | every Download button, and exporting a file's metadata |
| `files:upload` | upload or replace a redacted file |
| `files:delete` | delete a document from an application, or a redacted copy |
| `files:view_original` | view the identified original |
| `files:view_deidentified` | view the de-identified copy |
| `files:metadata` | show the original's metadata |
| `files:deid_metadata` | show the de-identified copy's metadata |
| `files:reject` | reject a document in step 2 of an application |

### New columns on an existing database

`init_db.py` drops and recreates tables, so don't run it on a live
database. Use:

```bash
python scripts/migrate_columns.py --list
python scripts/migrate_columns.py --apply
```

New tables (`access_logs`) have to be created by hand from
`sql/schema.sql`. After that, remove UPDATE and DELETE grants on
`audit_logs` and `access_logs` for the app user.

The intake no longer uses Hive tables. On a database that has the old
ones, drop them:

```sql
DROP TABLE IF EXISTS intake_files;
DROP TABLE IF EXISTS intake_batches;
```

New columns must go at the end of the table and at the end of the
`COLUMNS` tuple in `app/crud/*`, because Hive INSERT is positional.

### Troubleshooting

**"409 out of quota: CPU request limit reached"**: no CPU left for the Job.
Stop idle Sessions, and shrink the Applications (1 vCPU / 2 GiB is enough).
The Job can go down to 1 vCPU but needs 8 GiB; set `OCR_CPU_THREADS` to
the vCPU count. The file stays `queued` and runs later.

**"SSL certificate verify failed"**: the workspace uses an internal CA.
Find the CA bundle:

```bash
python -c "import ssl; print(ssl.get_default_verify_paths())"
ls -l /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt
```

and set `CML_CA_BUNDLE` to it. Don't use `CML_VERIFY_TLS=false`, the
request carries the API key.

## 6. Dashboard Application

Build the frontend in a Session:

```bash
cd /home/cdsw/frontend
npm ci
VITE_API_BASE_URL=/api npm run build
```

Applications → New Application:

| Field | Value |
|---|---|
| Name / subdomain | `patients` |
| Script | `scripts/start_dashboard.sh` |
| Resources | 1 vCPU / 2 GiB |

`start_dashboard.sh` sets `API_PROXY_TARGET` to the API application, so
the dashboard and API are on the same origin and CORS isn't needed.

Without the proxy you'd build with the full API URL and set `CORS_ORIGINS`
on the API. `VITE_API_BASE_URL` is used at build time, so changing it needs
a rebuild.

## 7. Check it works

1. Open the dashboard, the patient list should load.
2. `curl https://patients-api.<domain>/health` returns `{"status":"ok"}`.
3. Create a patient.
4. Upload a PDF.
5. Click De-identify. The row goes `queued` → `processing` → `done`.
6. Check the redaction:
   ```bash
   cd /home/cdsw/OCR
   .venv-ocr/bin/python scripts/verify_redaction.py <redacted file> --expect-absent "patient name"
   ```

Statuses:

```
pending     uploaded
queued      waiting for a Job run (cml_job only)
processing  being redacted
done        redacted copy exists
failed      check the Job run log
```

- Stuck in `queued`: the Job never started, check `CML_DEID_JOB_ID` and the
  API log.
- `model ... missing from the model store`: redo step 3b.
- Hangs for minutes then fails: something is trying to download, check
  `DEID_OFFLINE`.

## Things to keep in mind

- **Shared storage:** the API and the Jobs must see the same files
  (`/home/cdsw` works within one project).
- **PHI in temp files:** the OCR text is written to a temp folder between
  the two stages (0600, deleted afterwards). Don't set `DEID_KEEP_WORK_DIR`
  or `DEID_LOG_STAGE_OUTPUT` in production.
- **Login:** there is none in the app. The username comes from the
  `REMOTE-USER` header set by the platform.

## Air-gapped workspace

If PyPI is blocked too, build a custom runtime image on a machine with
internet:

```dockerfile
FROM <your-cml-python3.10-runtime>

COPY OCR/requirements-ocr.txt OCR/requirements-nlp.txt /tmp/
RUN python3.10 -m venv /opt/deid/.venv-ocr && \
    /opt/deid/.venv-ocr/bin/pip install -r /tmp/requirements-ocr.txt
RUN python3.10 -m venv /opt/deid/.venv-nlp && \
    /opt/deid/.venv-nlp/bin/pip install torch \
        --index-url https://download.pytorch.org/whl/cpu && \
    /opt/deid/.venv-nlp/bin/pip install -r /tmp/requirements-nlp.txt

COPY OCR/ /opt/deid/OCR/
COPY OCR/models/ /opt/deid/OCR/models/

RUN /opt/deid/.venv-ocr/bin/python /opt/deid/OCR/scripts/check_models.py --stage ocr && \
    /opt/deid/.venv-nlp/bin/python /opt/deid/OCR/scripts/check_models.py --stage nlp
```

Then set `DEID_OCR_PYTHON`, `DEID_NLP_PYTHON` and
`DEID_MODELS_DIR=/opt/deid/OCR/models` and skip steps 3 and 3b.
`OCR/models/` is not in git, so run `make models` before building.

## Main settings

| Variable | Default | |
|---|---|---|
| `FILE_STORAGE_DIR` | `storage/patient_files` | shared by API and Job |
| `DEID_BACKEND` | `inline` | `cml_job` on Cloudera |
| `DEID_OCR_PYTHON` / `DEID_NLP_PYTHON` | `OCR/.venv-*/bin/python` | |
| `DEID_MODELS_DIR` | `OCR/models` | |
| `DEID_OFFLINE` | `true` | never download models |
| `DEID_TIMEOUT_SECONDS` | `5400` | per file (~175 pages) |
| `DEID_BATCH_LIMIT` | `0` | max files per job run |
| `DEID_RETRY_STALE_MINUTES` | `0` | retry rows stuck in `processing` |
| `DEID_WORK_DIR` | temp dir | |
| `CML_DEID_JOB_ID` | | required for `cml_job` |
| `CML_CA_BUNDLE` | | CA bundle for internal CA |
| `API_PROXY_TARGET` | | serve API through the dashboard |
| `VITE_API_BASE_URL` | | build time, `/api` with the proxy |
