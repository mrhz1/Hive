# Deploying end to end on Cloudera AI

A complete walkthrough: project, Hive database, the two OCR virtualenvs,
the de-identification Job, the API Application, and the dashboard
Application. Follow it in order — each step assumes the previous one.

Four deployable units:

| Unit | Cloudera AI type | Entry point |
|---|---|---|
| Hive schema | Session (once) | `python scripts/init_db.py` |
| De-identification | **Job** | `python scripts/deid_worker.py` |
| API | Application | `uvicorn app.main:app --host 0.0.0.0 --port $CDSW_APP_PORT` |
| Dashboard | Application | `python scripts/serve_frontend.py` |

The dashboard is a React build, which Cloudera AI cannot serve on its
own — an Application runs a *process*, not a static directory. So a small
Flask server (`scripts/serve_frontend.py`) serves `frontend/dist`, with
SPA fallback and an optional API proxy. That is not a workaround; it is
the supported shape.

---

## 0. Before you start

You need:

- A Cloudera AI (CML) workspace and permission to create a project.
- A Hive/Impala Virtual Warehouse, or a Data Hub with HiveServer2, that
  the workspace can reach.
- A Python 3.10 runtime. Presidio supports 3.10–3.14, but impyla's
  `thrift-sasl` chain is fragile above 3.10 (see `requirements-dev.txt`),
  so **pick the 3.10 runtime** and keep everything on it.
