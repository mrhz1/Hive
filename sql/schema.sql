-- Managed + STORED AS ORC + TBLPROPERTIES ('transactional'='true') is what
-- makes DELETE/UPDATE work (full ACID). On Cloudera's Hive (CDP), managed
-- ORC tables get this property automatically via strict-managed-tables
-- mode, so `transactional`='true' is real, persisted metastore metadata
-- there too -- SHOW CREATE TABLE on Cloudera will show it explicitly.
-- Vanilla Apache Hive (used in local docker-compose.yml) does not set it
-- automatically, so it's spelled out here for parity.
--
-- EXTERNAL tables are NEVER transactional, regardless of file format --
-- DELETE/UPDATE will be rejected on them.
--
-- NOTE on ids: Hive has no sequences/AUTO_INCREMENT, so ids are
-- application-generated UUID STRINGs.
--
-- COLUMN ORDER IS LOAD-BEARING. Hive INSERT is positional against the
-- table definition, and the CRUD layer builds its statements from a
-- COLUMNS tuple per module. The order here must stay identical to:
--   patient                  app/crud/patients.py::COLUMNS
--   patient_applications     app/crud/patient_applications.py::COLUMNS
--   patient_application_files app/crud/patient_application_files.py::COLUMNS
--   file_metadata            app/crud/file_metadata.py::COLUMNS
--   audit_logs               app/crud/audit_log.py::COLUMNS
-- The test suite's fake cursor is keyed by name and cannot catch a
-- self-consistent reordering; this file is the guard.

DROP TABLE IF EXISTS `roles`;

