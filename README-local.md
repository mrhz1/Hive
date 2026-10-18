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
INTAKE_DIR/A/B/C/AA1234/image.dcm                         (incoming: not de-identified yet)

DATA_DIR/original/A/B/C/AA1234/image.dcm                  original, same path
DATA_DIR/de_identified/AA1234/AA1234_<date>_<serial>.dcm  redacted copy, under the code
DATA_DIR/de_identified/AA1234/AA1234_<date>_<serial>.dcm.json   sidecar
DATA_DIR/failed/...                                       redaction failed
DATA_DIR/needs_attention/...                              no code, unsupported, conflict, duplicate
DATA_DIR/.intake/                                         locks, heartbeats, run reports

SUBMITTED_DATA_DIR/original/...                           the same layout, once the
SUBMITTED_DATA_DIR/de_identified/...                      application is submitted
```

`DATA_DIR` (default `storage/pending_data`) holds what is de-identified but
not submitted yet; submitting an application moves its files to
`SUBMITTED_DATA_DIR` (default `storage/submitted_data`) at the same relative
paths. So on disk: `INTAKE_DIR` = waiting, `DATA_DIR` = de-identified and
pending (or failed/excluded), `SUBMITTED_DATA_DIR` = submitted.

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

With `INTAKE_PAGE_POOL=on` the workers are shared across files instead of
each taking a file: one pool of `DEID_WORKERS` OCR processes, each with
`DEID_WORKER_CPU_THREADS` threads, reads the pages of every file in the
order they arrive. When there are fewer files than workers (the end of a
run, or one big PDF), the idle workers read the remaining pages of the
files still going, so a single 400-page PDF gets all of them. Twice as many
files as workers are in progress at once to keep the pool busy. Each file
is redacted by the NER stage as soon as its last page is read; models load
once per run. A file whose OCR worker was killed (exit -9) is tried once
more before it goes to `failed/`. The stage logs go to
`.intake/work/<host>-pool.log`. Redacted output is the same as without it.

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

Removing a file from a draft never deletes files under `DATA_DIR`; deleting
a rejected application from Rejections does. Submitting stamps the patient
code on redacted PDFs and moves the application's files from `DATA_DIR` to
`SUBMITTED_DATA_DIR`, same relative paths (a name already taken there gets a
`_2` suffix). Files uploaded through the old application upload still go to
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
- De-identified copy: `<code>_<modality>_<date>_<16-digit serial>_<R|RR>.<ext>`,
  e.g. `AA1234_MR_20190312_1790261077741000_R.pdf` (`deid.deid_output_name`).
  `_R`: redacted by the pipeline (intake, De-identify). `_RR`: redacted by
  hand -- uploaded already de-identified, or a replacement uploaded from
  Rejections, which keeps the file's name and turns `_R` into `_RR`.
  The modality and date come from `app/document_info.py`:
  - DICOM: the `Modality` tag and the first of `StudyDate`, `SeriesDate`,
    `AcquisitionDate`, `ContentDate`, falling back to the file name.
  - PDF and Word: the file name as received. The modality is a whole word
    (`CT`, `MR`, `MRI`, `Echo`, `X-ray`, ...; aliases become DICOM codes, so
    `MRI` is `MR`). The date is `YYYYMMDD` or `YYYY-MM-DD` (or with `_`, `.`,
    a space).
  - Not found: `UNKNOWN`. Staff set both with **Set modality & date** on the
    application's files (`PUT /files/{id}/document-info`), which renames the
    copy and its sidecar. Not allowed once the application is submitted.
  - The API returns `modality` and `document_date` on each file, read from
    the name. Names from before modalities (`<code>_<date>_<serial>`) still
    work and get a modality when renamed.

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

#### Intake emails

`app/intake_notices.py` emails every active user whose role has
`deidentifier:notify` ("gets emails" on the de-identifier row of the Roles
page):

- **New files waiting**: `scripts/intake_notify.py`, run as a scheduled
  Cloudera Job (e.g. every 30 minutes). It counts settled files in
  `INTAKE_DIR` by patient code and only mentions files that arrived since
  its last sent email (`.intake/notices.json`); if the email couldn't be
  sent they are mentioned again next time.
- **Intake run finished**: done / failed / need attention, from the end of
  every run. With `--shards` each machine sends its own.
- **Application rejected**: the failed checklist points and the reason, and
  whether the documents were deleted (patient not eligible, protocol 9.1.2).
- **Document rejected**: the file and the reviewer's note.

They need `SMTP_HOST`, and `APP_BASE_URL` for the links.

### Background uploads

`POST /applications/{id}/files/background` saves the files to
`FILE_STORAGE_DIR/.uploads/<job id>/`, returns 202, and processes them in a
background task (move, insert row, extract metadata, email). A failed file
is marked `failed` on the job and the others continue (`partial`). Job
progress is kept in memory, so after a restart `/upload-jobs/{id}` returns
404, but the files already processed are fine.

### JPG/PNG/TIFF images (9.1.8)

Images in other formats (jpg, jpeg, png, tif, tiff, bmp, gif; also found by
their content when the name has no extension) are accepted by the intake
and the upload. Before de-identification each is converted to a DICOM
Secondary Capture (`app/image_convert.py`): PatientID = the code, Modality
from the file name (`xray` -> DX, else OT), StudyDate from the file name,
new UIDs, SeriesDescription "Converted from JPG". Nothing from the source
(EXIF, GPS, the file name) goes into the DICOM; the original's EXIF is
shown in its metadata. It then goes through the DICOM pipeline (burned-in
text found and covered) and is stored and named as a `.dcm`. Multi-page
TIFF: first page only. Needs Pillow and numpy (in `requirements-dev.txt`).

### Document type from the file name (9.1.2)

Redacted files are named `<code>_<type>_<date>_<serial>_<R|RR>`. For PDF,
Word and other files the type comes from the file name the site gave it,
never from the content (`app/document_info.py`, `TYPE_KEYWORDS`): e.g.
`discharge` -> DISCHARGE, `op note` -> OPERATIVE, `consent` -> CONSENT,
`echo`/`TTE` -> ECHO_REPORT, `MRI` -> MRI_REPORT, `EKG` -> ECG_REPORT; JPG/PNG
-> IMAGE; an Excel/CSV with `sts` -> STS_EXTRACT. Words are matched whole,
first type wins. A name with only a modality (`..._CT_...pdf`) keeps it;
anything else is UNKNOWN and staff set it with *Set type & date*. DICOM
files are still named by their Modality tag. More words per type can be
added in a JSON file named by `DOCUMENT_TYPES_FILE`:
`{"DISCHARGE": ["clinic letter"]}`. Files already processed keep their names.

### Text in images and bulk file corrections (7.9)

- **Burned-in text**: redaction already finds and covers text inside DICOM
  pictures (e.g. lead letters with a name). How many areas it covered is
  read from the pipeline's report and kept on the file
  (`patient_application_files.redaction_boxes`). The file list shows "text
  covered in picture (N)" on such images and can show only them. Checking
  them is optional; if an identifier still shows, **Reject** the image: it
  goes to Rejections and stays out of Zone 2 until replaced (`_RR`).
- **Leaded images (9.1.9)**: an image with identifiers in lead letters that
  can only be scrubbed by hand gets **Mark as leaded** (file actions, needs
  `files:reject`, also on submitted applications;
  `PUT /files/{id}/leaded`, `patient_application_files.leaded_phi`). It
  stays where it is and usable in Zones 1 and 1X, but preparing a Zone 2
  release with documents is refused while a cohort patient has one, and
  approving is refused if one was marked after preparing. Clear the mark
  once the image is scrubbed and replaced. Marking and clearing are audited.
- **Bulk corrections**: `scripts/update_file_metadata.py corrections.xlsx`
  (add `--apply` to make the changes, `--user` for the audit log). Columns:
  File (redacted name or file id), Modality, Document date, Reject reason,
  Leaded (yes/no); blank keeps what is there. Renames files of any application except
  deleted ones (`app/file_corrections.py`).
- New column: run `python scripts/migrate_columns.py --apply`.

### Bulk patient import and checked details

**Import** on the Patients page (`app/patient_import.py`) loads patients
from an Excel or CSV file: download the template, upload, preview, import.

- Columns are matched by the template's labels ("First name", "Date of
  birth") or the database names (`fstname`, `dt_b`); labels win, so "City"
  is the patient's city. Unknown columns are listed and left out.
- New codes are created (in batches of 200; one INSERT per row is slow on
  Hive). Existing patients only get their empty fields filled; a different
  value is shown as a conflict and kept as it is.
- Rows with a bad or repeated code, a date that isn't an Excel date or
  YYYY-MM-DD, a bad email, or another patient's email/phone are skipped.
- Needs `patient:create` and `patient:update`. One audit entry per import.

**Checked details** (`patient.details_checked_at`, `details_checked_by`):
patients made by intake or the import start unchecked; their first
application can't be submitted until someone clicks *Details are correct*
in step 1 (`POST /patients/{id}/confirm-details`). Patients typed in by hand
count as checked. Patients already in the database before this column
start unchecked too. Add the columns with
`python scripts/migrate_columns.py --apply`.

**Sites that share no records (9.1.2)** (`patient.no_records`): some sites
only ask for a code and enter their data themselves. Ticking *Site does not
share records or contact details* on the patient lets it be saved with the
code only (no name or email), and its applications don't wait for the
details check. The patient shows as "No records (site)". Changes are in the
patient's audit entries.

### Enrollment checklist

Submitting an application asks for the four checks (all files submitted,
patient eligible, right consent form, no identifiers left); the API refuses
`status: submitted` unless `checklist` has all four true. Rejecting asks
which of them failed (`failed_checks`) and a reason:

- `consent` failed: the data can't be kept. The application's documents
  (originals and de-identified copies) are deleted at once, as Delete on
  Rejections does, and it becomes a deleted record. Needs
  `application:delete`.
- anything else: it is rejected, to be fixed and submitted again.

The last result is in `patient_applications.checklist` (JSON: `passed` or
`failed`, `by`, `at`). On an existing database add the column with
`python scripts/migrate_columns.py --apply`.

### Rejections

`/rejections` (needs `application:view`) shows:

- rejected applications (`/applications?status=rejected`)
- rejected documents (`/files/rejected`), with the reviewer's note. For each
  one you can view or download either copy, upload a replacement, or
  approve it.

Uploading a replacement (`/files-library` with `replaces_file_id`) sets
`review_status` back to `pending` and clears the note. The old note is kept
in the audit log (`REPLACE` action).

### Abstraction folders

`/abstraction` (`app/abstraction.py`): temporary, read-only copies of
de-identified documents for one person's task.

- **Pick by metadata**: patient codes, modality, document date range, file
  type, and text in the file name or the metadata read from the file. Only
  documents of submitted applications are offered. *Find documents* shows
  what matches before anything is copied.
- **On disk**: `ABSTRACTION_DIR/<username>/<id8>-<name>/<CODE>/<file>` plus
  `MANIFEST.csv` (file, patient, modality, date, type, file id). Files and
  folders are made read-only so nothing new is added; on Cloudera also set
  the folder ACLs so only the owner can read their folder.
- **Expiry**: `ABSTRACTION_EXPIRY_DAYS` (90) from making or extending it.
  `scripts/abstraction_cleanup.py`, run daily as a scheduled Job, deletes
  the expired ones. *Make again* copies the same documents again (those
  still available) with a fresh 90 days. At most `ABSTRACTION_MAX_FILES`
  (5000) per folder.
- **Permissions** (`abstraction:*`): `view` and `update` your own folders,
  `create` new ones, `delete` = see and manage everyone's (the application
  specialist). Making a folder is logged in the access log as an export, and
  every change in the audit log.
- Table `abstraction_folders`; on an existing database run
  `python scripts/migrate_columns.py --apply`.

### Zone 1X: consent, cohort criteria, workspace (spec 9.2)

- **Consent matrix** (`/consents`, `app/consent.py`, table
  `patient_consents`, needs `consent:view` / `consent:update`): one row per
  decision (research, or documents = PDFs and images; granted, refused or
  withdrawn; form version and date), recorded by hand or imported from a
  spreadsheet. Rows are never changed; the latest per patient and type
  counts. A refused or withdrawn research consent keeps the patient out of
  every project; for a project approved for documents, so does the
  documents consent. It is checked when the cohort is saved, when the
  workspace is built and when a safe copy is prepared. A patient with no
  row is covered by the project's *Patient consent confirmed* box. REDCap
  can fill the same table later.
- **Cohort by criteria** (*Find by criteria* in *Choose patients*,
  `app/cohort.py`): code prefix, registration date, age at registration,
  country/state, institution, living only, modality and date of documents,
  codes to exclude. Patients the consent matrix keeps out are listed apart.
  Clinical criteria come with REDCap.
- **Workspace** (`app/workspace.py`): *Build workspace* writes
  `PROJECTS_DIR/<code>/workspace/` with `patients.csv`, `applications.csv`,
  `documents.csv` (CHSS codes kept, names and contacts left out), the
  de-identified PDFs and images under `documents/<CODE>/`, and
  `cleaning_log.csv`. Read-only. Deleted `WORKSPACE_EXPIRY_DAYS` (90) after
  it was first built unless *Extend 90 days* is used with a reason (audited);
  rebuilding keeps the date. `scripts/workspace_cleanup.py`, run daily,
  deletes expired ones. Release archives are separate and stay.
- **Cleanup rules** (`cleaning/`, `app/cleaning.py`): Python files applied
  to the tables at every build: `instrument/<table>.py`,
  `instrument/<MODALITY>.py`, `cohort/<PREFIX>.py`. See `cleaning/README.md`.
  A failing rule stops the build and keeps the old workspace.
- New columns and the `patient_consents` table:
  `python scripts/migrate_columns.py --apply`.

### Metadata, uploads and logs (security review, 2026-10-14)

- **Metadata of de-identified files** keeps the same fields as the original,
  with identifying values redacted: DICOM (identifying tags become
  `<REMOVED>`, dates blanked, free text through the name detector, private
  tags removed, every non-standard UID replaced with a new one keyed by
  `DEID_UID_SALT`), PDF (Info fields and XMP values through the detector,
  authors `<REMOVED>`), Word (core properties the same way). The name the
  site gave the file is no longer written into it. Zone 2 copies of DICOM
  files get project-own UIDs on top.
- **Uploads** (originals, de-identified files, replacements) each leave an
  audit entry (who, stored name, uploaded-as name, size, SHA-256; for a
  replacement also the fingerprint of the file replaced) and an access log
  entry `upload` (time, IP, request id).
- **Exports** (Excel, CSV reports, MANIFEST) put an apostrophe before text
  starting with `= + - @` so it can't run as a formula. Workspace and Zone 2
  data tables are left as they are.
- **Logs** hold `file_ref` (see DEPLOYMENT.md) instead of file names and
  paths, and validation errors log the field, not what was typed. Database
  errors show users a plain message; the details stay in the log.
- **Profile** is read-only; administrators change names and emails on the
  Users page (audited).

### Migration report, data quality check, workspace profile

- **Migration report** (`scripts/migration_report.py`, `app/migration_report.py`):
  files waiting, de-identified (pending/submitted), failed and needing
  attention by reason, document types, documents in applications
  (rejected, leaded, images with covered text), patients not checked and
  without consent, applications by status. Reads folders and the database
  only (names, never contents), streams rows, so it suits millions of
  files. Output in `REPORTS_DIR/migration-<time>/`: `migration-report.xlsx`
  (summary + lists capped at 50,000 rows, `--cap`) and every list in full
  as CSV.
- **Data quality check** (`scripts/qc_check.py`, `app/qc.py`): rules P01-P07
  (patients: missing birth date, impossible or future dates, age over 100,
  no name), A01-A02 (submitted applications without documents or
  checklist), D01-D06 (documents: UNKNOWN type/date, dated before birth,
  after death or in the future, failed de-identification), C01-C02 (no
  research consent; withdrawn consent in an active project). Accepted
  issues go in `QC_SUPPRESSIONS_FILE` (rule, record, reason, by, date) and
  are listed apart. Excel, PDF and CSV in `REPORTS_DIR/qc-<time>/`; the
  email to `QC_EMAIL_TO` gives counts only.
- **Workspace profile**: every workspace build also writes `profile.xlsx`
  (`app/profiling.py`): per column filled/missing/distinct and range,
  frequency tables, outliers (IQR for numbers, dates before 1900 or in the
  future).

### Zone 2 review and project end

`app/zone2.py`. Reviewing a release on the Zone 2 inbox page:

- **Spot checks**: when the release includes documents, the manager can open
  any of them (PDF in the page, DICOM as an image, Word downloaded), or pick
  5 at random. Opening one is logged in the access log
  (`release_document`). Checking every file is not required.
- **Flag**: a document that still identifies someone is flagged with a
  reason. The release is sent back, the source document is marked rejected
  so it shows in Rejections (and the intake team gets an email), and the
  project can't be prepared again with documents until it is replaced
  (`_RR`) or deleted. Rejected documents are also left out of abstraction
  folders.
- **End project** (`POST /projects/{id}/end`, with a reason): the project
  becomes `ended` and can't be changed or prepared again. Its Zone 2 copy
  and archive stay. Researchers' access is removed by hand in Users and
  Roles; ethics approvals, agreements and training are tracked outside the
  app.

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

### Security: lockdown and incidents (section 4)

- **Lockdown** (`app/lockdown.py`, Security page or the banner): a user with
  `security:manage` locks the app with a reason and level; everyone else gets
  503 `locked` on every call except `/me` and `/security/lockdown`, and
  every page shows a banner. Locking and unlocking are emailed and audited.
  The state is `SECURITY_STATE_DIR/lockdown.json`, shared by all instances.
- **Alert levels** (`scripts/access_alerts.py`): identified downloads and
  auth failures are high, exports and denials low; any rule turns critical
  at `ALERT_CRITICAL_FACTOR` (3) times its limit. Low goes to
  `ALERT_EMAIL_LOW_TO` (the application specialist), high and critical to
  `ALERT_EMAIL_TO` (Program Manager, specialist, Host IT). At
  `ALERT_LOCKDOWN_LEVEL` (critical) or above the job locks the app itself;
  `none` turns that off.
- **Incidents** (`app/incidents.py`, table `incidents`): title, level,
  detection time, what happened, data affected, risk, containment, affected
  parties. The preliminary report is due 24 h after detection and the full
  one 72 h; mark each as sent. High and critical incidents are emailed when
  recorded. `scripts/incident_reminders.py` (hourly Job) emails once per
  report 6 h before it is due or when overdue. *Report (.docx)* exports the
  breach report. Closing needs the data affected, the containment and the
  full report sent.

### Data dictionary (7.10)

Every Zone 2 safe copy has `data_dictionary.csv` (file, column, type,
meaning, values) and the Excel exports a "Data dictionary" sheet
(`app/data_dictionary.py`). A test fails if a released column has no
definition.

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
