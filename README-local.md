# Local Hive dev environment

HiveServer2 (Apache Hive 4.0.0) in Docker with ORC transactional tables,
using impyla like on Cloudera AI.

## Getting started

```
make up      # start Hive (first run takes 1-2 min, needs ~4GB RAM for Docker)
make check   # wait until Hive is ready
make init    # create empty tables with the admin and viewer logins
make verify  # check INSERT/UPDATE/DELETE work
make run     # start the API on port 8100
make test    # run the tests
```

`make init` drops and recreates all tables. On a database with data use
`python scripts/migrate_columns.py --apply` instead.

Hive queries are slow (a few seconds each, even single inserts), that's
normal.

Other commands: `make logs` shows the Hive logs, `make down` stops it (data
stays in the `hive-warehouse` volume).

## API

Docs at `http://localhost:8100/docs`.

### Tables

| table | |
|---|---|
| `roles` | `permissions` is an `ARRAY<STRING>` |
| `users` | linked to a role |
| `patient` | `id` is the patient code from the documents |
| `patient_applications` | one submission for a patient, with status, assignee, etc. |
| `patient_application_files` | one row per document, with original and de-identified paths |
| `file_metadata` | metadata read from each file at upload (JSON string) |
| `audit_logs` | changes (create/update/delete), append only |
| `access_logs` | who viewed/downloaded what, partitioned by day |

### Endpoints

- `/users`, `/patients`, `/roles`, `/applications`: POST, GET list, GET,
  PUT, DELETE. `/applications?patient_id=` filters by patient.
- `/logs`: POST, GET list, GET (no update/delete).
- `/applications/{id}/files`: upload (POST multipart) and list.
- `/applications/{id}/files/background`: upload in the background, returns
  202 with a job, progress at `/upload-jobs/{id}`.
- `/files/{id}`: GET, PUT, DELETE.
- `/files/{id}/content`: download (`?deidentified=true` for the redacted copy).
- `/files/{id}/metadata`: metadata extracted at upload.
- `/files/{id}/image?frame=N`: DICOM frame as PNG (`X-Frame-Count` header).
- `/files/{id}/text`: Word document text.
- `/files/{id}/deidentify` and `/applications/{id}/files/deidentify-all`:
  still there, but not used by the UI anymore since intake does the
  de-identification.
- `/file-metadata`: search all metadata (`search`, `status`, `file_type`,
  `patient_id`), `/file-metadata/export` for Excel.
- `/files-library/...`: de-identified files (needs `files:*` permissions).
- `/intake/...`: see Intake below.

File endpoints use `application:*` permissions.

### Auth and permissions

Every endpoint except `/health` needs a `REMOTE-USER` header with an
active username. Permissions are `<model>:<action>`, for the models
`user`, `patient`, `role`, `log`, `application` and the actions `view`,
`create`, `update`, `delete` (defined in `app/security.py`). 401 for an
unknown user, 403 for a missing permission.

The app doesn't do login itself, on Cloudera the platform sets
`REMOTE-USER`. Locally:

```bash
curl -H "REMOTE-USER: admin" http://localhost:8100/users
```

### Audit log

Creating, updating or deleting users and patients writes an audit entry
(CREATE has no `old_values`, DELETE has no `new_values`). It's written in a
background task, so a failure is logged but doesn't fail the request.

### Metadata

- Metadata that came with the file (PDF info, DICOM tags, Word
  properties) is saved in `file_metadata` at upload (`app/file_metadata.py`).
  Legacy `.doc` files need `olefile`.
- Info added by this system (de-identified, when, patient) is written into
  the output file itself (`app/embed.py`): PDF `keywords`, DICOM
  `DeidentificationMethod`, Word `comments`.

### File types

The type is detected from the file content when the name has no known
extension (`app/filetype.py`), e.g. PACS files named `IM000001`:
DICOM (`DICM`), PDF (`%PDF-`), docx (zip with `word/`), doc (OLE2).

### Intake

Files are copied into the incoming folder (`INTAKE_DIR`). When someone
clicks **Start de-identification** on the Intake page (or runs
`make intake-start`), every file in it is processed and moved into
`DATA_DIR`:

```
INTAKE_DIR/A/B/C/AA1234/image.dcm                         (incoming, the queue)

DATA_DIR/original/A/B/C/AA1234/image.dcm                  original, same path
DATA_DIR/de_identified/AA1234/A/B/C/AA1234_<date>_<serial>.dcm
DATA_DIR/de_identified/AA1234/A/B/C/AA1234_<date>_<serial>.dcm.json   sidecar
DATA_DIR/failed/...                                       redaction failed
DATA_DIR/needs_attention/...                              no code, unsupported, conflict, duplicate
DATA_DIR/.intake/                                         locks, heartbeats, run reports
```

Whatever is still in the incoming folder hasn't been done yet, so a run
can be stopped and started again at any time. `INTAKE_DIR` and `DATA_DIR`
should be on the same disk so moves are instant. There are no intake
tables in Hive.

```bash
make intake-preview    # show what a run would do, moves nothing
make intake-start      # process everything in INTAKE_DIR

python scripts/intake_run.py --workers 4
python scripts/intake_run.py --limit 10
```

#### What happens to a file

1. Files changed in the last `INTAKE_SETTLE_SECONDS` are still being copied,
   so the run waits for them (up to `INTAKE_SETTLE_WAIT_SECONDS`, 5 minutes)
   and then does them. Any not settled by then are left for the next run.
2. The patient code is read from the path or file name. Files without a
   code, with an unsupported format, with two different codes, or that are
   an exact copy of a file already in `original/` go to `needs_attention/`
   with a `.reason.json` file next to them.
3. The file is redacted into `de_identified/<CODE>/...` under a temporary
   `.partial` name.
4. The original is moved to `original/`, then the copy gets its final
   name and a `.json` sidecar (original path, method). The pipeline's text
   and report files are deleted.
5. If redaction fails, the original goes to `failed/` with the reason.
6. The code is passed to the patient creator (see below).

Before step 3 a small file is written to `.intake/pending/`. If the
process is killed in the middle, the next run uses it to either redo the
file (original still in incoming) or finish it (original already moved).

Only one run at a time (a lock file in `.intake/`). To use several
machines, give each a share of the files:

```bash
python scripts/intake_run.py --shards 0-3  --of 12   # machine 1
python scripts/intake_run.py --shards 4-7  --of 12   # machine 2
python scripts/intake_run.py --shards 8-11 --of 12   # machine 3
```

Files are split by a hash of their path, so each file is done by exactly
one machine.

#### Finding the code

- **Folder:** a folder name that is a full code (`A/B/C/AA1234/x.dcm`).
  The deepest one wins.
- **File name:** a code at the start of the name, followed by a
  non-alphanumeric character or the end (`AA1234.pdf`, `AA1234_chest.pdf`).
  `AVDD12005_x.pdf` and `chest_AA1234.pdf` don't count.
- **File type** comes from the file content when there is no extension
  (PACS exports like `IM000001`).

If the folder and the name disagree, the file goes to `needs_attention/`
and someone picks one of the two codes on the Intake page. The choice is
saved in `.intake/code_overrides.json` and the file goes back to incoming.

#### Patients are created automatically

When a file is done, its code is passed to a background thread. If there
is no patient with that code, it creates one with only the code filled in
and writes an audit entry (`CREATE patient`, user `intake`). The workers
don't wait for it. A lock file per code in `.intake/patients/` stops two
machines creating the same patient. At the start of each run it also
creates patients for any code folder in `de_identified/` that has none.

#### Workers and memory

Memory is the limit, not CPU. A worker killed for memory (exit -9) produces
nothing, so size `DEID_WORKERS` from measured usage:

```
workers = min(cores / cores_per_worker, RAM / RAM_per_worker)
```

- `DEID_WORKER_CPU_THREADS` sets `OCR_CPU_THREADS`, `OMP_NUM_THREADS` and
  `MKL_NUM_THREADS` for each worker (OCR defaults to 8 threads).
- `DEID_WORKER_MEMORY_GB` caps the number of workers to what fits in free
  memory.
- `DEID_CHUNK_DICOM` / `DEID_CHUNK_DOCUMENTS` set how many files go into one
  pipeline run, so the models load once per run.

Measured with 8 threads: about 18 s per handwritten page and 31 s per
printed page (OCR is almost all of it).

#### Intake page

`/intake` (needs `application:view`):

- Start button and status (running or idle, files left in incoming, done
  this run, speed, time left), workers, last runs
