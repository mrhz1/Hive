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
| `patient` | singular, matching the Cloudera metastore. `id` is the **patient code off the documents**, supplied not generated — see [Patient codes](#patient-codes). `fstname`/`lstname` + provider (`p*`) and patient (`pt*`) contact blocks, `dt_reg`/`dt_b`/`dt_d` DATEs; no role, and no lifecycle columns — record data only |
| `patient_application_files` | one row per uploaded document, keyed on `application_id` — documents belong to a submission, not to a patient directly. Bytes live under `FILE_STORAGE_DIR`; the row carries the de-identification state. No per-file review verdict: that is recorded once, on the application |
| `file_metadata` | one row per file, holding the metadata the document **arrived carrying** (PDF info dict / DICOM tags / Word core properties), extracted at upload, as JSON-in-STRING. Schemaless on purpose — a DICOM study and a Word document share almost no fields. Facts this system generates afterwards are deliberately **not** here; see [Metadata](#metadata) |
| `patient_applications` | one submission of a patient + their documents for review; holds who did what and when, and `assigned_to_id` -- the user set to work on it, who is emailed about its uploads |
| `audit_logs` | append-only; `user_id` names the acting caller; `old_values`/`new_values` are JSON-in-STRING |
| `intake_files` | one row per file found in a dropped batch, **including the ones we refuse** — a file nobody can place has to be visible and fixable. Also the only record of which original produced which redacted copy; see [Intake](#intake-the-drop-folder) |
| `intake_batches` | one sweep of the drop folder. Counts are derived, not stored |

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

**De-identification is no longer started from an application.** Documents
are redacted in intake, before they can be picked (see
[Intake](#intake-the-drop-folder)), so the application page offers no
*De-identify* or *De-identify all* control. The endpoints
`/files/{id}/deidentify` and `/applications/{id}/files/deidentify-all` are
kept, unreachable from the UI, as an escape hatch for re-running a single
redaction found wanting at review; a bad redaction is otherwise fixed from
the Rejections page by attaching a better copy.

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
| PDF | appended to `keywords`; XMP dropped |
| DICOM | `PatientIdentityRemoved`, and appended to `DeidentificationMethod` (LO, VM 1-n) |
| Word | appended to `comments` |

These are **added, not substituted**. The de-identified file keeps its
own metadata — de-identified in place by the pipeline, so `Author:
<PERSON>` rather than no author — and overwriting that would throw away
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
transfer syntax work — the client would otherwise need a WASM DICOM
codec. Frames are windowed through the VOI LUT when the study carries
one, and MONOCHROME1 is inverted so it is not shown as a negative.

The Word preview returns **structure, not HTML**: it is somebody's
uploaded document, and handing the browser markup out of it invites the
obvious injection. The client renders those strings as text nodes.
Legacy `.doc` cannot be previewed (python-docx reads only the 2007+
format) and says so rather than failing blankly.

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

### Intake: the drop folder

Documents arrive by being **put in a folder**, not uploaded through the
application. Everything under `INTAKE_DIR` is swept, matched to a patient
code, and de-identified without anybody opening the dashboard; the
application then picks from what came out.

```
storage/incoming_data/A/B/C/AA1234/image.dcm
storage/incoming_data/de_identified/A/B/C/AA1234/AA1234_<date>_<serial>.dcm
```

The mirror lives **inside** the intake root and reproduces the tree exactly,
so one folder holds a batch and its redacted twin.

To run the steps by hand -- or to see what a sweep *would* do before trusting
it -- there are separate commands:

```bash
make intake                                  # what would happen
make intake-apply                            # record it in Hive
python scripts/intake_sweep.py --root /some/drop --settle-seconds 0
```

Dry by default, because the sweep is deciding which patient a document
belongs to and that judgement is worth reading before it is trusted.

#### Starting by itself

`scripts/intake_run.py` (`app/intake_run.py`) is what makes the drop folder
work unattended. It is meant to be called often, and most calls find nothing
to do. The work starts only once a push has **finished landing**:

- **the sender says so** — a `batch.done` file (`INTAKE_BATCH_MARKER`)
  anywhere in the tree starts it immediately; or
- **the folder goes quiet** — nothing in it has changed for
  `INTAKE_SETTLE_SECONDS`, which is what the end of a copy looks like from
  outside.

Then it sweeps and redacts in one go. A push still in progress is left alone
entirely: taking a half-copied folder would record the files that had
arrived and leave the rest for a later batch, splitting one delivery in two.

```bash
make intake-run      # check once -- what a scheduled Job runs
make intake-watch    # check every minute, for as long as it runs
```

**"Changed" means mtime *or* ctime.** `cp -p` and `rsync -t` carry the
source's modification time over, so a file copied a second ago can claim to
be weeks old. The change time is set by the filesystem on every write and
rename and no copy tool can set it, so the later of the two is the truth.
Hidden files are skipped for the same reason: rsync writes
`.image.dcm.Xy12Ab` and renames it when done, and recording that would report
a skipped "unsupported format" for every file of a push caught mid-flight.

**Never two at once.** A run holds an OS file lock
(`<INTAKE_DIR>/.intake/run.lock`); one that finds it held exits straight away
(`busy`). A thousand files take hours, so runs *will* overlap their
schedule. The lock dies with its process, so a crashed run leaves nothing to
clear by hand.

A spent `batch.done` is deleted once its push has been swept — left in place,
the next push into the same folder would be taken as finished the moment its
first file appeared. A queue left behind by an interrupted run is drained by
the next one even if nothing new has arrived.

##### Scheduling it on Cloudera AI

Create a **Job**:

| | |
|---|---|
| Script | `scripts/intake_run.py` |
| Schedule | every minute (cron `* * * * *`) |
| Resources | as sized for the workers — see [Sizing the pool](#sizing-the-pool) |
| Environment | `INTAKE_DIR`, `SUBMITTED_DIR`, `DEID_WORKERS`, `DEID_WORKER_CPU_THREADS`, `INTAKE_SETTLE_SECONDS`, plus the Hive variables |

Every minute is fine: a run that finds nothing costs one walk of the folder,
and one that finds a run already working leaves immediately. The Job needs
`INTAKE_DIR` on the same mounted volume the sender writes to and the API
reads from.

If the sending side can write `batch.done` when a push completes, ask it to:
that starts redaction the moment the copy ends, where the quiet window has
to wait `INTAKE_SETTLE_SECONDS` to be sure.

#### Four outcomes, all of them recorded

| outcome | meaning |
|---|---|
| **queued** | one agreed code, a format we handle — ready to redact |
| **skipped** | unsupported format, or no code found |
| **conflict** | the path and the file name name different patients |
| **superseded** | a refusal that has since come back corrected |

A refused file is a **row**, not a log line. "1,000 files arrived, 3 need
attention" and "997 files arrived" are different reports, and only the first
one gets those three files fixed.

#### Finding the code

`app/intake.py`, using the same `is_patient_code` the patient records use —
one definition of what a code is, rather than two that drift.

- **A folder** claims a code when a whole segment is one; the **deepest**
  wins. `A/B/C/AA1234/x.dcm` claims AA1234, `A/B/C/x.dcm` claims nothing,
  and `AA1234-exported/` claims nothing either.
- **A name** claims a code at its start, ending on a non-alphanumeric
  boundary: `AA1234.pdf`, `AA1234_chest.pdf` and `AA1234()_-chest.pdf` all
  claim AA1234. The boundary is load-bearing — without it `AVDD12005_x.pdf`
  would be carved down to the real-looking `AVDD1200` and filed under a
  patient who has nothing to do with it. A code buried mid-name
  (`chest_AA1234.pdf`) is a description, not a claim.
- **The type comes from the bytes** where the name does not say
  (`app/filetype.py`), because a PACS export is routinely `IM000001` with no
  extension at all.

**A disagreement is never resolved automatically.** A file in AA1234's
folder named for BB5678 means somebody dropped it in the wrong place; either
choice files a document under a patient it may not belong to, and redaction
now happens before any human looks. So it waits in the conflict list, and
`intake.resolve_conflict` accepts **only** one of the two codes the file
actually claimed — otherwise that list would become a way to file a document
under any patient at all.

#### Half-copied files

A sweep that takes a file the moment it appears will redact half of a 400MB
study — and report success, because half a study is a readable file. So a
file counts as arrived only once it has sat untouched for
`INTAKE_SETTLE_SECONDS`. If the sending side can write an
`INTAKE_BATCH_MARKER` when it finishes, that is better than any amount of
waiting.

#### Pushing the same folder again

The correction loop is: fix the file names at source, push the whole folder
back. So a second sweep has to leave the work already done alone while
taking the corrections — and the dedupe key is what decides whether it does.

**Bytes and absolute path, not bytes alone.** Three cases forced that:

- Adding a code to a file name **changes no bytes**. Keyed on content
  alone, the sweep would reject exactly the correction it exists to accept,
  and the file would stay skipped for ever.
- The same document in two patients' folders is **two filings**. Keyed on
  content alone, only the first is ever redacted and the second patient's
  copy silently never appears.
- A relative path **repeats across roots**, so it cannot identify a file
  either.

Identical bytes at an identical path are the same file arriving again, and
keep the row they have — which also stops a sweep on a timer breeding a
fresh row for every unfixed file, every run. When a refusal does come back
fixed, the old row is marked `superseded` and says what replaced it, so it
leaves the list somebody is working through without being deleted.

#### Redacting the queue

`scripts/intake_deid.py` (`make intake-deid`) drains what the sweep queued.
It reads the queue, not the folder.

```bash
make intake-deid                            # one at a time
python scripts/intake_deid.py --workers 4   # four at once
python scripts/intake_deid.py --limit 1     # one file, to try it
```

Each file goes in on its own and comes out in the mirror, renamed to
`<CODE>_<date>_<serial>`, with the original left exactly where it was. A
run's three outputs — the copy, the extracted text and the report — are
renamed together, because they are found as a set.

Nothing here touches an application or a patient record: a patient does not
exist yet, so this is file-in, file-out with the intake row as its only
bookkeeping.

**One thread claims, N threads run.** Hive cannot claim a row atomically, so
four workers each asking for "the oldest queued file" are handed the same
one four times. The claimer marks a row `processing` before passing it on,
which is what keeps a second worker off it — serialise the claim,
parallelise the wait.

A bad document costs only itself: the row is marked `failed` with the reason
and the batch carries on. A file that has vanished since the sweep, a
pipeline crash, an error nobody predicted — all three land as `failed`
rather than leaving a row stuck at `processing` for ever.

#### Sizing the pool

**The ceiling is memory, not cores.** A worker killed for running out of it
(exit -9) produces nothing at all, so `DEID_WORKERS` wants setting against a
measured peak RSS:

```
N = min(cores / cores_per_worker, RAM / RAM_per_worker)
```

`DEID_WORKER_CPU_THREADS` is injected per subprocess, because
`OCR_CPU_THREADS` defaults to 8 — right for one worker, four times the
machine for four of them. It caps `OMP_NUM_THREADS` and `MKL_NUM_THREADS`
too, or the NLP stage's libraries take every core anyway and undo the
budget.

`DEID_WORKER_MEMORY_GB` is **advisory**: a process cannot cap its own
memory, that is the container's job. It is used to refuse to start more
workers than the machine can hold, which is the part that is enforceable
here — eight workers on a box with room for two do not run four times
faster, they get killed mid-document and leave files marked failed for a
reason that has nothing to do with the file.

Worth the arithmetic before turning it up. Measured on this pipeline:
**19–31 seconds per page on a 4-core job**. A ten-page document is about
four minutes; a thousand of them is around 67 hours in one lane.

#### The Intake page

`/intake` in the dashboard, gated on `application:view`
(`frontend/src/routes/intake/index.tsx`, API in `app/routers/intake.py`).
Five tiles that double as filters — Conflicts, Skipped, Failed, Waiting,
De-identified — refreshed every 15 seconds, since redaction runs out of
process and this is where a batch is watched going through.

- **Skipped** and **Failed** list the **full source path** with the reason,
  and *Copy list* puts them on the clipboard one per line
  (`path<TAB>reason<TAB>detail`) — the thing to send whoever owns the source,
  so they can fix and re-push.
- **Conflicts** show both claims and offer exactly those two codes as
  buttons. Choosing one needs `application:update`, only accepts a code the
  file actually claimed, and is **audited** (`entity_type=intake_file`, both
  claims in `old_values`): it is a decision about whose document this is.

| endpoint | |
|---|---|
| `GET /intake/counts` | the tally, derived from the rows |
| `GET /intake/files?status=` | one status's files; an unknown status is a 422 |
| `GET /intake/batches` | sweeps, newest first |
| `POST /intake/files/{id}/resolve` `{"code": ...}` | settle a conflict; the file goes back to `queued` |

#### Putting an application together

A new application starts from a **patient code**, not a patient form
(`IntakeCodePicker`). Only codes with redacted files nobody has attached are
offered (`GET /intake/codes`). If a patient already has that code it is
selected; if not, the form opens with the code filled in and locked, and the
patient is created *with* it. The application's source folder is the code's
folder in the drop tree, filled in rather than typed.

The code is shown large on purpose: a mistyped code upstream (`AA1235` for
`AA1234`) is still a valid code, and this is the first place a person can
notice.

Step 2 lists that code's de-identified documents grouped by folder
(`IntakeFilePicker`) — take a whole folder or single files.
`POST /applications/{id}/intake-files` attaches them:

- **One row, both copies.** `file_path` is the original in the drop tree,
  `de_identified_file_path` its redacted twin in the mirror, `deid_status`
  already `done`. Nothing is copied; both stay where they are until the
  application is submitted, so an abandoned draft strands nothing.
- **The drop folder is a storage root** (`storage.intake_root`) for that
  reason — otherwise every read of an attached file is refused and logged as
  a traversal attempt.
- **The code must match.** A file carrying `BB0042` cannot go on `AA1234`'s
  application: the code on the document is the only evidence of whose it
  is, and a click must not override it.
- **All or nothing.** Every file is checked before any is attached.
- **Claimed.** The intake row goes to `claimed` with the application file's
  id, so no second application can take it.

**Taking a file back off does not delete it.** Removing an intake document
from a draft, or deleting the whole application, hands it back to the pool
(`intake.release_claim`) with both copies intact. Before this, removing a
file from an application deleted both copies from disk — right for an
uploaded file, destructive for one that belongs to the drop folder.

`frontend/e2e/intake.spec.ts` walks this in a browser. It needs real
de-identified files, which only a real sweep and OCR run produce, so it
skips unless `E2E_INTAKE_CODE` names a code that has some.

#### Submitting

Submission files both copies under the patient, side by side
(`app/submission.py`):

```
storage/submitted/AA1234/original/image.dcm
storage/submitted/AA1234/de_identified/AA1234_20260924_1790261077741000.dcm
```

- **Both move**, and the row is pointed at both new paths in one write, so
  there is no moment at which it names a file that has already gone. The
  path setter is `crud.set_paths`, deliberately not part of
  `PatientApplicationFileUpdate` — that is what `PUT /files/{id}` accepts,
  and a path a client can set is a path a client can aim anywhere.
- **Names never collide.** `image.dcm` from two series becomes `image.dcm`
  and `image_2.dcm`; the second does not silently replace the first.
- **The run's text and report are removed**, wherever the run left them —
  beside the copy in the mirror for an intake file, in
  `<original>/deidentified/` for an uploaded one.
- **The drop tree empties itself.** Folders left empty on both sides are
  pruned; other patients' files in the same tree are untouched.
- **The intake row goes to `submitted`, not back to the pool.** Its files
  have left the drop tree, so releasing it would offer files that are not
  where it says. It also keeps the row as the record of where the document
  *arrived* — which is what makes a re-pushed folder a duplicate rather than
  new work.
- `DEID_KEEP_ORIGINAL=false` still discards the original instead of filing
  it; the row keeps its old path (the column is required, and whatever
  reads it checks the disk first).

The sweep **never walks `SUBMITTED_DIR`**, wherever it is configured: nested
inside the drop folder, it would take every submitted original — and every
already-redacted copy — as a fresh arrival and redact it again.

`DEID_PDF_DIR` / `DEID_DICOM_DIR` / `DEID_WORD_DIR` are no longer where
submission files anything. The Files library's manual upload of an
already-redacted document still writes there.

#### At millions of files

Built for pushes of five million files and more, on Hive alone. Everything
below is shaped by one fact about Hive: **a statement costs ~0.4-1 s whether
it touches one row or a thousand**. So nothing happens a row at a time.

| | How | Why |
|---|---|---|
| **Redaction** | a *chunk* of files per pipeline run (`DEID_CHUNK_DICOM`, `DEID_CHUNK_DOCUMENTS`) | the models load once per run. Measured on DICOMs: 1.07 s each in runs of 40, ~7.5 s each one at a time |
| **Recording arrivals** | 500 rows per `INSERT` | 80 days of single inserts becomes about an hour |
| **Claiming work** | a chunk per claim: one `SELECT`, one `UPDATE ... IN` | the old one-at-a-time claimer capped the whole system at ~35,000 files/day |
| **Recording outcomes** | one `UPDATE ... CASE` per chunk | per-row values in a single statement |
| **Counting** | `GROUP BY`, cached 10 s | loading rows to count them stops the page loading at all |
| **Watching for arrivals** | only folders whose time changed; the mirror is never walked; a full look once a day | re-listing millions of files every minute |
| **Lists** | paged; the whole list downloads as CSV | a hundred thousand rows in one response hangs the browser |

##### Several machines: shards

Each row belongs to one of 256 shards by the first two characters of its id.
A process owns a set of them and claims only inside it, so processes on
different machines can never take the same file -- no lock across machines
is needed, which is fortunate, because a file lock on shared storage is not
one you can rely on.

```bash
python scripts/intake_run.py --watch --shards 0-3  --of 12   # machine 1
python scripts/intake_run.py --watch --shards 4-7  --of 12   # machine 2
python scripts/intake_run.py --watch --shards 8-11 --of 12   # machine 3
```

Every shard `0..of-1` must be run by exactly one process; the one holding
shard 0 also sweeps. On Cloudera, that is one Job per line above.

##### Stopping and continuing

Every outcome is appended to a local journal (`.intake/journal/`) the moment
it is known, then published to Hive with the rest of its chunk. A worker
killed in between loses nothing: on the next start, finished work is
published from the journal rather than done again, and only what was
genuinely half-done goes back in the queue -- for that process's own shards
only. Stop it, restart it, move it to another machine: it continues from
where it was.

##### Watching it

The Intake page shows files processed out of the total, speed, time left,
each worker (live, idle or **stopped**, what it is on, how fast), and each
push's own progress. Speed and liveness come from heartbeat files the
workers write every few seconds (`.intake/workers/`), so they are live
without asking Hive. If files are waiting and no worker has reported for
`INTAKE_HEARTBEAT_STALE_SECONDS`, a red banner says so.

##### DICOM: pixels only when there is something to black out

Pixels are written back only when identifying text was found in them.
An image with no text -- or only an orientation marker or a measurement --
keeps its pixels **byte-for-byte**, and has its metadata de-identified. Each
file's intake row records which way it went (`detail`): `pixels and tags`,
`tags only: no text in the image`, or `tags only: text in the image,
nothing identifying`.

#### What this table is also for

`intake_files` is the only thing that remembers **which original produced
which redacted copy**. Renaming the output to the patient-code scheme breaks
the link on disk (`image.dcm` and `AA1234_20260924_179….dcm` share no name),
and at redaction time there is no `patient_application_files` row to hold
both paths yet.

Counts are deliberately not stored on `intake_batches`: they are a `GROUP BY`
away, and a Hive `UPDATE` per file to keep a counter honest costs more than
the query ever will.

### Patient codes

A patient id **is** the code its documents carry. It is not generated: the
sending system writes it into the file path or the file name, the same code
means the same person everywhere, and `POST /patients` takes it as `id`
rather than allocating one. Two to four letters then three or four digits —
`AA0001`, `AA1200`, `AVDD001`, `AVDD1200` — matched case-insensitively,
stored upper-case, and settable with `PATIENT_CODE_PATTERN`.

`app/ids.py` holds the pattern and `is_patient_code` / `normalise_patient_code`;
the same pair is what the intake sweep uses to find a code in a path, so
there is one definition of what a code is rather than two that drift.

**The pattern is load-bearing, not cosmetic.** Nothing can check a candidate
against the `patient` table — patients do not exist until their files have
been redacted — so the shape is the only evidence that a string is a code.
The previous scheme (six random characters from `A-Z0-9`) would have
accepted `REPORT`, `SCAN01` and `IMAGE1` as codes and filed documents under
them as though they were people, silently. Two-to-four letters then
three-to-four digits rejects all three.

What it cannot catch is a **typo that is still a valid code**: `AA1235` for
`AA1234` passes, and creates a patient who should not exist. Redaction
happens before any human looks, so the first person who can notice is
whoever picks the files for an application — which is why the code is shown
prominently there.

Uniqueness is a pre-check `SELECT`, like every other uniqueness rule here
(Hive has no constraints), so two concurrent creates of one code can both
pass. That mattered less when ids were random; it matters more now that
they arrive from outside. A duplicate code is a 409.

### Document names

An uploaded document is stored as
`<patient code>-<type>-<date>-<16-digit serial>.<ext>` --
`app/storage.py::document_name`, with the serial from `app/ids.py`
(milliseconds plus a per-millisecond sequence, so it is unique and sorts
by arrival).

A **de-identified** copy is named
`<patient code>_<de-id date>-<16-digit serial>.<ext>` —
`AA1234_20260924_1790261077741000.pdf`. The date and the serial are the
*redaction run's* own, not the original upload's
(`app/deid.py::deid_output_name`). Reading the name tells you when the
redacted copy was made, and a re-run is plainly a new document rather than
the old one wearing the same name.

Every redacted file in the system reads this way — the intake sweep, the
wizard's manual attach and a `/files-library` upload all go through the
same function, so one name shape means one thing. There is no `_deid`
marker and no document type in it: the copy is identified by living in a
de-identified folder, the extension already carries the type, and the code
is what has to be read off the page in a hurry. `deid_artifacts` finds a
run's sidecars by the recorded name rather than by that suffix, so nothing
depended on it.

The OCR pipeline cannot know that name: it writes its three outputs (the
copy, the extracted text, the report) named after the file it read. So
`_rename_run_outputs` renames the set once the run succeeds -- all three
together, because `deid_artifacts` finds them by their shared stem. That
is also why cleanup now passes the recorded `deidentified_file_name` in:
the source-derived prefix no longer matches it, though that prefix is
still tried, for rows written before this and for a run that died before
it could record anything.

Both manual paths -- the wizard's *attach a de-identified document* and a
`/files-library` upload -- call the same `deid_output_name`, so every
redacted file in the system reads the same way.

### Both copies, and how they stay paired

Submission keeps the identified original by default
(`DEID_KEEP_ORIGINAL`, `app/submission.py`), filing it in the patient's
`original/` folder beside the redacted copy — see [Submitting](#submitting).
Turning the flag off deletes it instead.

**The pairing is the row, not the file names.** One
`patient_application_files` row holds both `file_path` and
`de_identified_file_path`, so one file id reaches either copy --
`/files/{id}/content` serves the original, `?deidentified=true` the
redacted one, and the preview endpoints mirror the same way. Do not try
to pair them by name: the redacted copy carries the *redaction run's* own
date and serial, deliberately (see above), so the two names never match.

The viewer flips between the two in place rather than being closed and
reopened -- the toggle in `FileViewerModal` switches sides on one file
id, and only appears when a redacted copy exists. A locked (already
submitted) application does not offer it, which preserves what the review
panel did before originals survived submission: it never offered *View
original* there. Now that the bytes are still on disk, whether a reviewer
of a submitted application may see them is a policy question rather than
a technical one.

The run's own leftovers -- the extracted text and the redaction report --
are removed at submission either way. Nothing points at them once the
redacted copy has been moved out from under them, and the report is the
one artifact that can hold the identifiers in the clear
(`DEID_REPORT_INCLUDE_VALUES`).

Two consequences of keeping originals, neither of them handled for you:

- The identified pile under `FILE_STORAGE_DIR` now grows without bound.
  It needs a purge policy with an owner; there isn't one yet.
- Every read of an original is a real disclosure. `access_logs.identified`
  is what separates those from routine work, and it matters more now that
  both copies live side by side for good -- see [The two trails](#the-two-trails).

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

The notifications live in `app/notifications.py`. Every one of them goes
to the user in the application's `assigned_to_id`, falling back to whoever
created the application -- a run finishing silently is worse than one
email to a roughly-right inbox:

- an application being assigned to someone
- a background upload batch finishing, with the failing file names when it
  did not
- de-identification finishing, with the documents that could not be
  redacted

### One de-identification email per application

De-identification is triggered per file and each run is independent, so
there is no batch record to hang a "finished" email off. `app/deid_notices.py`
reads it off the rows instead: after every run settles, it asks whether any
file on that application is still `queued` or `processing`, and only the run
that finds none sends the notice. Ten files sent through
`/deidentify-all` therefore produce one email, not ten. (That endpoint is
now an escape hatch only -- see [Endpoints](#endpoints). Intake redaction
does not send per-application notices: there is no application yet.)

Two runs finishing in the same instant would both see an idle table, so a
marker under `FILE_STORAGE_DIR/.deid-notices/<application id>.json` holds
the outcome that was last announced. A second notice describing the same
outcome within `DEID_NOTICE_REPEAT_SECONDS` (default 120) is dropped; a
genuine re-run later, or one that changes the outcome, still sends.

On the `cml_job` backend the email is sent from inside the Cloudera Job,
because that is where `run_deidentification` finishes -- the Job needs
`SMTP_HOST` and `APP_BASE_URL` in its own environment, or the notice
becomes a logged no-op with no link in it. The one case the API sends for
itself is a run that never touched the row at all: `deid_queue._fail_row`
marks the file `failed` after `DEID_DISPATCH_MAX_ATTEMPTS`, and notifies
from there.

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

### Rejections

One page for everything a reviewer turned down --
`frontend/src/routes/rejections/index.tsx`, gated on `application:view`:

- **Rejected applications**, from `/applications?status=rejected`, with the
  reason and a link into the submission.
- **Rejected documents**, from `/files/rejected` -- every file whose
  `review_status` is `rejected`, across all applications, with the note the
  reviewer left. Per row: read either copy, download either copy, attach a
  replacement redaction, or approve it as it stands.

`/files/rejected` is declared **before** `/files/{file_id}` so the literal
path wins, and it resolves patients in one pass over the applications
rather than a query per file. Its `has_original` / `has_deidentified` are
disk checks rather than columns: whether the identified copy still exists
depends on `DEID_KEEP_ORIGINAL` and on when the application was submitted,
so the page only offers the downloads that can actually work.

**A replacement sends the file back for review.** `/files-library` with
`replaces_file_id` now resets `review_status` to `pending` and clears the
note: a verdict describes the bytes it was given, and nobody has looked at
the new ones. That is also what takes the row off this queue. The rejection
reason is not lost -- it goes into the audit entry's `old_values`.

> Which uncovered a defect worth knowing about: that audit entry was
> **never being written**. `record_audit(action="REPLACE")` failed
> `AuditLogCreate`'s `^(CREATE|UPDATE|DELETE)$` pattern, and audit failures
> are logged rather than raised (see [Audit logging](#audit-logging)), so
> every replacement since the endpoint was written went unrecorded.
> `REPLACE` is now an allowed action, in `app/schemas.py` and in the
> frontend's `AUDIT_ACTIONS`.

### The two trails

Two questions, two tables, one page each. Neither is ever updated or
deleted -- and `audit_logs` should have `UPDATE`/`DELETE` revoked from the
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

- **`identified`** -- whether identified PHI left, or only a redacted
  copy. The same endpoint serves both, separated by `?deidentified=`, and
  only one of them is a disclosure. Without this flag every routine read
  looks like a breach.
- **`record_count`** on exports. "Exported 4,127 rows" and "exported 3"
  are different events.

Patient *list* views are deliberately not recorded: they fire on every
page load and would bury the reads that mean something. Detail views are.

**Writes are buffered.** A Hive INSERT costs seconds, almost all of it
planning, and the cost is per statement -- so a batch of 200 rows costs
about what one row costs. A background thread flushes every few seconds,
which keeps Hive off the request path entirely. The trade is a bounded
loss window: a kill between flushes loses what was queued, which is why
each event is written to the Application log synchronously as it happens.

Reads are partition-pruned. Bound the dates on the Access log page and
the query reads those days; leave them open and it reads every day ever
recorded. That is the whole reason the table is partitioned from the
start -- retrofitting a partition scheme means rewriting the table.

### Alerting

`scripts/access_alerts.py`, run as a CML Job on a schedule, counts events
per actor in a window and emails when a threshold is crossed -- bulk
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
**reach** it -- failed sign-ins die at the proxy, so those logs have to be
read where they are. And this records access **through the API**: reading
files off the volume, or querying Hive directly, needs OS and Ranger
auditing respectively.

### Logging / tracing

structlog with `contextvars`, so one `request_id` threads through the
whole transaction -- including the background audit write, which re-binds
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
counting `TRUSTED_PROXY_COUNT` hops in from the right -- everything
further left is client-supplied, so that count has to match the
deployment rather than be guessed.

`request_started` is at DEBUG. It carried nothing `request_finished`
does not, and at two lines per request it was most of the volume.

**Two renderings.** `console` is aligned key=value for a terminal;
`json` is one object per line for anything that ingests logs. Unset,
`LOG_FORMAT` picks by where stdout goes -- a terminal gets console, a
captured pipe gets json -- so local runs stay readable and Cloudera AI
gets machine-readable output without configuring anything. Tail a
production log by eye with `... | jq` and you get the pretty form back.

> **PHI does not go in the log stream.** Record values live in
> `audit_logs`, never in a log line -- the log lines carry the *names* of
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
