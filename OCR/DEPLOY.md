# De-identification: full deployment runbook

Every command, in order, from an empty checkout to a de-identification
Job that the API Application triggers on a button click.

This is the OCR-side runbook. `../DEPLOYMENT.md` covers the whole system
(Hive schema, dashboard, Applications); this file is what you follow when
the de-identification pipeline is the thing you are standing up, and it
is self-contained for that purpose.

**The one constraint that shapes everything below:** Cloudera AI blocks
`github.com` and `huggingface.co`, which is where all four models come
from. pip works; model weights do not arrive over pip. So the weights are
staged on a machine that *has* egress and moved across as files, and the
job loads them by path with downloading switched off.

Contents:

1. [Local: build the venvs](#1-local-build-the-two-virtualenvs)
2. [Local: stage the models](#2-local-stage-the-models)
3. [Local: prove it works](#3-local-prove-the-pipeline-works)
4. [Move it to Cloudera AI](#4-move-it-to-cloudera-ai)
5. [Cloudera: build the venvs](#5-cloudera-build-the-venvs)
6. [Cloudera: unpack and check the models](#6-cloudera-unpack-and-check-the-models)
7. [Run it once by hand](#7-run-the-whole-thing-once-as-a-single-job)
8. [Create the Job](#8-create-the-job)
9. [Wire the Application to the Job](#9-wire-the-application-to-the-job)
10. [Verify end to end](#10-verify-end-to-end)
11. [Troubleshooting](#troubleshooting)

---

## 1. Local: build the two virtualenvs

**PaddleOCR and Presidio cannot be installed into the same environment.**
The conflict is exact:

```
paddleocr → paddlex           pins  PyYAML==6.0.2
presidio-analyzer ≥ 2.2.363   needs pyyaml>=6.0.3
```

pip has no solution, so the pipeline runs as two processes with two
virtualenvs and a JSON handoff. Everything below builds **both**.

```bash
cd OCR

# Python 3.10 specifically: impyla's thrift-sasl chain (used by the API
# side of this repo) is fragile above 3.10, and keeping one interpreter
# across the whole project avoids a second class of problem.
python3.10 -m venv .venv-ocr
python3.10 -m venv .venv-nlp
.venv-ocr/bin/pip install --upgrade pip
.venv-nlp/bin/pip install --upgrade pip

# Stage 1: paddle.
.venv-ocr/bin/pip install --retries 10 --timeout 120 -r requirements-ocr.txt

# Stage 2: torch FIRST, from the CPU index. Skip that and pip pulls the
# ~3GB CUDA build (nvidia-cublas, nvidia-cudnn, …) for a CPU job.
.venv-nlp/bin/pip install --retries 10 --timeout 120 torch \
    --index-url https://download.pytorch.org/whl/cpu
.venv-nlp/bin/pip install --retries 10 --timeout 120 -r requirements-nlp.txt
```

Or the same thing via make:

```bash
cd OCR
make venvs
make install
```

> **Never** `pip install -r requirements-ocr.txt -r requirements-nlp.txt`
> into one environment. That is the thing that does not work.

---

## 2. Local: stage the models

Run this **on a machine with network access**. It downloads every weight
and lays it out under `OCR/models/` in the shape `deid/model_store.py`
expects.

```bash
cd OCR

.venv-ocr/bin/python scripts/stage_models.py --stage ocr    # ~133MB
.venv-nlp/bin/python scripts/stage_models.py --stage nlp    # ~434MB

# or both:
make models
```

Two runs, not one: each virtualenv can only download what it can import.
Expect ~15 minutes — the NER model is a ~440MB `pytorch_model.bin` with
no safetensors in the repo. Re-running skips whatever is already staged;
`--force` re-downloads.

Result:

```
OCR/models/
├── paddle/PP-OCRv6_medium_det/                          133MB (both)
├── paddle/PP-OCRv6_medium_rec/
├── spacy/en_core_web_sm/                                 15MB
└── transformers/StanfordAIMI/stanford-deidentifier-base/ 419MB
```

Directory names are the model identifiers **verbatim** — the same strings
`deid/config.py` pins. Swapping a model means dropping in a folder with
the matching name, not editing code.

Now confirm they load with the network switched off:

```bash
make check-models
```

```
INFO    model store: /path/to/OCR/models (offline=True)
INFO    paddle: det=PP-OCRv6_medium_det rec=PP-OCRv6_medium_rec
INFO      OK
INFO    spacy: en_core_web_sm
INFO      OK
INFO    transformers: StanfordAIMI/stanford-deidentifier-base
INFO      OK -- labels: DATE, HCW, HOSPITAL, ID, O, PATIENT, PHONE, VENDOR
```

---

## 3. Local: prove the pipeline works

Before moving anything, run it end to end against the synthetic document:

```bash
cd OCR

# Interpreters resolvable, models present?
python3 scripts/run_deid.py --preflight

# Build the synthetic scanned discharge summary and de-identify it.
make run

# The check that actually matters.
make verify
```

`make run` prints a JSON summary; expect `"files_ok": 1` and
`"entities_redacted": 20`.

`make verify` re-OCRs the output the way an attacker would. A report
saying "20 entities redacted" only proves 20 boxes were drawn; this
proves the information is gone:

```
residual text-layer chars: 0
  [removed] Jonathan Michael Reyes
  [removed] 543-22-9087
  … 9 more …
  [kept   ] chest pain
  [kept   ] troponins
  [kept   ] ejection fraction
PASS: no PII survived; expected clinical content intact
```

It also checks that content which *should* survive did — a redactor that
blacks out the whole page would otherwise pass a leak test while being
useless. Exit `0` clean, `1` leak, `2` over-redacted.

---

## 4. Move it to Cloudera AI

The code goes by git. The weights do not — ~570MB is not a thing to put
in every clone, and `OCR/models/` is gitignored for that reason.

```bash
# On the machine with egress:
cd OCR
tar czf ~/models.tar.gz models        # ~500MB compressed
```

Upload `models.tar.gz` into the CML project (**Files → Upload**, or
`scp`/`cdswctl` if the workspace allows it). Put the code there as a Git
project: **Project → New Project → Git**, pointing at this repository —
a Git project makes redeploys a `git pull` in a Session.

---

## 5. Cloudera: build the venvs

Start a **Session** (Python 3.10 runtime, 2 vCPU / 4 GiB) and run exactly
what you ran locally:

```bash
cd /home/cdsw/OCR
make venvs
make install
```

> The venvs hard-code the absolute path of the interpreter that created
> them. After any runtime change, `make distclean && make venvs install`
> — a venv pointing at a python that no longer exists fails in a way that
> looks like a missing dependency.

---

## 6. Cloudera: unpack and check the models

```bash
cd /home/cdsw/OCR
tar xzf ~/models.tar.gz               # creates ./models/

make check-models                     # loads every model, network off
python3 scripts/run_deid.py --preflight
```

`make check-models` is the check that matters here. It constructs each
model the way the pipeline will, so a truncated `pytorch_model.bin` fails
now rather than several minutes into the first real job.

`--preflight` only verifies the directories exist — enough to catch an
incomplete copy, not a corrupt one — and prints what resolved:

```json
{
  "environment": {
    "orchestrator_python": "/usr/local/bin/python3",
    "ocr_root": "/home/cdsw/OCR",
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

An **empty string** under `resolved` is a model that is not there.

Leave `DEID_OFFLINE` alone — it defaults to on, and it is what turns a
missing model into that message instead of a job hanging on a blocked
host until it times out.

---

## 7. Run the whole thing once, as a single job

Still in the Session. This is the single-command test the Job will later
run on your behalf — do it by hand first, so a failure here is a Session
you can debug rather than a Job log you have to read backwards.

### 7a. One PDF, straight through the pipeline

```bash
cd /home/cdsw/OCR

python3 scripts/run_deid.py \
    --input /home/cdsw/storage/patient_files/<application-id>/<file>.pdf \
    --output-dir /home/cdsw/out
```

Or the env-var form, which is how a Cloudera Job usually receives
arguments:

```bash
DEID_INPUT=/home/cdsw/storage/patient_files/<application-id>/<file>.pdf \
DEID_OUTPUT_DIR=/home/cdsw/out \
python3 scripts/run_deid.py
```

Run it with **any** python — `run_deid.py` is the orchestrator and
imports nothing outside the standard library. It coordinates the two
stage subprocesses, and only those need dependencies. That is why the
Cloudera runtime's stock python can run it with nothing installed.

A whole directory, recursively:

```bash
python3 scripts/run_deid.py --input /home/cdsw/storage/patient_files \
    --recursive --output-dir /home/cdsw/out
```

Batch as many PDFs into one invocation as you can. Model load dominates
the cost of a small run and each stage pays it exactly once per
invocation, so 50 files in one call is far cheaper than 50 calls.

You get `doc_deid.pdf`, `doc_deid.txt` (de-identified text) and
`doc_deid.report.json` per input, a JSON summary on stdout, and exit
`0` all OK / `1` everything failed / `2` partial.

### 7b. The same work, driven by the queue

This is what the Job actually runs. It reads `patient_application_files` from Hive,
de-identifies what is waiting, and writes the result back onto the row:

```bash
cd /home/cdsw

# Exactly one file, by id -- what a triggered run does.
python scripts/deid_worker.py --file-id <file-id>
DEID_FILE_ID=<file-id> python scripts/deid_worker.py     # env-var form

# Drain the queue: 'queued' first (someone asked), then 'pending'
# (uploaded, never processed).
python scripts/deid_worker.py

# Cap one run, and re-claim rows stuck in 'processing'.
python scripts/deid_worker.py --limit 20
DEID_RETRY_STALE_MINUTES=120 python scripts/deid_worker.py
```

`deid_worker.py` calls `app.deid.run_deidentification` — the exact
function the API calls inline — so moving between the two changes
scheduling, not behaviour.

> **Run one instance at a time.** Hive has no reliable compare-and-set,
> so two overlapping runs can both claim the same row. The status guard
> narrows the window; it does not close it.

Watch the row move:

```bash
python - <<'PY'
from app.db import hive_cursor
from app.crud import patient_application_files as crud
with hive_cursor() as c:
    for f in crud.list_files(c):
        print(f.id, f.deid_status, f.deidentified_file_name)
PY
```

---

## 8. Create the Job

**Jobs → New Job.**

| Field | Value |
|---|---|
| Name | `deidentify` |
| Script | `scripts/deid_worker.py` |
| Runtime | the same Python 3.10 runtime as the Session |
| Schedule | **Manual** |
| Resources | 2 vCPU / **8 GiB** minimum |

8 GiB is not padding. Stage 2 loads a BERT-sized NER model; splitting the
pipeline means paddle is unloaded before torch is imported, but the NLP
stage alone still wants several GiB.

Environment for the Job (project variables work too):

```
FILE_STORAGE_DIR=/home/cdsw/storage/patient_files
DEID_OCR_PYTHON=/home/cdsw/OCR/.venv-ocr/bin/python
DEID_NLP_PYTHON=/home/cdsw/OCR/.venv-nlp/bin/python
HIVE_HOST=<your HS2 host>
HIVE_PORT=10000
HIVE_DB=hive_patients
HIVE_AUTH=GSSAPI
HIVE_USER=<workload user>
```

`DEID_MODELS_DIR` and `DEID_OFFLINE` only need setting if the store is
somewhere other than `OCR/models` — the defaults are right.

Create it, then **copy the job id out of the URL** (`.../jobs/<job-id>`)
into the project variable `CML_DEID_JOB_ID`. That is the chicken-and-egg:
the API needs the job's id, and the job cannot exist until the project
does.

### Add a sweep

The API starts a run per request, so the Job needs no schedule to
function. Add a **second** Job on a schedule anyway — same script, no
`DEID_FILE_ID`:

```
Name:     deidentify-sweep
Script:   scripts/deid_worker.py
Schedule: every 15 minutes
Env:      DEID_RETRY_STALE_MINUTES=120
```

It drains anything whose trigger never reached the control plane, and
re-claims rows stuck in `processing` because a run died mid-file. Without
it a single dropped API call strands a document forever. Do not schedule
it more often than a run takes to finish.

> `DEID_RETRY_STALE_MINUTES` measures age since *upload*, not since the
> row was claimed — `patient_application_files` has no `updated_at` column. Set it
> comfortably longer than a run takes.

---

## 9. Wire the Application to the Job

This is the part that makes the dashboard's **De-identify** button start
a Job run. The wiring is already in the repo; what follows is the code
and the three variables it needs.

### The shape

```
  browser                API Application            Cloudera control plane
     │                          │                            │
     │  POST /files/{id}/deidentify                          │
     ├─────────────────────────►│                            │
     │                          │ mark row 'queued'          │
     │  200 (row, queued)       │                            │
     │◄─────────────────────────┤                            │
     │                    background task                    │
     │                          │  POST /api/v2/projects/…/jobs/{job}/runs
     │                          ├───────────────────────────►│
     │                          │   { environment: { DEID_FILE_ID: … } }
     │                          │                            │
     │                          │                     starts the Job run
     │                          │                            ▼
     │                          │                   scripts/deid_worker.py
     │                          │                   → app.deid.run_deidentification
     │                          │                   → OCR/scripts/run_deid.py
     │                          │                   → writes 'done' onto the row
     │  GET /files/{id}  (poll) │                            │
     ├─────────────────────────►│  reads Hive ───────────────┘
```

No socket, by design: the client re-reads the row to see the result.

### Configuration

| Variable | Default | What it is |
|---|---|---|
| `DEID_BACKEND` | `inline` | set to **`cml_job`** on Cloudera |
| `CML_DEID_JOB_ID` | — | **required**; the Job id from step 8 |
| `CML_PROJECT_ID` | `$CDSW_PROJECT_ID` | injected by the platform |
| `CML_API_KEY` | `$CDSW_APIV2_KEY` | injected; a *legacy* API key will not work |
| `CML_API_URL` | derived from `$CDSW_DOMAIN` | `https://<domain>/api/v2` |

Inside a CML Application the platform injects the `CDSW_*` vars, so in
practice only `DEID_BACKEND=cml_job` and `CML_DEID_JOB_ID` are set by
hand.

`CDSW_APIV2_KEY` is only injected when the workspace has API v2 enabled
for the project. If it is missing, mint a key in **User Settings → API
Keys** and set `CML_API_KEY` explicitly.

The API says at boot whether dispatch will work (`app/main.py`), so a
half-configured backend shows up in the Application log rather than as a
user clicking the button and the row going straight to `failed`:

```
deid_backend_misconfigured  backend=cml_job
detail=DEID_BACKEND=cml_job but the Cloudera API is not configured;
       set CML_DEID_JOB_ID (and CML_API_KEY / CML_PROJECT_ID if not
       running inside a CML workload)
```

A misconfiguration is deliberately not fatal — the rest of the API is
perfectly usable, and refusing to start would turn a broken feature into
a broken deployment.

### The endpoint — `app/routers/patient_application_files.py`

Returns immediately; the work happens elsewhere.

```python
@router.post("/files/{file_id}/deidentify", response_model=PatientFile)
def deidentify_patient_file(
    file_id: str,
    background: BackgroundTasks,
    request: Request,
    cursor=Depends(get_cursor),
    _actor: User = Depends(require_permission("patient:update")),
):
    record = crud.get_file_or_404(cursor, file_id)

    # 'pending' is deliberately not in this list: that is the state every
    # file is uploaded in, so rejecting it would make a document
    # impossible to de-identify the first time.
    if record.deid_status in ("queued", "processing"):
        raise ValidationError("This file is already queued for de-identification")

    if record.file_extension.lower() != "pdf":
        raise ValidationError(
            f"Only PDF files can be de-identified (got '{record.file_extension}')"
        )

    # Marked before dispatch so the UI reflects it on the very next read,
    # rather than looking like nothing happened.
    updated = crud.update_file(
        cursor, file_id, PatientFileUpdate(deid_status=queued_status())
    )

    background.add_task(
        dispatch_deidentification,
        file_id=file_id,
        request_id=request.headers.get("X-Request-ID"),
    )
    return updated
```

### The dispatch — `app/deid.py`

One function, two backends. Switching changes *scheduling*, not logic:
both paths end in the same `run_deidentification()`.

```python
DEID_BACKEND = os.environ.get("DEID_BACKEND", "inline").strip().lower()


def queued_status() -> str:
    """Inline runs mark 'processing' immediately, because the work begins
    in this process a moment later. The Job backend marks 'queued': the
    run has been *asked for* but no worker has claimed the row yet, and
    marking 'processing' before anything is would leave a permanently
    stuck row if the run never starts."""
    return "queued" if DEID_BACKEND == "cml_job" else "processing"


def dispatch_deidentification(file_id: str, request_id: Optional[str] = None) -> None:
    """Never raises -- this runs detached from any request, so there is no
    error left to return."""
    if DEID_BACKEND == "inline":
        run_deidentification(file_id, request_id=request_id)
        return

    if DEID_BACKEND != "cml_job":
        log.error("deid_backend_unknown", backend=DEID_BACKEND, file_id=file_id)
        _set_status(file_id, deid_status="failed")
        return

    try:
        # DEID_FILE_ID scopes the run to this file. The worker still
        # drains anything else left pending, so a dropped trigger is
        # recovered by the next run rather than stranding a row.
        run_id = start_deid_job_run(environment={"DEID_FILE_ID": file_id})
        log.info("deid_job_dispatched", file_id=file_id, run_id=run_id)
    except ClouderaError as exc:
        log.error("deid_job_dispatch_failed", file_id=file_id, error=str(exc))
        _set_status(file_id, deid_status="failed")
```

### The API call — `app/cloudera.py`

One POST. Hand-rolled over `httpx` rather than pulling in `cmlapi`, which
is a large transitive dependency for the web process to carry for a
single call.

```python
def start_deid_job_run(environment: Optional[Dict[str, str]] = None) -> str:
    """Start a run of the de-identification Job. Returns the run id."""
    config = _config()
    url = (
        f"{config['url']}/projects/{config['project_id']}"
        f"/jobs/{config['job_id']}/runs"
    )

    payload = {"project_id": config["project_id"], "job_id": config["job_id"]}
    if environment:
        # Values must be strings; the API rejects a JSON number here.
        payload["environment"] = {k: str(v) for k, v in environment.items()}

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {config['api_key']}"},
            timeout=CML_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise ClouderaError(f"Could not reach the Cloudera API: {exc}") from exc

    if response.status_code >= 400:
        raise ClouderaError(
            f"Cloudera API returned {response.status_code}: {response.text[:300]}"
        )

    return response.json().get("id", "")
```

`CML_API_URL` is derived from `CDSW_DOMAIN` as `https://<domain>/api/v2`.
Note that `CDSW_API_URL`, which the platform also injects, points at the
**v1** API and is not usable here.

The `environment` override is what scopes a run to one file without
needing a second Job.

### Test the call on its own

Before trusting the button, prove the API path works. In a Session:

```bash
python - <<'PY'
from app.cloudera import is_configured, start_deid_job_run
print("configured:", is_configured())
print("run id:", start_deid_job_run(environment={"DEID_FILE_ID": "<file-id>"}))
PY
```

A run should appear under **Jobs → deidentify → History** within seconds.
If `is_configured()` is `False`, one of `CML_PROJECT_ID`, `CML_API_KEY`,
`CML_DEID_JOB_ID` is missing — the error names which.

Or with plain curl, which isolates credentials from the code entirely:

```bash
curl -X POST \
  -H "Authorization: Bearer $CDSW_APIV2_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$CDSW_PROJECT_ID\",\"job_id\":\"$CML_DEID_JOB_ID\",
       \"environment\":{\"DEID_FILE_ID\":\"<file-id>\"}}" \
  "https://$CDSW_DOMAIN/api/v2/projects/$CDSW_PROJECT_ID/jobs/$CML_DEID_JOB_ID/runs"
```

### Restart the Application

Environment changes are read at process start:

**Applications → patients-api → Restart**, then check its log for
`deid_backend backend=cml_job` with no `deid_backend_misconfigured`
above it.

---

## 10. Verify end to end

In order, because each step depends on the last:

1. **Upload a PDF** to a patient in the dashboard.
2. **Click De-identify.** The row goes to `queued` immediately.
3. **A run appears** under **Jobs → deidentify → History** within seconds.
4. **The row reaches `done`** a minute or two later, the badge shows
   `redacted`, and the redacted copy is viewable in the UI.
5. **Verify the redaction.** In a Session:

   ```bash
   cd /home/cdsw/OCR
   .venv-ocr/bin/python scripts/verify_redaction.py \
       /home/cdsw/storage/patient_files/<application-id>/deidentified/<file>_deid.pdf \
       --expect-absent "the patient's name" \
       --expect-absent "their MRN"
   ```

### Where each status comes from

```
pending     uploaded, nobody has asked for it
queued      the API asked Cloudera to start a run   (cml_job only)
processing  a worker claimed the row
done        a redacted copy exists
failed      look at the Job run's log
```

---

## Troubleshooting

**Row stuck in `queued`.** The Job run never started. Check
`CML_DEID_JOB_ID` and the API Application's log for
`deid_job_dispatch_failed` — the message carries the control plane's own
reason (bad job id, expired key).

**Row stuck in `processing`.** A run died mid-file. The sweep re-claims
it; without a sweep, re-run `deid_worker.py --file-id <id>` by hand.

**Row goes straight to `failed`, log says `model ... missing from the
model store`.** Step 6 did not land. Re-run `make check-models` in a
Session — the message names the directory it looked in.

**A run *hangs* for minutes before failing.** Something is still trying
to download. Check that `DEID_OFFLINE` has not been set to `0` anywhere,
and that nothing overrides `DEID_MODELS_DIR` to a path that does not
exist.

**`ocr stage interpreter not found`.** `DEID_OCR_PYTHON` /
`DEID_NLP_PYTHON` point at venvs that are not there, or that were built
by an interpreter the runtime no longer has. `make distclean && make
venvs install`, then re-unpack the models (`distclean` does not touch
`models/`).

**The API Application is slow or memory-hungry.** It should carry none of
the ML stack — with `DEID_BACKEND=cml_job` it only marks the row and
POSTs. If it is loading models, `DEID_BACKEND` is still `inline`.

**Job runs out of memory.** Raise the Job to 8 GiB. Stage 2 loads a
BERT-sized model; the two stages do not run at once, but the NLP one
alone needs the headroom.

**Both stages fail with an import error naming the other stack.** Someone
installed both requirement files into one venv, or a module crossed the
import boundary. `tests/test_ocr_stage_isolation.py` guards the latter —
run `pytest tests/test_ocr_stage_isolation.py` from the repo root.

---

## Quick reference

```bash
# --- one-time, on a machine with network access ---
cd OCR
make venvs install          # both virtualenvs
make models                 # ~570MB into OCR/models
make check-models           # do they load offline?
make run verify             # end-to-end on the synthetic sample
tar czf ~/models.tar.gz models

# --- on Cloudera AI, in a Session ---
cd /home/cdsw/OCR
make venvs install
tar xzf ~/models.tar.gz
make check-models
python3 scripts/run_deid.py --preflight

# --- the job, by hand ---
python3 scripts/run_deid.py --input <pdf> --output-dir /home/cdsw/out
cd /home/cdsw && python scripts/deid_worker.py --file-id <file-id>

# --- the job, triggered by the Application ---
# DEID_BACKEND=cml_job + CML_DEID_JOB_ID, then click De-identify.
```