- Egress to PyPI from the workspace, for `pip install`.
- A separate machine **with** egress to GitHub and Hugging Face, to stage
  the ~570MB of model weights. The workspace itself does not need it —
  and in this deployment does not have it — because the weights move as a
  file copy (step 3b). If PyPI is blocked too, jump to
  [Air-gapped](#air-gapped-workspaces).

Times to expect on a first build: dependencies ~10 min, staging the model
weights ~15 min on the machine with egress (the NER model alone is
~440MB), uploading them a few minutes, Hive schema seconds.

---

## 1. Create the project

**Project → New Project → Git**, pointing at this repository. A Git
project makes redeploys a `git pull` in a Session rather than a re-upload.

Then **Project Settings → Advanced → Environment Variables** and set the
values from `.env.example`. Project-level variables are inherited by
every Session, Job and Application, which is what you want — the API and
the Job must agree about `FILE_STORAGE_DIR` or the Job cannot read what
the API wrote.

| Variable | Value | Notes |
|---|---|---|
| `HIVE_HOST` | your HS2 host | from the Virtual Warehouse JDBC URL |
| `HIVE_PORT` | `10000` (binary) / `443` (HTTP) | |
| `HIVE_DB` | `hive_patients` | created in step 2 |
| `HIVE_AUTH` | `GSSAPI` | `NOSASL` only against a local docker Hive |
| `HIVE_USER` | your workload user | |
| `FILE_STORAGE_DIR` | `/home/cdsw/storage/patient_files` | **absolute** |
| `DEID_BACKEND` | `cml_job` | `inline` runs OCR inside the API process |
| `DEID_OCR_PYTHON` | `/home/cdsw/OCR/.venv-ocr/bin/python` | step 3 |
| `DEID_NLP_PYTHON` | `/home/cdsw/OCR/.venv-nlp/bin/python` | step 3 |
| `DEID_MODELS_DIR` | `/home/cdsw/OCR/models` | step 3b; only if not the default |
| `CML_DEID_JOB_ID` | *(fill in after step 4)* | chicken-and-egg; see below |

> **Do not set `VITE_DEV_USERNAME`.** It is a local stand-in for the
> authenticated principal. On Cloudera the platform sets `REMOTE-USER`
> itself; leaving this unset means the dashboard sends no identity header
> of its own and the switcher does not render.

---

## 2. Create the Hive database and tables

Start a **Session** (Python 3.10, 2 vCPU / 4 GiB is plenty) and run:

```bash
pip install -r requirements-dev.txt
python scripts/check_hive.py      # connectivity first, schema second
```

`check_hive.py` runs `SHOW DATABASES`. If it fails, stop here — nothing
downstream can work, and the error message names the cause (usually
Kerberos or a wrong port).

> `check_hive.py` passing is necessary but not sufficient: `SHOW
> DATABASES` returns a couple of rows, and the impyla/thrift bug that
> `requirements-dev.txt` documents only shows up on larger fetches. The
> first real page load is the honest test.

Then create the database and tables:

```sql
-- In a Hue/DAS/beeline session against the same warehouse:
CREATE DATABASE IF NOT EXISTS hive_patients;
```

```bash
python scripts/init_db.py         # applies sql/schema.sql + seed rows
```

### What the schema requires, and why it will bite you

Every table is `STORED AS ORC` with `TBLPROPERTIES ('transactional'='true')`.
That is not decoration — `UPDATE` and `DELETE` are rejected on anything
else, and this app updates rows constantly (`deid_status` alone changes
three times per document).

On Cloudera's Hive, managed ORC tables get `transactional='true'`
automatically via strict-managed-tables mode. Two things still go wrong:

- **`EXTERNAL` tables are never transactional**, whatever the file
  format. If your warehouse defaults to external tables, every write
  fails. `SHOW CREATE TABLE patients` and check.
- **Hive has no sequences.** Ids are application-generated UUID strings,
  so nothing breaks if you restore a table — but do not add an
  `AUTO_INCREMENT`-shaped column expecting it to work.

Verify ACID is genuinely on before going further:

```bash
python scripts/verify_acid.py     # does a real INSERT/UPDATE/DELETE round trip
```

---

## 3. Build the two OCR virtualenvs

**This is the step that the rest of the deployment depends on, and the
one that is not obvious.**

PaddleOCR and Presidio cannot be installed into the same environment:

```
paddleocr → paddlex           pins  PyYAML==6.0.2
presidio-analyzer ≥ 2.2.363   needs pyyaml>=6.0.3
```

pip has no solution, so the OCR pipeline runs as two processes with two
virtualenvs and a JSON handoff between them. `OCR/README.md` has the
full reasoning; what matters here is that you build **both**.

In the same Session:

```bash
cd /home/cdsw/OCR
make venvs      # .venv-ocr and .venv-nlp
make install    # both requirement sets; torch from the CPU index
```

The models do **not** come from here — see the next step.

---

## 3b. Move the model store across

> `OCR/DEPLOY.md` is the same ground as steps 3, 3b, 4 and 5 in one
> self-contained runbook, with every command spelled out and the
> Application → Job wiring code. Use it if de-identification is the part
> you are standing up.

**Cloudera AI blocks `github.com` and `huggingface.co`**, which is where
all four models normally come from. pip works; model weights do not
arrive over pip. So the weights are staged on a machine that has egress
and copied into the project as files. Nothing downloads at job time.

On your laptop (or any build agent with network), in a checkout with both
venvs built:

```bash
cd OCR
make models                    # ~570MB into OCR/models, a few minutes
tar czf models.tar.gz models   # ~500MB compressed
```

Upload `models.tar.gz` to the CML project, then in the Session:

```bash
cd /home/cdsw/OCR
tar xzf ~/models.tar.gz
make check-models   # loads every model with the network switched off
make preflight      # interpreters resolvable, models present?
```

`make check-models` is the check that matters here. It constructs each
model the way the pipeline will, so a truncated `pytorch_model.bin`
fails now rather than several minutes into the first real job.
`make preflight` only verifies the directories exist — enough to catch an
incomplete copy, not a corrupt one — and prints what the orchestrator
resolved:

```json
{
  "environment": {
    "orchestrator_python": "/usr/local/bin/python3",
    "ocr_python": "/home/cdsw/OCR/.venv-ocr/bin/python",
    "nlp_python": "/home/cdsw/OCR/.venv-nlp/bin/python",
    "models": {
      "models_dir": "/home/cdsw/OCR/models",
      "offline": true,
      "resolved": {
        "paddle:PP-OCRv6_medium_det": "/home/cdsw/OCR/models/paddle/PP-OCRv6_medium_det",
        "paddle:PP-OCRv6_medium_rec": "/home/cdsw/OCR/models/paddle/PP-OCRv6_medium_rec",
        "spacy:en_core_web_sm": "/home/cdsw/OCR/models/spacy/en_core_web_sm",
        "transformers:StanfordAIMI/stanford-deidentifier-base": "/home/cdsw/OCR/models/transformers/StanfordAIMI/stanford-deidentifier-base"
      }
    }
  },
  "problems": []
}
```

An empty string under `resolved` is a model that is not there. Leave
`DEID_OFFLINE` alone (it defaults to on) — it is what turns a missing
model into that message instead of a job hanging on a blocked host.
`OCR/models/README.md` has the layout, including the off-canonical
directory spellings the resolver tolerates.

Then prove the whole thing works before wiring any Cloudera object to it:

```bash
make run && make verify
```

`make verify` re-OCRs the redacted output the way an attacker would and
fails if any planted identifier survived. A green `make run` only proves
boxes were drawn; `make verify` proves the information is gone. Expect
`PASS: no PII survived; expected clinical content intact`.

### Why the venvs survive, and when they do not

`/home/cdsw` is project storage and persists across Sessions, Jobs and
Applications — so venvs built here are visible to the Job later. Two
caveats:

- Project storage is **NFS-backed**. Importing torch from it is slower
  than from a container layer. Acceptable for a Job that runs for
  minutes; if it is not, bake the venvs into a custom runtime image.
- A runtime upgrade can change the base Python. The venvs are tied to the
  interpreter that created them, so `make distclean && make venvs
  install models` after any runtime change.

---

## 4. Create the de-identification Job

**Jobs → New Job.**

| Field | Value |
|---|---|
| Name | `deidentify` |
| Script | `scripts/deid_worker.py` |
| Runtime | the same Python 3.10 runtime |
| Schedule | **Manual** (see below) |
| Resources | 2 vCPU / 8 GiB minimum |

8 GiB is not padding. Stage 2 loads a BERT-sized NER model, and while
splitting the pipeline means paddle is unloaded before torch is imported,
the NLP stage on its own still wants several GiB.

Create it, then copy the job id out of the URL
(`.../jobs/<job-id>`) into the project variable **`CML_DEID_JOB_ID`**.
That is the chicken-and-egg from step 1: the API needs the job's id, and
the job cannot exist until the project does.

### Manual schedule plus a sweep

The API starts a run per request (step 5), so the Job does not need a
schedule to function. Add a **second** Job on a schedule anyway —
same script, no `DEID_FILE_ID` — every 15 minutes or so:

```
Name:     deidentify-sweep
Script:   scripts/deid_worker.py
Schedule: every 15 minutes
Env:      DEID_RETRY_STALE_MINUTES=120
```

The sweep drains anything whose trigger never reached the control plane,
and re-claims rows stuck in `processing` because a run died mid-file.
Without it, a single dropped API call strands a document forever.

> **Run one at a time.** Hive has no reliable compare-and-set, so two
> overlapping runs can both claim the same row and process it twice. The
> status guard narrows the window; it does not close it. Do not schedule
> the sweep more often than a run takes to finish.

> `DEID_RETRY_STALE_MINUTES` measures age since *upload*, not since the
> row was claimed — `patient_application_files` has no `updated_at` column. Set it
> comfortably longer than a run takes, or a file uploaded yesterday gets
> re-claimed the moment it starts processing.

---

## 5. Create the API Application

**Applications → New Application.**

| Field | Value |
|---|---|
| Name | `patients-api` |
| Subdomain | `patients-api` |
| Script | `scripts/start_api.sh` (below) |
| Resources | 1 vCPU / 2 GiB |

Applications run a script, so create `scripts/start_api.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
pip install -r requirements-dev.txt
exec uvicorn app.main:app --host 0.0.0.0 --port "$CDSW_APP_PORT"
```

Note what the API does **not** need: neither OCR virtualenv. With
`DEID_BACKEND=cml_job` it only marks the row and POSTs to the CML API to
start a Job run, so the web process stays small.

Check the Application log after it starts. You want:

```
deid_backend backend=cml_job
```

and *not*:

```
deid_backend_misconfigured ... set CML_DEID_JOB_ID
```

That check runs at boot precisely so a missing job id surfaces now,
rather than as a row silently going to `failed` the first time somebody
clicks De-identify.

### How the API reaches the Job

`app/cloudera.py` POSTs to `/api/v2/projects/{id}/jobs/{id}/runs` with
`Authorization: Bearer $CDSW_APIV2_KEY`. Everything except
`CML_DEID_JOB_ID` is derived from the `CDSW_*` variables the platform
injects.

If `CDSW_APIV2_KEY` is not injected (API v2 not enabled for the project),
mint a key under **User Settings → API Keys** and set `CML_API_KEY`
explicitly. A *legacy* API key will not work — it must be a v2 key.

---

## 6. Build and serve the dashboard

The React app is compiled to static files, which an Application cannot
serve directly. Build it, then run the Flask server.

In a Session:

```bash
cd /home/cdsw/frontend
npm ci
VITE_API_BASE_URL=/api npm run build
```

Then **Applications → New Application**:

| Field | Value |
|---|---|
| Name | `patients-dashboard` |
| Subdomain | `patients` |
| Script | `scripts/start_dashboard.sh` |
| Resources | 1 vCPU / 2 GiB |

```bash
#!/usr/bin/env bash
set -euo pipefail
pip install -r requirements-dev.txt
export API_PROXY_TARGET="https://patients-api.${CDSW_DOMAIN}"
exec python scripts/serve_frontend.py
```

### Same origin, or CORS

Two ways to connect the dashboard to the API. **Prefer the first.**

**Proxy (recommended).** Build with `VITE_API_BASE_URL=/api` and set
`API_PROXY_TARGET` to the API Application's URL. The dashboard serves
both, so there is one origin: no CORS configuration, no `CORS_ORIGINS`
to keep in sync with a generated hostname, and the platform's auth
cookie is sent on every request because it never crosses an origin.

**Direct.** Build with `VITE_API_BASE_URL=https://patients-api.<domain>`
and set `CORS_ORIGINS=https://patients.<domain>` on the API. One more
moving part, and the failure mode is unhelpful — a CORS rejection does
not look like a CORS error in the app, it looks like the API is down.

Either way, `VITE_API_BASE_URL` is baked in **at build time**. Changing
it means rebuilding, not restarting.

### SPA routing

`serve_frontend.py` returns `index.html` for any path that is not a real
file. Without that, `/patients/abc/files` 404s on reload — the router is
client-side and the server has no such file. If deep links break, that
fallback is what to check.

---

## 7. Verify end to end

In order, because each step depends on the last:

1. **Dashboard loads.** `https://patients.<domain>` renders the patient
   list. If it renders but is empty and the console shows failed
   requests, the API connection is wrong (step 6), not the data.
2. **API reachable.** `curl https://patients-api.<domain>/health` →
   `{"status":"ok"}`. This deliberately does not touch Hive, so it
   answers "is the process up" and nothing else.
3. **Hive path works.** Create a patient in the UI. This exercises
   connection, INSERT and the ACID properties in one action.
4. **Upload a PDF** to that patient.
5. **Click De-identify.** The row goes to `queued`, a run appears under
   **Jobs → deidentify → History**, and the row reaches `done` a minute
   or two later. The dashboard shows `redacted` and the redacted copy is
   viewable.
6. **Verify the redaction.** In a Session:
   ```bash
   cd /home/cdsw/OCR
   .venv-ocr/bin/python scripts/verify_redaction.py \
       /home/cdsw/storage/patient_files/<application-id>/deidentified/<file>_deid.pdf \
       --expect-absent "the patient's name"
   ```
   A report saying "20 entities redacted" proves 20 boxes were drawn. This
   proves the information is gone.

### Where each status comes from

```
pending     uploaded, nobody has asked for it
queued      the API asked Cloudera to start a run   (cml_job only)
processing  a worker claimed the row
done        a redacted copy exists
failed      look at the Job run's log
```

A row stuck in `queued` means the Job run never started — check
`CML_DEID_JOB_ID` and the API Application's log. A row stuck in
`processing` means a run died mid-file; the sweep re-claims it.

A row that goes straight to `failed` with `model ... missing from the
model store` in the Job log means step 3b did not land — re-run
`make check-models` in a Session. A run that instead *hangs* for minutes
before failing means something is still trying to download: check that
`DEID_OFFLINE` has not been set to `0` anywhere.

---

## Three things that will bite you

**1. Shared storage.** The API writes uploads and the Job reads them, so
they must see the same filesystem. `/home/cdsw` works within one project
and is NFS-backed. At volume, move to S3/ADLS and store the object key in
`file_path`. Decide before you have production data — migrating stored
paths afterwards is painful.

**2. The weights are not downloadable from here.** github and
huggingface are blocked, so `OCR/models/` has to arrive as a file copy
(step 3b) and nothing may fetch at job time. `DEID_OFFLINE` defaults to
on to enforce that; a missing model then fails preflight with the path it
looked in, instead of the job hanging on a blocked host until it times
out. For a fleet, bake `models/` into a custom runtime rather than
copying it per project.

**3. The handoff file is PHI.** Between the two stages, the OCR'd text
sits in a JSON file. It is created 0600 in a 0700 temp directory and
deleted in a `finally`. Do not set `DEID_KEEP_WORK_DIR` in production,
and do not point `DEID_WORK_DIR` at shared storage. Relatedly,
`DEID_LOG_STAGE_OUTPUT` forwards stage stderr to the job log — and the
NLP libraries quote document text into their warnings.

---

## Air-gapped workspaces

Step 3b already assumes the models cannot be downloaded on the target.
A fully air-gapped workspace adds `pip install` to that list. Build a
custom runtime image instead, on a machine that has egress:

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

# `make models` on the build host, so models/ is already populated in the
# build context and this only copies. Staging inside the image would need
# egress at build time, which is the thing being avoided.
COPY OCR/models/ /opt/deid/OCR/models/

# Fail the build, not the first job, if a weight did not make it in.
RUN /opt/deid/.venv-ocr/bin/python /opt/deid/OCR/scripts/check_models.py --stage ocr && \
    /opt/deid/.venv-nlp/bin/python /opt/deid/OCR/scripts/check_models.py --stage nlp
```

Then set `DEID_OCR_PYTHON=/opt/deid/.venv-ocr/bin/python`,
`DEID_NLP_PYTHON=/opt/deid/.venv-nlp/bin/python` and
`DEID_MODELS_DIR=/opt/deid/OCR/models`, and skip steps 3 and 3b. The two
`RUN` lines for the venvs must stay separate — a single `pip install`
naming both requirement files is the exact thing that cannot resolve.

Note `OCR/models/` is gitignored (~570MB), so a CI build context needs it
staged or fetched from an artifact store first — a clone alone will not
have it.

---

## Configuration reference

| Variable | Default | Notes |
|---|---|---|
| `HIVE_HOST` / `HIVE_PORT` / `HIVE_DB` / `HIVE_AUTH` / `HIVE_USER` | — | `HIVE_AUTH=GSSAPI` in production |
| `CORS_ORIGINS` | localhost dev ports | Unneeded when proxying |
| `FILE_STORAGE_DIR` | `storage/patient_files` | Visible to **both** API and Job |
| `DEID_BACKEND` | `inline` | `cml_job` on Cloudera AI |
| `DEID_OCR_PYTHON` | `OCR/.venv-ocr/bin/python` | Stage 1 (paddle) |
| `DEID_NLP_PYTHON` | `OCR/.venv-nlp/bin/python` | Stage 2 (presidio) |
| `DEID_PYTHON` | this interpreter | Runs the stdlib-only orchestrator |
| `DEID_MODELS_DIR` | `OCR/models` | The local model store; read-only is fine |
| `DEID_OFFLINE` | `true` | Load models by path only, never download |
| `DEID_TIMEOUT_SECONDS` | `1800` | Per file |
| `DEID_BATCH_LIMIT` | `0` (no limit) | Cap files per job run |
| `DEID_RETRY_STALE_MINUTES` | `0` (off) | Re-claim rows stuck in `processing` |
| `DEID_FILE_ID` | — | Set per run by the API; scopes a run to one file |
| `DEID_WORK_DIR` | 0700 temp dir | Holds the PHI-bearing handoff |
| `DEID_KEEP_WORK_DIR` | `false` | Debugging only |
| `CML_DEID_JOB_ID` | — | Required for `cml_job` |
| `CML_PROJECT_ID` / `CML_API_KEY` / `CML_API_URL` | from `CDSW_*` | Override only if not injected |
| `FRONTEND_DIST` | `frontend/dist` | Dashboard Application |
| `API_PROXY_TARGET` | — | Set to serve dashboard + API on one origin |
| `VITE_API_BASE_URL` | — | **Build-time**; `/api` when proxying |
| `VITE_DEV_USERNAME` | — | **Leave unset in production** |

---

## Identity in production

There is no login. `app/security.py::_current_username` reads the
`REMOTE-USER` header — the username the platform already authenticated.
Locally you set it by hand; on Cloudera the platform sets it ahead of the
app. The proxy deployment (step 6) is what makes that work: the dashboard
and API share an origin, so the platform's auth headers reach the API
unchanged.

## When to graduate the Job to an Application

If a user ever *waits* for a result, or the queue grows faster than one
batch drains it. Run a small always-on worker with models loaded once and
keep the Job as a sweeper. The `deid_status` contract does not change —
only who drains it.
