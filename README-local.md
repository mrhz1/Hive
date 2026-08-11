# Local Hive dev environment

Real HiveServer2 (Apache Hive 4.0.0) in Docker, ORC managed/transactional
tables, connected via impyla -- the same dialect and Python client used on
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
> `python scripts/migrate_columns.py --apply` instead -- see
> [Columns added after launch](DEPLOYMENT.md#columns-added-after-launch).

Expected timings:
- `make up`: container starts in seconds, but HiveServer2 itself isn't
  ready for ~60-120s while Derby initializes. Port 10000 is bound before
  it can serve a session, so a check inside that window sees
  `TSocket read 0 bytes` rather than a connection refusal. `make check`
  waits it out (150s; `HIVE_CHECK_TIMEOUT` to change), so a failure from
  it means something really is wrong -- see Troubleshooting.
- `make init` / `make verify`: each Hive query (including single-row
  INSERT) can take a few seconds due to query planning overhead -- this is
  normal Hive behavior, not a local misconfiguration.

## Day to day

- `make logs` -- tail the HiveServer2 container logs.
- `make down` -- stop the container (named volume `hive-warehouse`
  persists your data across restarts; `docker volume rm` it to reset).

## The API

Interactive docs at `http://localhost:8100/docs` once `make run` is up.

### Tables

| table | notes |
|---|---|
| `roles` | `id`, `name`, `permissions ARRAY<STRING>` |
| `users` | `role_id` FK to roles; reads join in `role_name` + `permissions` |
| `patient` | singular, matching the Cloudera metastore. `fstname`/`lstname` + provider (`p*`) and patient (`pt*`) contact blocks, `dt_reg`/`dt_b`/`dt_d` DATEs; no role, and no lifecycle columns — record data only |
| `patient_application_files` | one row per uploaded document, keyed on `application_id` — documents belong to a submission, not to a patient directly. Bytes live under `FILE_STORAGE_DIR`; the row carries the de-identification state. No per-file review verdict: that is recorded once, on the application |
| `file_metadata` | one row per file, holding the metadata the document **arrived carrying** (PDF info dict / DICOM tags / Word core properties), extracted at upload, as JSON-in-STRING. Schemaless on purpose — a DICOM study and a Word document share almost no fields. Facts this system generates afterwards are deliberately **not** here; see [Metadata](#metadata) |
| `patient_applications` | one submission of a patient + their documents for review; holds who did what and when, and `assigned_to_id` -- the user set to work on it, who is emailed about its uploads |
| `audit_logs` | append-only; `user_id` names the acting caller; `old_values`/`new_values` are JSON-in-STRING |

### Endpoints

`/users`, `/patients`, `/roles`, `/applications` each expose POST / GET
(list) / GET `{id}` / PUT `{id}` / DELETE `{id}`. `/logs` exposes POST /
GET (list, filterable by `entity_type`, `entity_id`, `limit`) / GET
`{id}` -- no update or delete, because an audit trail you can rewrite is
not an audit trail.

`/applications` accepts a `patient_id` query parameter to scope the list
to one patient.

Documents hang off an **application**, not a patient:
`/applications/{id}/files` (POST multipart / GET), and per file
`/files/{id}` (GET / PUT / DELETE), `/files/{id}/content` (GET,
`?deidentified=true` for the redacted copy), `/files/{id}/deidentify`
(POST) and `/files/{id}/metadata` (GET -- what was extracted from the
document at upload time).

`/applications/{id}/files/background` (POST multipart) is the same upload
without the wait: it stages the bytes, answers 202 with an upload job,
and moves, records and parses the files afterwards.
`/upload-jobs/{id}` (GET) reports progress, and the user in the
application's `assigned_to_id` is emailed when the batch ends -- whether
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

The 20 grants are the product of five models -- `user`, `patient`,
`role`, `log`, `application` -- and four actions: `view`, `create`,
`update`, `delete`. Both tuples live in `app/security.py`, and
`scripts/init_db.py`, the test fixtures and the frontend's
`schemas/common.ts` all derive from them rather than restating the list.

**The app authenticates nobody.** `REMOTE-USER` is the username the
platform already authenticated (Kerberos/Knox on Cloudera AI) and passed
down; locally you set it by hand. Swapping the source means changing only
`_current_username` in `app/security.py` -- routes and permission strings
are unchanged, so nothing branches on environment.

`make init` seeds two roles: **admin** (all 20 permissions) and **viewer**
(read-only), with usernames to match. Use those as `REMOTE-USER`:

```bash
curl -H "REMOTE-USER: admin" http://localhost:8100/users
```

### Audit logging

Writes to users and patients record a CREATE/UPDATE/DELETE entry.
Convention: CREATE has `old_values` null, DELETE has `new_values` null,
UPDATE has both. Roles are **not** audited (not requested -- say the word
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
records `failed` with the reason — which is what it did before, so the
degradation is to the old behaviour rather than to an error.

**What this system works out afterwards** — that a file was
de-identified, when, by what method, for which patient — is written into
the **output file's own metadata** by `app/embed.py`, never into the
table. Mixing the two made a row that was half read-out and half
written-in, indistinguishable once stored.

| format | where the facts land |
|---|---|
| PDF | info dict, replaced wholesale, facts in `keywords`; XMP dropped |
| DICOM | `PatientIdentityRemoved`, and appended to `DeidentificationMethod` (LO, VM 1-n) |
| Word | core properties, facts in `comments` |

The PDF case is a replace rather than a merge for a reason:
`OCR/deid/pdf_io.py` redacts page content but never touches the info
dictionary, so a redacted PDF still carried the original author, title
and creation date. (The DICOM and Word halves of the pipeline already
scrub their own.)

### File types

Everything downstream keys off the extension — whether a file can be
de-identified, whether its metadata is read, which `DEID_*_DIR` its
redacted copy is filed under. A name is only a claim, and PACS exports
routinely have none at all (`IM000001`), so `app/filetype.py` resolves
the type from the bytes when the name does not already name a format we
handle:

- DICOM — `DICM` at offset 128 (or 0, for preamble-less writers)
- PDF — `%PDF-`
- `.docx` — zip signature with a `word/` entry
- `.doc` — the OLE2 signature

A name that *does* name a handled format wins, because it carries the
`.dcm`/`.dicom` and `.doc`/`.docx` distinctions the magic numbers cannot.
A file that is neither recognised nor named keeps whatever its name
claimed — an unknown format stays unknown rather than being guessed into
the wrong pipeline.

### Email

`app/mailer.py` talks to an SMTP relay -- plain, port 25, no credentials,
which is what Cloudera gives a workload on the cluster network. Set
`SMTP_HOST` to switch it on; leave it unset and every send becomes a
logged no-op, so nothing here needs a mail server locally. See
`.env.example` for the rest (`SMTP_FROM`, and the `SMTP_STARTTLS` /
`SMTP_USER` pair for pointing at a real provider).

Nothing raises on a failed send. An upload that succeeded must not be
reported as failed because a mail server was down, so `send_email`
returns a bool and logs `email_send_failed`.

Currently the only notifications are upload outcomes, from
`app/notifications.py`: the user in the application's `assigned_to_id`
hears when a background batch finishes, and hears with the failing file
names when it does not. An unassigned application falls back to whoever
started the upload -- a batch failing silently is worse than one email to
a roughly-right inbox.

### Background uploads

`POST /applications/{id}/files` writes, inserts and parses every file
before it answers, which is a long time to hold a request open for a
folder of scans. `/files/background` splits that: the request stages the
bytes under `FILE_STORAGE_DIR/.uploads/<job id>/` and answers 202, then a
`BackgroundTask` moves each file into place (a rename -- staging and
storage share a filesystem), inserts its row, extracts its metadata, and
emails the assignee.

One bad file does not cost the batch: it is marked `failed` on the job
with its error and the rest carry on, which is what `partial` means on an
upload job. Nothing is half-recorded either way -- a file that never
moved has no row.

Job state is in-process, like the de-identification dispatcher's. It is
progress for the UI to poll, not a record: the files and their rows are
the record. A restart mid-batch loses the progress bar, not the
documents, and `/upload-jobs/{id}` then 404s.

### Logging / tracing

structlog with `contextvars`, so one `request_id` threads through the
whole transaction -- including the background audit write, which re-binds
it explicitly. Grep a single id to see a request end to end:

```
request_started    method=POST path=/users request_id=4c0e60a7...
user_created       request_id=4c0e60a7... user_id=51963c2c...
request_finished   duration_ms=1393.15 status_code=201 request_id=4c0e60a7...
audit_recorded     action=CREATE entity_type=user request_id=4c0e60a7...
```

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
production -- application code should never branch on environment; it just
reads these vars. `.env.example` is the committed template; `.env.local`
is gitignored.

`conf/hive-site.xml` is mounted into the container via `HIVE_CUSTOM_CONF_DIR`
and overrides the `apache/hive:4.0.0` image's defaults to match what
Cloudera AI's HiveServer2 already has configured: NOSASL auth, and a real
transaction manager (`hive.txn.manager` / `hive.support.concurrency`) so
DELETE/UPDATE work. The image's `HIVE_CUSTOM_CONF_DIR` mechanism replaces
`hive-site.xml` wholesale (it symlinks by filename, it doesn't merge), so
this file also carries forward the image's own default properties
(warehouse dir, Tez local-mode settings, etc.) -- if you add more overrides,
add them to this file rather than a second one, and don't drop the
existing properties.

## Troubleshooting

**`SASL(-1): generic failure` / auth negotiation errors from impyla**
This almost always means an auth mechanism mismatch. Locally we use
`HIVE_AUTH=NOSASL` because the dev HiveServer2 has no Kerberos. On
Cloudera AI, `HIVE_AUTH` is `GSSAPI` (Kerberos) instead -- don't hardcode
either value in code; always read `HIVE_AUTH` from the environment. If you
see this error locally, check `.env.local` actually has `NOSASL` and that
nothing overrode it in your shell.

**`TSocket read 0 bytes`**
HiveServer2 closed the connection. Two quite different causes give the
identical message, so check them in this order.

*It is still starting, or is not running at all.* Much the commoner one.
Port 10000 is bound before HiveServer2 can serve a session -- the
embedded Derby metastore is still initialising behind it -- so `connect()`
succeeds and the first statement gets the socket closed under it. That is
why the failure reads `FAILED to run SHOW DATABASES` rather than
`FAILED to connect`. On a first `make up` against an empty volume this
window is 1-2 minutes; on a restart it is seconds. `make check` now
retries for 150s (`HIVE_CHECK_TIMEOUT` to change it), so this should
resolve itself -- if it does not, confirm the container is actually up:

```bash
docker compose ps        # STATUS must be Up, not Exited
docker compose logs -f hiveserver2   # wait for 'Starting HiveServer2'
```

An `Exited (143)` container is one that was stopped -- by `make down`, or
by Docker/WSL shutting down. `make up` brings it back; the warehouse
volume survives, so the database is still there.

*The transport really is being rejected.* The `apache/hive:4.0.0` image's
default `hive.server2.authentication` is `NONE`, which HiveServer2 still
speaks over SASL PLAIN -- incompatible with impyla's `NOSASL` mode.
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
didn't restart/crash (`docker ps -a` -- status should be `Up`, not
`Exited`).

**Port 10000 refuses connections**
Almost always means HiveServer2 hasn't finished starting yet (see timings
above). Run `make logs` and look for `Starting HiveServer2` / listener
bind messages. If it's been more than ~3 minutes, check `docker ps` for
container health and confirm Docker has enough memory (~4GB) -- Hive's
Derby+Thrift services get OOM-killed silently under memory pressure and
just look like a hung startup.

**`SystemError: PY_SSIZE_T_CLEAN macro must be defined for '#' formats`**
Raised from `iprot._fast_decode` deep in an impyla `fetchall()`. This is
thrift's C accelerator (`fastbinary`) being broken on Python 3.10 -- it
blows up decoding a `FetchResults` response, so **any query returning more
than a handful of rows 500s while small ones pass**. Reproduced on thrift
0.16.0 (which impyla 0.20.0 hard-pins) and on 0.21.0; fixed on 0.24.0.
`requirements-dev.txt` therefore pins impyla==0.24.0 / thrift==0.24.0.
Do not downgrade impyla without re-testing a multi-row fetch --
`make check` will NOT catch this, since `SHOW DATABASES` is small enough
to pass on the broken versions.

**impyla install/import fails**
impyla's SASL transport chain is fragile on newer Python (3.12+/3.14
frequently fail to build the `sasl`/`pure-sasl` extension, or `thrift`
changes break impyla's imports). This repo's venv is pinned to Python
3.10.20 with impyla==0.24.0 / thrift==0.24.0 / thrift-sasl==0.4.3 in
`requirements-dev.txt` -- use that interpreter rather than whatever
`python3` resolves to system-wide.

**`SemanticException [Error 10294]` on DELETE/UPDATE**
"Attempt to do update or delete using transaction manager that does not
support these operations." The session's transaction manager isn't ACID
capable. `conf/hive-site.xml` sets `hive.txn.manager=...DbTxnManager` and
`hive.support.concurrency=true` to fix this -- confirm those are present
if you see this error.

**`SemanticException [Error 10297]` on DELETE/UPDATE, or the table shows
up as `EXTERNAL_TABLE` / `TRANSLATED_TO_EXTERNAL=TRUE` in `DESCRIBE
FORMATTED`**
"Attempt to do update or delete on table X that is not transactional."
Unlike Cloudera's Hive (CDP), vanilla Apache Hive does **not** default
managed ORC tables to `transactional=true` -- and turning on
`hive.strict.managed.tables` to try to force that behavior will silently
convert non-qualifying managed tables to `EXTERNAL` instead (the opposite
of what you want) rather than erroring loudly. `sql/schema.sql` avoids
this by setting `TBLPROPERTIES ('transactional'='true')` explicitly on
every managed ORC table. Keep that property on any table you add here --
it's also what Cloudera's own `SHOW CREATE TABLE` will show, since CDP
persists it as real metadata rather than applying it invisibly.
Confirm a table is `MANAGED` (no `EXTERNAL`), `STORED AS ORC`, and check
`DESCRIBE FORMATTED <table>` for `Table Type: MANAGED_TABLE` and
`transactional=true` in Table Parameters if DELETE/UPDATE misbehaves.