- Failed list: Retry moves the file back to incoming
- Needs attention list: pick a code for conflicts; the rest are fixed at
  the source and pushed again
- Copy list and CSV download for both lists

| endpoint | |
|---|---|
| `POST /intake/start` | start a run (409 if one is running) |
| `GET /intake/status` | status, counts and workers |
| `GET /intake/runs` | last run reports |
| `GET /intake/files?kind=failed\|attention` | a list (paged, `X-Total-Count`) |
| `GET /intake/files/export?kind=` | the list as CSV |
| `POST /intake/files/retry` `{"path"}` | move a failed file back to incoming |
| `POST /intake/files/resolve` `{"path", "code"}` | pick the code for a conflict |
| `GET /intake/codes` | codes with de-identified files not attached yet |
| `GET /intake/codes/{code}/files` | those files |

With `DEID_BACKEND=cml_job` the Start button starts the Cloudera Job set in
`CML_INTAKE_JOB_ID`. Otherwise it starts `scripts/intake_run.py` in the
background on the API machine.

#### Creating an application from intake

Step 1 is picking a patient code (`IntakeCodePicker`). Step 2 lists the
code's de-identified files grouped by folder (`IntakeFilePicker`), and
`POST /applications/{id}/intake-files` attaches them: one row per file
with `file_path` = the original in `original/` and
`de_identified_file_path` = the copy. Nothing is copied or moved, and a
file can only be on one application.

Removing a file from an application (or deleting the application) never
deletes files under `DATA_DIR`. Submitting stamps the patient code on
redacted PDFs but doesn't move `DATA_DIR` files; they're already in their
final place. Files uploaded through the application page still go to
`SUBMITTED_DIR` as before.

### Patient codes

The patient id is the code from the documents, not a generated id.
`POST /patients` takes it as `id`. Format: two to four letters then three or
four digits (`AA0001`, `AVDD1200`), case-insensitive, stored upper-case.
Change it with `PATIENT_CODE_PATTERN`. `app/ids.py` has `is_patient_code`
and `clean_patient_code`, used by both the API and the sweep.

A typo that is still a valid code (`AA1235` for `AA1234`) can't be caught,
which is why the code is shown large when picking files. Duplicate codes
return 409 (checked with a `SELECT`, since Hive has no constraints).

### Document names

- Uploaded document: `<code>-<type>-<date>-<16-digit serial>.<ext>`
  (`storage.document_name`).
- De-identified copy: `<code>_<date>_<16-digit serial>.<ext>`, e.g.
  `AA1234_20260924_1790261077741000.pdf` (`deid.deid_output_name`). The date
  and serial are from the de-identification run.

The OCR pipeline names its outputs after the input file, so
`deid._rename_outputs` renames the copy, text and report together after a
successful run.

### Original and de-identified copies

One `patient_application_files` row holds both paths. `/files/{id}/content`
returns the original and `?deidentified=true` the redacted copy (same for
the preview endpoints). Don't match them by name, the names are different.

The file viewer has an Original / De-identified toggle when both exist. It
is hidden for submitted applications.

Originals are kept by default (`DEID_KEEP_ORIGINAL`). Two things to be aware
of:

- the originals folder keeps growing, there is no purge yet.
- reading an original is logged with `access_logs.identified`.

### Email

`app/mailer.py` sends through an SMTP relay (port 25, no auth by default).
Set `SMTP_HOST` to enable it; without it sends are logged and skipped. See
`.env.example` for `SMTP_FROM`, `SMTP_STARTTLS` and `SMTP_USER`.

A failed send never raises, `send_email` returns `False` and logs
`email_send_failed`.

Emails (`app/notifications.py`) go to the application's assignee, or its
creator if nobody is assigned:

- application assigned
- background upload finished (with failed file names)
- de-identification finished (with files that failed)

The de-identification email is sent once per application, by the run that
finishes last (`app/deid_notices.py`). A marker file in
`FILE_STORAGE_DIR/.deid-notices/` stops a duplicate if two runs finish at
the same time (`DEID_NOTICE_REPEAT_SECONDS`, default 120). Intake redaction
doesn't send emails since there is no application yet. With the `cml_job`
backend the Job needs `SMTP_HOST` and `APP_BASE_URL` too.

### Background uploads

