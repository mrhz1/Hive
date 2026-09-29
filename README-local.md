# Local Hive dev environment

HiveServer2 (Apache Hive 4.0.0) in Docker with ORC transactional tables,
using impyla like on Cloudera AI.

## Getting started

```
make up      # start Hive (first run takes 1-2 min, needs ~4GB RAM for Docker)
make check   # wait until Hive is ready
make init    # create tables and seed data (users: admin, viewer)
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
| `intake_files` | every file found in the intake folder |
| `intake_batches` | one row per intake sweep |

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

### Intake (drop folder)

Documents come in by being copied into `INTAKE_DIR`, not uploaded through
the app. Each file is matched to a patient code, de-identified, and written
to a mirror folder inside the intake root:

```
storage/incoming_data/A/B/C/AA1234/image.dcm
storage/incoming_data/de_identified/A/B/C/AA1234/AA1234_<date>_<serial>.dcm
```

Commands:

```bash
make intake          # dry run: show what a sweep would do
make intake-apply    # sweep and record the files in Hive
make intake-deid     # redact everything queued
make intake-run      # check once, sweep + redact if a push has finished
make intake-watch    # same, every minute

python scripts/intake_sweep.py --root /some/drop --settle-seconds 0
python scripts/intake_deid.py --workers 4
python scripts/intake_deid.py --limit 1
```

#### When a run starts

`intake_run.py` only starts when a push has finished:

- a `batch.done` file (`INTAKE_BATCH_MARKER`) is in the tree, or
- nothing has changed for `INTAKE_SETTLE_SECONDS`.

"Changed" uses the later of mtime and ctime, because `cp -p` / `rsync -t`
keep the source mtime. Hidden files (rsync temp files, `.DS_Store`) are
ignored. The marker file is deleted after its push is swept.

Only one run at a time: a run holds a file lock on
`<INTAKE_DIR>/.intake/run.lock` and a second run exits with `busy`.
If a run was interrupted, the next run finishes the queue even if nothing
new arrived.

#### Scheduling on Cloudera AI

Create a Job:

| | |
|---|---|
| Script | `scripts/intake_run.py` |
| Schedule | every minute (`* * * * *`) |
| Environment | `INTAKE_DIR`, `SUBMITTED_DIR`, `DEID_WORKERS`, `DEID_WORKER_CPU_THREADS`, `INTAKE_SETTLE_SECONDS` and the Hive variables |

`INTAKE_DIR` has to be on the same volume the sender writes to and the API
reads from. If the sender can write `batch.done` at the end of a push,
redaction starts right away instead of waiting for the settle time.

#### Statuses

| status | meaning |
|---|---|
| `queued` | has a code and a supported format, waiting to be redacted |
| `processing` | being redacted |
| `done` | redacted, ready to attach to an application |
| `failed` | redaction failed, reason in `detail` |
| `skipped` | unsupported format or no patient code |
| `conflict` | path and file name have different codes |
| `claimed` | attached to an application |
| `submitted` | its application was submitted |
| `superseded` | an old skipped/failed row that was pushed again and fixed |

Skipped and conflict files are stored as rows too, so they show up on the
Intake page and can be fixed.

#### Finding the code

- **Folder:** a folder name that is a full code (`A/B/C/AA1234/x.dcm`).
  The deepest one wins.
- **File name:** a code at the start of the name, followed by a
  non-alphanumeric character or the end (`AA1234.pdf`, `AA1234_chest.pdf`).
  `AVDD12005_x.pdf` and `chest_AA1234.pdf` don't count.
- **File type** comes from the file content when there is no extension
  (PACS exports like `IM000001`).

If the folder and the name disagree, the file goes to `conflict` and someone
has to pick one of the two codes on the Intake page. Only those two codes
are accepted.

#### Pushing the same folder again

Files are matched on checksum + full path. Same bytes at the same path is
the same file and is skipped. This means you can fix file names at source
and push the whole folder again: the fixed files are picked up, and the old
skipped rows are marked `superseded`. The same document in two patients'
folders is treated as two files.

#### Workers and memory

Memory is the limit, not CPU. A worker killed for memory (exit -9) produces
nothing, so size `DEID_WORKERS` from measured usage:

```
workers = min(cores / cores_per_worker, RAM / RAM_per_worker)
```

- `DEID_WORKER_CPU_THREADS` sets `OCR_CPU_THREADS`, `OMP_NUM_THREADS` and
  `MKL_NUM_THREADS` for each worker (OCR defaults to 8 threads).
- `DEID_WORKER_MEMORY_GB` caps the number of workers to what fits in free
  memory. It does not limit memory itself; the container does that.
- `DEID_CHUNK_DICOM` / `DEID_CHUNK_DOCUMENTS` set how many files go into one
  pipeline run, so the models load once per run.

For reference: about 19-31 seconds per page on a 4-core job.

#### Large pushes

Hive statements are slow (~0.4-1 s each, however many rows), so everything
is done in batches: 500 rows per insert, one claim query per chunk, one
update per chunk for results, and `GROUP BY` for counts (cached 10 s).
Only folders changed since the last sweep are walked, with a full sweep
once a day (`INTAKE_FULL_SWEEP_HOURS`). Lists on the Intake page are paged,
and the full list can be downloaded as CSV.

To spread the work over several machines, each process takes a set of
shards (256 in total, by the first two characters of the row id):

```bash
python scripts/intake_run.py --watch --shards 0-3  --of 12   # machine 1
python scripts/intake_run.py --watch --shards 4-7  --of 12   # machine 2
python scripts/intake_run.py --watch --shards 8-11 --of 12   # machine 3
```

Every shard must be covered by exactly one process. The process with shard
0 also does the sweep.

Results are written to a local journal (`.intake/journal/`) before they go
to Hive. If a worker is killed, the next start publishes what it already
finished and puts the rest back in the queue, so it is safe to stop and
restart at any time.

Workers write a heartbeat file every few seconds (`.intake/workers/`). The
Intake page uses these for speed, time left and worker status, and shows a
red banner if files are waiting and no worker has reported for
`INTAKE_HEARTBEAT_STALE_SECONDS`.

For DICOM, pixels are only changed when identifying text is found in the
image. Otherwise only the tags are de-identified. The `detail` column says
which one happened.

#### Intake page

`/intake` (needs `application:view`). Shows progress, workers, and tiles for
Conflicts, Skipped, Failed, Waiting and De-identified.

- Skipped/Failed: full path and reason, with *Copy list* and CSV download
  to send to whoever owns the source.
- Failed: *Retry* puts the file back in the queue.
- Conflicts: pick one of the two codes (needs `application:update`, audited).

| endpoint | |
|---|---|
| `GET /intake/counts` | counts per status |
| `GET /intake/files?status=` | files for a status (paged, `X-Total-Count` header) |
| `GET /intake/files/export?status=` | CSV of all files for a status |
| `GET /intake/codes` | codes with redacted files not attached yet |
| `GET /intake/batches` | sweeps, newest first |
| `GET /intake/progress` | overall progress and workers |
| `GET /intake/progress/batches` | progress per push |
| `POST /intake/files/{id}/resolve` `{"code": ...}` | resolve a conflict |
| `POST /intake/files/{id}/retry` | retry a failed file |

#### Creating an application from intake

Step 1 is picking a patient code (`IntakeCodePicker`). If a patient with
that code exists it is selected, otherwise the patient form opens with the
code filled in. Step 2 lists the code's redacted files grouped by folder
(`IntakeFilePicker`), and `POST /applications/{id}/intake-files` attaches
them:

- one row per file, with `file_path` = original and
  `de_identified_file_path` = redacted copy. Nothing is copied.
- the file's code has to match the application's patient.
- all files are checked before any are attached.
- the intake row becomes `claimed` so no other application can take it.

Removing an intake file from a draft (or deleting the application) puts it
back to `done`. The files on disk are not deleted.

`frontend/e2e/intake.spec.ts` tests this flow. It needs real redacted files,
so it only runs when `E2E_INTAKE_CODE` is set.

#### Submitting

On submit both copies are moved under the patient (`app/submission.py`):

```
storage/submitted/AA1234/original/image.dcm
storage/submitted/AA1234/de_identified/AA1234_20260924_1790261077741000.dcm
```

- If a name is taken, `_2`, `_3`... is added.
- The OCR text and report files are deleted.
- Empty folders left behind are removed.
- The intake row becomes `submitted`.
- With `DEID_KEEP_ORIGINAL=false` the original is deleted instead.

The sweep never walks `SUBMITTED_DIR`, even if it is inside the intake
folder.

`intake_files` is also the only place that links an original to its
redacted copy, since the names don't match.

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