-- permissions is ARRAY<STRING> of "<model>:<action>" grants, e.g.
-- 'user:view'. Verified working on ORC ACID: INSERT via array(%s, ...),
-- UPDATE via SET col = array(...). Reads come back from impyla as BYTES
-- holding a JSON array (b'["user:view"]'), not a Python list -- see
-- app/crud/roles.py::_parse_permissions.
CREATE TABLE `roles` (
  `id` STRING,
  `name` STRING,
  `permissions` ARRAY<STRING>
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `users`;

CREATE TABLE `users` (
  `id` STRING,
  `username` STRING,
  `email` STRING,
  `first_name` STRING,
  `last_name` STRING,
  `status` STRING,
  `is_active` BOOLEAN,
  `role_id` STRING,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient`;

-- Singular, matching the Cloudera metastore. Patients carry no role_id:
-- roles govern API callers (users), and patients are not API callers.
--
-- Naming follows the source records:
--   p*  / unprefixed address+phone -- the provider / institution the
--                                     patient is registered with
--   pt*                            -- the patient's own contact details
--   fstname / lstname              -- the patient's name
--   dt_reg / dt_b / dt_d           -- registration, birth, death
--
-- original_file_path / deidentified_file_path point at the patient's
-- source document; per-document rows live in `patient_application_files`,
-- attached to an application rather than to the patient directly.
--
-- There is deliberately no status / is_active / created_at here. A
-- patient row is record data, not a workflow object -- lifecycle belongs
-- to `patient_applications`, which is what actually moves through states.
--
-- Every column is nullable, because these records are ingested from
-- systems that do not always populate them. The API requires only two
-- things: original_file_path, and at least one of fstname / lstname /
-- ptemail so the row can be recognised. Hive has no CHECK constraints, so
-- both rules are enforced in app/schemas.py and app/crud/patients.py.
CREATE TABLE `patient` (
  `id` STRING,
  `fstname` STRING,
  `lstname` STRING,
  `instcode` STRING,
  `pname` STRING,
  `street` STRING,
  `street2` STRING,
  `street3` STRING,
  `city` STRING,
  `state` STRING,
  `zip` STRING,
  `country` STRING,
  `phone1` STRING,
  `phone2` STRING,
  `wphone1` STRING,
  `wphone2` STRING,
  `pemail` STRING,
  `ptstreet` STRING,
  `ptstreet2` STRING,
  `ptstreet3` STRING,
  `ptcity` STRING,
  `ptstate` STRING,
  `ptzip` STRING,
  `ptcountry` STRING,
  `ptphone` STRING,
  `ptphone2` STRING,
  `ptwphone` STRING,
  `ptwphone2` STRING,
  `ptemail` STRING,
  `dt_reg` DATE,
  `dt_b` DATE,
  `dt_d` DATE,
  `original_file_path` STRING,
  `deidentified_file_path` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient_applications`;

-- One submission of a patient and their documents for review.
--
-- The application is the workflow wrapper around a patient record: the
-- wizard creates a patient in step 1 and an application row alongside it,
-- then step 2 attaches documents and step 3 summarises the result. The
-- patient holds the clinical facts; this holds who did what, and when.
--
--   status  'draft' -> 'submitted' -> 'approved' | 'rejected'
--
-- This is also the only place a review verdict is recorded. Individual
-- documents are not approved or rejected -- see patient_application_files.
--
-- The *_by_id columns are user ids. They are STRINGs rather than a
-- foreign key because Hive does not enforce referential integrity --
-- the application layer sets them from the authenticated caller.
--
-- submitted_at / reviewed_at stay NULL until those transitions happen,
-- so "never submitted" is distinguishable from "submitted at some
-- unknown time".
CREATE TABLE `patient_applications` (
  `id` STRING,
  `patient_id` STRING,
  `submitted_by_id` STRING,
  `reviewed_by_id` STRING,
  `status` STRING,
  `submitted_at` TIMESTAMP,
  `reviewed_at` TIMESTAMP,
  `created_at` TIMESTAMP,
  `updated_at` TIMESTAMP,
  `description` STRING,
  `created_by_id` STRING,
  `updated_by_id` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient_application_files`;

-- Documents belonging to an **application**, not to a patient directly.
-- A patient's documents are reached through their applications, which is
-- what makes "which submission was this uploaded for?" answerable.
--
-- Hive holds only metadata; the bytes live on the filesystem under
-- FILE_STORAGE_DIR, with `file_path` pointing at them. Storing binaries
-- in ORC would bloat the warehouse and make every scan expensive, and
-- Hive is not a blob store. Extracted document metadata does not live
-- here either -- it goes in `file_metadata`, one row per file.
--
-- The de-identification columns are the hand-off to the OCR job:
--   deid_status  'pending' -> ['queued'] -> 'processing' -> 'done' | 'failed'
--     'pending'    uploaded, nobody has asked for it
--     'queued'     a Cloudera AI Job run has been requested for it
--                  (DEID_BACKEND=cml_job only; inline goes straight to
--                  'processing')
--     'processing' a worker has claimed it
--   is_deidentified FALSE on upload, TRUE once a redacted copy exists
--   deidentified_file_name / de_identified_file_path are NULL until then
--
-- Note the two spellings: `deidentified_file_name` against
-- `de_identified_file_path`. That is what the Cloudera metastore has, and
-- matching it exactly beats being tidy -- a rename here is a migration.
CREATE TABLE `patient_application_files` (
  `id` STRING,
  `application_id` STRING,
  `original_file_name` STRING,
  `sanitized_file_name` STRING,
  `deidentified_file_name` STRING,
  `file_extension` STRING,
  `mime_type` STRING,
  `file_size` INT,
  `deid_status` STRING,
  `is_deidentified` BOOLEAN,
  `created_at` TIMESTAMP,
  `description` STRING,
  `file_path` STRING,
  `de_identified_file_path` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `file_metadata`;

-- Metadata extracted from an uploaded document, one row per file.
--
-- `metadata` is the extractor's output as a JSON object serialised to
-- STRING, because ORC/Hive has no JSON type -- the same convention
-- audit_logs uses for old_values/new_values. It is deliberately
-- schemaless: a DICOM study and a Word document share almost no fields,
-- and a column per attribute would be a hundred mostly-NULL columns that
-- still could not hold the next format.
--
-- Written once, right after the file row is created (app/routers/
-- patient_application_files.py). Extraction failing does not fail the
-- upload -- `status` records what happened so the UI can say "no
-- metadata" rather than showing an empty object as if the file had none:
--   status  'ok'          extracted, `metadata` holds the fields
--           'unsupported' not a format we read (only PDF/DICOM/Word are)
--           'failed'      the file was one of those and could not be read;
--                         `error` carries the reason
--
-- No foreign key (Hive has none); `file_id` references
-- patient_application_files.id and the row is deleted alongside it.
CREATE TABLE `file_metadata` (
  `id` STRING,
  `file_id` STRING,
  `file_type` STRING,
  `metadata` STRING,
  `status` STRING,
  `error` STRING,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `audit_logs`;

-- Append-only change log. old_values/new_values hold JSON serialized to
-- STRING because ORC/Hive has no native JSON type. Convention:
--   CREATE -> old_values NULL, new_values populated
--   UPDATE -> both populated
--   DELETE -> old_values populated, new_values NULL
-- entity_type is the model name ('user', 'patient').
-- user_id is the authenticated caller who made the change, NULL only for
-- changes with no acting user (a scheduled job writing back a result).
CREATE TABLE `audit_logs` (
  `id` STRING,
  `action` STRING,
  `entity_type` STRING,
  `entity_id` STRING,
  `user_id` STRING,
  `old_values` STRING,
  `new_values` STRING,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');