`POST /applications/{id}/files/background` saves the files to
`FILE_STORAGE_DIR/.uploads/<job id>/`, returns 202, and processes them in a
background task (move, insert row, extract metadata, email). A failed file
is marked `failed` on the job and the others continue (`partial`). Job
progress is kept in memory, so after a restart `/upload-jobs/{id}` returns
404, but the files already processed are fine.

### Rejections

`/rejections` (needs `application:view`) shows:

- rejected applications (`/applications?status=rejected`)
- rejected documents (`/files/rejected`), with the reviewer's note. For each
  one you can view or download either copy, upload a replacement, or
  approve it.

Uploading a replacement (`/files-library` with `replaces_file_id`) sets
`review_status` back to `pending` and clears the note. The old note is kept
in the audit log (`REPLACE` action).

### Audit log and access log

| | `audit_logs` | `access_logs` |
|---|---|---|
| Records | changes | reads, downloads, exports, denied requests |
| Written by | `app/audit.py` | `app/access_log.py` (buffered) |
| Partitioned | no | by day |

Access log rows include the user, IP, user agent, request id, patient,
`identified` (original or redacted copy) and `record_count` for exports.
Patient list views aren't logged, detail views are. Events are written in
batches every few seconds, and also to the app log right away. Filter by
date on the Access log page to keep queries fast.

Remove UPDATE/DELETE grants on both tables for the app user in production.

### Alerts

`scripts/access_alerts.py` (run as a scheduled CML Job) emails when a user
goes over a limit: many downloads, large exports, denied requests, auth
failures. Limits are in `.env.example`.

```bash
python scripts/access_alerts.py --window 60 --dry-run
```

It only sees requests that reach the API.

### Logging

structlog, with `request_id`, `source_ip` and `user_agent` on every line of
a request. `source_ip` comes from `X-Forwarded-For` using
`TRUSTED_PROXY_COUNT`. `LOG_FORMAT` is `console` in a terminal and `json`
otherwise. No patient data goes in the logs.

### Known limits

- Unique checks (username, email, etc.) are done with a SELECT since Hive
  has no constraints, so two requests at the same time can both pass.
- Every request looks up the user and role, which costs a Hive query.

## Config

`.env.local` uses the same variable names as Cloudera AI (`HIVE_HOST`,
`HIVE_PORT`, `HIVE_DB`, `HIVE_AUTH`, `HIVE_SERVICE`, `HIVE_USER`,
`CDSW_APP_PORT`), only the values change. Copy `.env.example` to start.

`conf/hive-site.xml` is mounted into the container. It sets NOSASL auth and
the transaction manager (needed for UPDATE/DELETE). It replaces the image's
`hive-site.xml` completely, so it also contains the image's default
settings. Add new settings to this file and keep the existing ones.

## Troubleshooting

**`SASL(-1): generic failure`**: auth mismatch. Locally `HIVE_AUTH` must be
`NOSASL`, on Cloudera `GSSAPI`.

**`TSocket read 0 bytes`**: usually Hive is still starting (1-2 min on
first run). `make check` waits 150s (`HIVE_CHECK_TIMEOUT`). Check:

```bash
docker compose ps
docker compose logs -f hiveserver2   # wait for 'Starting HiveServer2'
```

If it never works, check `conf/hive-site.xml` is mounted:

```bash
docker exec hive-local grep -A1 authentication /opt/hive/conf/hive-site.xml
```

**Every query resets the connection**: Hive isn't fully started, or
`hive-site.xml` is missing required settings. Check `make logs` and
`docker ps -a`.

**Port 10000 refuses connections**: still starting, or Docker is out of
memory (give it ~4GB).

**`SystemError: PY_SSIZE_T_CLEAN macro must be defined`**: old thrift
version, breaks on queries with many rows. Use impyla 0.24.0 and thrift
0.24.0 (pinned in `requirements-dev.txt`).

**impyla fails to install/import**: use Python 3.10 with the versions in
`requirements-dev.txt`.

**`SemanticException [Error 10294]` on UPDATE/DELETE**: the transaction
manager isn't set, check `hive.txn.manager` and `hive.support.concurrency`
in `conf/hive-site.xml`.

**`SemanticException [Error 10297]`**: the table isn't transactional.
Every table in `sql/schema.sql` has `TBLPROPERTIES ('transactional'='true')`,
keep it on new tables. `DESCRIBE FORMATTED <table>` should show
`MANAGED_TABLE` and `transactional=true`.
