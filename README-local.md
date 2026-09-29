# Local Hive dev environment

Real HiveServer2 (Apache Hive 4.0.0) in Docker, ORC managed/transactional
tables, connected via impyla, the same dialect and Python client used on
Cloudera AI. No DuckDB/SQLite substitution.

## Startup sequence

```
make up      # docker compose up -d -- first run takes 1-2 min (embedded
             # Derby metastore init). Needs ~4GB RAM available to Docker.
make check   # poll until SHOW DATABASES succeeds
make init    # apply sql/schema.sql, seed roles/users/patients.
             # Seeds the usernames 'admin' and 'viewer' -- those are the
             # REMOTE-USER values the API authenticates with.
make verify  # prove INSERT/SELECT/DELETE (ACID) works on ORC
make run     # start the FastAPI app on CDSW_APP_PORT (8100)
make test    # run pytest suite (FastAPI app tests)
```

> `make init` **drops and recreates every table.** It is for an empty
> database. On one that already has data, use
> `python scripts/migrate_columns.py --apply` instead, see
> [Columns added after launch](DEPLOYMENT.md#columns-added-after-launch).

Expected timings:
- `make up`: container starts in seconds, but HiveServer2 itself isn't
  ready for ~60-120s while Derby initializes. Port 10000 is bound before
  it can serve a session, so a check inside that window sees
  `TSocket read 0 bytes` rather than a connection refusal. `make check`
  waits it out (150s; `HIVE_CHECK_TIMEOUT` to change), so a failure from
  it means something really is wrong, see Troubleshooting.
- `make init` / `make verify`: each Hive query (including single-row
  INSERT) can take a few seconds due to query planning overhead, this is
  normal Hive behavior, not a local misconfiguration.

## Day to day

- `make logs`, tail the HiveServer2 container logs.
- `make down`, stop the container (named volume `hive-warehouse`
  persists your data across restarts; `docker volume rm` it to reset).

## The API

Interactive docs at `http://localhost:8100/docs` once `make run` is up.

### Tables

| table | notes |
|---|---|
| `roles` | `id`, `name`, `permissions ARRAY<STRING>` |
| `users` | `role_id` FK to roles; reads join in `role_name` + `permissions` |
| `patient` | singular, matching the Cloudera metastore. `id` is the **patient code off the documents**, supplied not generated, see [Patient codes](#patient-codes). `fstname`/`lstname` + provider (`p*`) and patient (`pt*`) contact blocks, `dt_reg`/`dt_b`/`dt_d` DATEs; no role, and no lifecycle columns, record data only |
| `patient_application_files` | one row per uploaded document, keyed on `application_id`, documents belong to a submission, not to a patient directly. Bytes live under `FILE_STORAGE_DIR`; the row carries the de-identification state. No per-file review verdict: that is recorded once, on the application |
| `file_metadata` | one row per file, holding the metadata the document **arrived carrying** (PDF info dict / DICOM tags / Word core properties), extracted at upload, as JSON-in-STRING. Schemaless on purpose, a DICOM study and a Word document share almost no fields. Facts this system generates afterwards are deliberately **not** here; see [Metadata](#metadata) |
| `patient_applications` | one submission of a patient + their documents for review; holds who did what and when, and `assigned_to_id`, the user set to work on it, who is emailed about its uploads |
| `audit_logs` | append-only; `user_id` names the acting caller; `old_values`/`new_values` are JSON-in-STRING |
| `intake_files` | one row per file found in a dropped batch, **including the ones we refuse**, a file nobody can place has to be visible and fixable. Also the only record of which original produced which redacted copy; see [Intake](#intake-drop-folder) |
| `intake_batches` | one sweep of the drop folder. Counts are derived, not stored |

### Endpoints

`/users`, `/patients`, `/roles`, `/applications` each expose POST / GET
(list) / GET `{id}` / PUT `{id}` / DELETE `{id}`. `/logs` exposes POST /
GET (list, filterable by `entity_type`, `entity_id`, `limit`) / GET
`{id}`, no update or delete, because an audit trail you can rewrite is
not an audit trail.

`/applications` accepts a `patient_id` query parameter to scope the list
to one patient.

Documents hang off an **application**, not a patient:
`/applications/{id}/files` (POST multipart / GET), and per file
`/files/{id}` (GET / PUT / DELETE), `/files/{id}/content` (GET,
`?deidentified=true` for the redacted copy), `/files/{id}/deidentify`
(POST) and `/files/{id}/metadata` (GET, what was extracted from the
document at upload time).

**De-identification is no longer started from an application.** Documents
are redacted in intake, before they can be picked (see
[Intake](#intake-drop-folder)), so the application page offers no
*De-identify* or *De-identify all* control. The endpoints
`/files/{id}/deidentify` and `/applications/{id}/files/deidentify-all` are
kept, unreachable from the UI, as an escape hatch for re-running a single
redaction found wanting at review; a bad redaction is otherwise fixed from
the Rejections page by attaching a better copy.

`/applications/{id}/files/background` (POST multipart) is the same upload
without the wait: it stages the bytes, answers 202 with an upload job,
and moves, records and parses the files afterwards.
`/upload-jobs/{id}` (GET) reports progress, and the user in the
application's `assigned_to_id` is emailed when the batch ends, whether
it worked or not. See [Email](#email).

`/file-metadata` (GET) browses every extraction at once rather than one
file at a time, filterable by `search` (which reaches inside the stored
blob, field names as well as values), `status`, `file_type` and
`patient_id`. `/file-metadata/export` takes the same filters and returns
the matching rows as an `.xlsx`, one column per extracted field found in
them.

All of them are gated on `application:*` rather than `patient:*`: these
files are part of a submission, so anyone who may read an application may
read its documents. A patient's documents are reached through their
applications.

### Auth and permissions

Every endpoint except `/health` requires a `REMOTE-USER` header naming an
active user's **username**, and the permission `<model>:<action>` (e.g.
`user:view`, `patient:delete`) on that user's role. Missing/unknown user
-> 401; missing grant -> 403.

The 20 grants are the product of five models, `user`, `patient`,
`role`, `log`, `application`, and four actions: `view`, `create`,
`update`, `delete`. Both tuples live in `app/security.py`, and
`scripts/init_db.py`, the test fixtures and the frontend's
`schemas/common.ts` all derive from them rather than restating the list.

**The app authenticates nobody.** `REMOTE-USER` is the username the
platform already authenticated (Kerberos/Knox on Cloudera AI) and passed
down; locally you set it by hand. Swapping the source means changing only
`_current_username` in `app/security.py`, routes and permission strings
are unchanged, so nothing branches on environment.

`make init` seeds two roles: **admin** (all 20 permissions) and **viewer**
(read-only), with usernames to match. Use those as `REMOTE-USER`:

```bash
curl -H "REMOTE-USER: admin" http://localhost:8100/users
```

### Audit logging

Writes to users and patients record a CREATE/UPDATE/DELETE entry.
Convention: CREATE has `old_values` null, DELETE has `new_values` null,
UPDATE has both. Roles are **not** audited (not requested, say the word
and it's a three-line addition).

Audit writes run in a FastAPI `BackgroundTask`, so the caller does not
wait on a second Hive INSERT. Measured on a POST /users: response
returned at 1393ms, the audit row landed ~550ms later. The trade-off,
taken deliberately: an audit failure cannot fail the request, so it is
logged loudly instead of raised (see `app/audit.py`). If audit durability
ever has to be transactional with the change itself, that has to move
back inline.

### Metadata

Two kinds, kept in two places on purpose.

**What the document arrived carrying** goes in the `file_metadata` table,
read once at upload by `app/file_metadata.py`:

| format | source | reader |
|---|---|---|
| PDF | info dictionary + page count | pypdf |
| DICOM | every non-sequence top-level tag (pixel data excluded) | pydicom |
| `.docx` | core properties | python-docx |
| `.doc` | OLE2 SummaryInformation streams | olefile |

`.doc` needs olefile because python-docx reads only the 2007+ zip format;
`_extract_word` picks the reader from the OLE2 signature, not the name, so
a misnamed file still reads. Without olefile installed a legacy `.doc`
records `failed` with the reason, which is what it did before, so the
degradation is to the old behaviour rather than to an error.

**What this system works out afterwards**, that a file was
de-identified, when, by what method, for which patient, is written into
the **output file's own metadata** by `app/embed.py`, never into the
table. Mixing the two made a row that was half read-out and half
written-in, indistinguishable once stored.

| format | where the facts land |
|---|---|
| PDF | appended to `keywords`; XMP dropped |
| DICOM | `PatientIdentityRemoved`, and appended to `DeidentificationMethod` (LO, VM 1-n) |
| Word | appended to `comments` |

These are **added, not substituted**. The de-identified file keeps its
own metadata, de-identified in place by the pipeline, so `Author:
<PERSON>` rather than no author, and overwriting that would throw away
the fact that a person was named there. See
[Metadata is de-identified, not deleted](OCR/README.md#metadata-is-de-identified-not-deleted)
for what the pipeline does to it first.

### Viewing a document

A browser renders a PDF in an `<iframe>` and **downloads** everything
else, which made "View original" a download button for every DICOM and
Word file. So the API produces something a browser will show
(`app/preview.py`):

| endpoint | format | returns |
|---|---|---|
| `/files/{id}/image?frame=N` | DICOM | one frame as PNG, plus `X-Frame-Count` |
| `/files/{id}/text` | `.docx` | the text as structure |

`/files-library/{id}/image` and `/text` mirror both for the redacted
copy, gated on `files:download` the way that router's other endpoints
are.

Rendering server-side rather than in the browser is what makes every
transfer syntax work, the client would otherwise need a WASM DICOM
codec. Frames are windowed through the VOI LUT when the study carries
one, and MONOCHROME1 is inverted so it is not shown as a negative.

The Word preview returns **structure, not HTML**: it is somebody's
uploaded document, and handing the browser markup out of it invites the
obvious injection. The client renders those strings as text nodes.
Legacy `.doc` cannot be previewed (python-docx reads only the 2007+
format) and says so rather than failing blankly.

### File types

Everything downstream keys off the extension, whether a file can be
de-identified, whether its metadata is read, which `DEID_*_DIR` its
redacted copy is filed under. A name is only a claim, and PACS exports
routinely have none at all (`IM000001`), so `app/filetype.py` resolves
the type from the bytes when the name does not already name a format we
handle:

- DICOM, `DICM` at offset 128 (or 0, for preamble-less writers)
- PDF, `%PDF-`
- `.docx`, zip signature with a `word/` entry
- `.doc`, the OLE2 signature

A name that *does* name a handled format wins, because it carries the
`.dcm`/`.dicom` and `.doc`/`.docx` distinctions the magic numbers cannot.
A file that is neither recognised nor named keeps whatever its name
claimed, an unknown format stays unknown rather than being guessed into
the wrong pipeline.

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

### The two trails

Two questions, two tables, one page each. Neither is ever updated or
deleted, and `audit_logs` should have `UPDATE`/`DELETE` revoked from the
application's Hive principal, because code cannot enforce that on itself.

| | `audit_logs` | `access_logs` |
|---|---|---|
| Answers | what **changed** | who **saw** it |
| Written by | `app/audit.py`, per change | `app/access_log.py`, buffered |
| Page | Audit log | Access log |
| Partitioned | no (low volume) | **by day** |

**`access_logs` records** downloads, previews, metadata reads, exports,
patient detail views, permission denials, authentication failures and
integrity refusals. Every row carries the actor, their source address and
user agent, the request id, the patient, and:

- **`identified`**, whether identified PHI left, or only a redacted
  copy. The same endpoint serves both, separated by `?deidentified=`, and
  only one of them is a disclosure. Without this flag every routine read
  looks like a breach.
- **`record_count`** on exports. "Exported 4,127 rows" and "exported 3"
  are different events.

Patient *list* views are deliberately not recorded: they fire on every
page load and would bury the reads that mean something. Detail views are.

**Writes are buffered.** A Hive INSERT costs seconds, almost all of it
planning, and the cost is per statement, so a batch of 200 rows costs
about what one row costs. A background thread flushes every few seconds,
which keeps Hive off the request path entirely. The trade is a bounded
loss window: a kill between flushes loses what was queued, which is why
each event is written to the Application log synchronously as it happens.

Reads are partition-pruned. Bound the dates on the Access log page and
the query reads those days; leave them open and it reads every day ever
recorded. That is the whole reason the table is partitioned from the
start, retrofitting a partition scheme means rewriting the table.

### Alerting

`scripts/access_alerts.py`, run as a CML Job on a schedule, counts events
per actor in a window and emails when a threshold is crossed, bulk
identified downloads, large exports, repeated denials, authentication
failures. It uses the SMTP relay already configured for upload notices,
so it needs no new infrastructure.

```bash
python scripts/access_alerts.py --window 60 --dry-run
```

The thresholds in `.env.example` are starting points. Watch them against
real traffic for a fortnight and move them: an alert that cries wolf gets
ignored, which is worse than not having one.

Two limits worth stating plainly. The app only sees requests that
**reach** it, failed sign-ins die at the proxy, so those logs have to be
read where they are. And this records access **through the API**: reading
files off the volume, or querying Hive directly, needs OS and Ranger
auditing respectively.

### Logging / tracing

structlog with `contextvars`, so one `request_id` threads through the
whole transaction, including the background audit write, which re-binds
it explicitly. Grep a single id to see a request end to end:

```
user_created       request_id=4c0e60a7... user_id=51963c2c...
request_finished   duration_ms=1393.15 status_code=201 request_id=4c0e60a7...
audit_recorded     action=CREATE entity_type=user request_id=4c0e60a7...
```

The middleware also binds **`source_ip` and `user_agent`** onto every
line of a request. "Which account" is not enough on its own to scope an
incident or to notice a shared login, and binding it once here means no
call site has to remember. `source_ip` comes out of `X-Forwarded-For`,
counting `TRUSTED_PROXY_COUNT` hops in from the right, everything
further left is client-supplied, so that count has to match the
deployment rather than be guessed.

`request_started` is at DEBUG. It carried nothing `request_finished`
does not, and at two lines per request it was most of the volume.

**Two renderings.** `console` is aligned key=value for a terminal;
`json` is one object per line for anything that ingests logs. Unset,
`LOG_FORMAT` picks by where stdout goes, a terminal gets console, a
captured pipe gets json, so local runs stay readable and Cloudera AI
gets machine-readable output without configuring anything. Tail a
production log by eye with `... | jq` and you get the pretty form back.

> **PHI does not go in the log stream.** Record values live in
> `audit_logs`, never in a log line, the log lines carry the *names* of
> the fields that changed. The de-identification subprocess is the one
> place this had to be actively defended: its dependencies quote the
> document into their warnings (see the gotchas in
> [OCR/README.md](OCR/README.md)), so `app/deid.py` logs a filtered,
> bounded `detail` rather than the raw stderr it used to.

Console rendering is for local readability; swap in
`structlog.processors.JSONRenderer()` in `app/logging_setup.py` if the
Cloudera AI log collector wants JSON.

### Known limits

- **Uniqueness is not atomic.** Hive has no UNIQUE constraint, so
  `username`/`email`/`phone_number`/role `name` checks are pre-check
  SELECTs. Two concurrent creates of the same value can both pass.
- **Permission checks cost a query.** Each request resolves the caller via
  the users/roles join. It shares the request's single connection rather
  than opening a second, but on Hive it is still real latency. A short TTL
  cache would help at the cost of staleness on role change.

## Config

`.env.local` uses the exact env var names Cloudera AI provides at runtime
(`HIVE_HOST`, `HIVE_PORT`, `HIVE_DB`, `HIVE_AUTH`, `HIVE_SERVICE`,
`HIVE_USER`, `CDSW_APP_PORT`). Only the values differ between here and
production, application code should never branch on environment; it just
reads these vars. `.env.example` is the committed template; `.env.local`
is gitignored.

`conf/hive-site.xml` is mounted into the container via `HIVE_CUSTOM_CONF_DIR`
and overrides the `apache/hive:4.0.0` image's defaults to match what
Cloudera AI's HiveServer2 already has configured: NOSASL auth, and a real
transaction manager (`hive.txn.manager` / `hive.support.concurrency`) so
DELETE/UPDATE work. The image's `HIVE_CUSTOM_CONF_DIR` mechanism replaces
`hive-site.xml` wholesale (it symlinks by filename, it doesn't merge), so
this file also carries forward the image's own default properties
(warehouse dir, Tez local-mode settings, etc.), if you add more overrides,
add them to this file rather than a second one, and don't drop the
existing properties.

## Troubleshooting

**`SASL(-1): generic failure` / auth negotiation errors from impyla**
This almost always means an auth mechanism mismatch. Locally we use
`HIVE_AUTH=NOSASL` because the dev HiveServer2 has no Kerberos. On
Cloudera AI, `HIVE_AUTH` is `GSSAPI` (Kerberos) instead, don't hardcode
either value in code; always read `HIVE_AUTH` from the environment. If you
see this error locally, check `.env.local` actually has `NOSASL` and that
nothing overrode it in your shell.

**`TSocket read 0 bytes`**
HiveServer2 closed the connection. Two quite different causes give the
identical message, so check them in this order.

*It is still starting, or is not running at all.* Much the commoner one.
Port 10000 is bound before HiveServer2 can serve a session, the
embedded Derby metastore is still initialising behind it, so `connect()`
succeeds and the first statement gets the socket closed under it. That is
why the failure reads `FAILED to run SHOW DATABASES` rather than
`FAILED to connect`. On a first `make up` against an empty volume this
window is 1-2 minutes; on a restart it is seconds. `make check` now
retries for 150s (`HIVE_CHECK_TIMEOUT` to change it), so this should
resolve itself, if it does not, confirm the container is actually up:

```bash
docker compose ps        # STATUS must be Up, not Exited
docker compose logs -f hiveserver2   # wait for 'Starting HiveServer2'
```

An `Exited (143)` container is one that was stopped, by `make down`, or
by Docker/WSL shutting down. `make up` brings it back; the warehouse
volume survives, so the database is still there.

*The transport really is being rejected.* The `apache/hive:4.0.0` image's
default `hive.server2.authentication` is `NONE`, which HiveServer2 still
speaks over SASL PLAIN, incompatible with impyla's `NOSASL` mode.
`conf/hive-site.xml` in this repo already sets
`hive.server2.authentication=NOSASL` to fix this; if the wait above times
out, confirm that file is still mounted and wasn't dropped by an
unrelated compose change:

```bash
docker exec hive-local grep -A1 authentication /opt/hive/conf/hive-site.xml
```

This one does not clear on its own, however long you wait.

**Connects fine, but every query (even `OpenSession`) resets the
connection (`ConnectionResetError` / `unexpected exception`)**
The port is open but HiveServer2 hasn't actually finished initializing
internally, or `conf/hive-site.xml` is missing properties the image
needs (this happened during initial setup when a custom `hive-site.xml`
accidentally replaced the image's defaults instead of extending them,
dropping `hive.metastore.warehouse.dir` etc.). Check `make logs` for
exceptions right after `Starting HiveServer2`, and confirm the container
didn't restart/crash (`docker ps -a`, status should be `Up`, not
`Exited`).

**Port 10000 refuses connections**
Almost always means HiveServer2 hasn't finished starting yet (see timings
above). Run `make logs` and look for `Starting HiveServer2` / listener
bind messages. If it's been more than ~3 minutes, check `docker ps` for
container health and confirm Docker has enough memory (~4GB), Hive's
Derby+Thrift services get OOM-killed silently under memory pressure and
just look like a hung startup.

**`SystemError: PY_SSIZE_T_CLEAN macro must be defined for '#' formats`**
Raised from `iprot._fast_decode` deep in an impyla `fetchall()`. This is
thrift's C accelerator (`fastbinary`) being broken on Python 3.10, it
blows up decoding a `FetchResults` response, so **any query returning more
than a handful of rows 500s while small ones pass**. Reproduced on thrift
0.16.0 (which impyla 0.20.0 hard-pins) and on 0.21.0; fixed on 0.24.0.
`requirements-dev.txt` therefore pins impyla==0.24.0 / thrift==0.24.0.
Do not downgrade impyla without re-testing a multi-row fetch,
`make check` will NOT catch this, since `SHOW DATABASES` is small enough
to pass on the broken versions.

**impyla install/import fails**
impyla's SASL transport chain is fragile on newer Python (3.12+/3.14
frequently fail to build the `sasl`/`pure-sasl` extension, or `thrift`
changes break impyla's imports). This repo's venv is pinned to Python
3.10.20 with impyla==0.24.0 / thrift==0.24.0 / thrift-sasl==0.4.3 in
`requirements-dev.txt`, use that interpreter rather than whatever
`python3` resolves to system-wide.

**`SemanticException [Error 10294]` on DELETE/UPDATE**
"Attempt to do update or delete using transaction manager that does not
support these operations." The session's transaction manager isn't ACID
capable. `conf/hive-site.xml` sets `hive.txn.manager=...DbTxnManager` and
`hive.support.concurrency=true` to fix this, confirm those are present
if you see this error.

**`SemanticException [Error 10297]` on DELETE/UPDATE, or the table shows
up as `EXTERNAL_TABLE` / `TRANSLATED_TO_EXTERNAL=TRUE` in `DESCRIBE
FORMATTED`**
"Attempt to do update or delete on table X that is not transactional."
Unlike Cloudera's Hive (CDP), vanilla Apache Hive does **not** default
managed ORC tables to `transactional=true`, and turning on
`hive.strict.managed.tables` to try to force that behavior will silently
convert non-qualifying managed tables to `EXTERNAL` instead (the opposite
of what you want) rather than erroring loudly. `sql/schema.sql` avoids
this by setting `TBLPROPERTIES ('transactional'='true')` explicitly on
every managed ORC table. Keep that property on any table you add here,
it's also what Cloudera's own `SHOW CREATE TABLE` will show, since CDP
persists it as real metadata rather than applying it invisibly.
Confirm a table is `MANAGED` (no `EXTERNAL`), `STORED AS ORC`, and check
`DESCRIBE FORMATTED <table>` for `Table Type: MANAGED_TABLE` and
`transactional=true` in Table Parameters if DELETE/UPDATE misbehaves.
