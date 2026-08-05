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
-- Replace the DDL below with your production `SHOW CREATE TABLE` output.
--
-- NOTE on ids: Hive has no sequences/AUTO_INCREMENT, so ids are
-- application-generated UUID STRINGs.

DROP TABLE IF EXISTS `roles`;

-- permissions is ARRAY<STRING> of "<model>:<action>" grants, e.g.
-- 'users:read'. Verified working on ORC ACID: INSERT via array(%s, ...),
-- UPDATE via SET col = array(...). Reads come back from impyla as BYTES
-- holding a JSON array (b'["users:read"]'), not a Python list -- see
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

DROP TABLE IF EXISTS `patients`;

-- Patients carry no role_id: roles govern API callers (users), and
-- patients are not API callers.
--
-- Naming follows the source records:
--   p*  / unprefixed address+phone -- the provider / institution the
--                                     patient is registered with
--   pt*                            -- the patient's own contact details
--   fstname / lstname              -- the patient's name
--   dt_reg / dt_b / dt_d           -- registration, birth, death
--
-- original_file_path / deidentified_file_path point at the patient's
-- source document; per-document rows live in `patient_files`.
--
-- Every column is nullable here, because these records are ingested
-- from systems that do not always populate them. The API requires only
-- two things: original_file_path, and at least one of fstname / lstname
-- / ptemail so the row can be recognised. Hive has no CHECK constraints,
-- so both rules are enforced in app/schemas.py and app/crud/patients.py.
CREATE TABLE `patients` (
  `id` STRING,
  `instcode` STRING,
  `pname` STRING,
  `pemail` STRING,
  `phone1` STRING,
  `phone2` STRING,
  `wphone1` STRING,
  `wphone2` STRING,
  `street` STRING,
  `street2` STRING,
  `street3` STRING,
  `city` STRING,
  `state` STRING,
  `zip` STRING,
  `country` STRING,
  `fstname` STRING,
  `lstname` STRING,
  `ptemail` STRING,
  `ptphone` STRING,
  `ptphone2` STRING,
  `ptwphone` STRING,
  `ptwphone2` STRING,
  `ptstreet` STRING,
  `ptstreet2` STRING,
  `ptstreet3` STRING,
  `ptcity` STRING,
  `ptstate` STRING,
  `ptzip` STRING,
  `ptcountry` STRING,
  `dt_reg` DATE,
  `dt_b` DATE,
  `dt_d` DATE,
  `original_file_path` STRING,
  `deidentified_file_path` STRING,
  `status` STRING,
  `is_active` BOOLEAN,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient_files`;

-- Documents belonging to a patient.
--
-- Hive holds only metadata; the bytes live on the filesystem under
-- FILE_STORAGE_DIR, with `file_path` pointing at them. Storing binaries
-- in ORC would bloat the warehouse and make every scan expensive, and
-- Hive is not a blob store.
--
-- The de-identification columns are the hand-off to the OCR job:
--   deid_status  'pending' -> 'processing' -> 'done' | 'failed'
--   is_identified TRUE while the file still contains identifiers
--   deidentified_file_name / _path are NULL until a redacted copy exists
CREATE TABLE `patient_files` (
  `id` STRING,
  `patient_id` STRING,
  `original_file_name` STRING,
  `sanitized_file_name` STRING,
  `deidentified_file_name` STRING,
  `file_extension` STRING,
  `mime_type` STRING,
  `file_size` BIGINT,
  `deid_status` STRING,
  `is_identified` BOOLEAN,
  `created_at` TIMESTAMP,
  `description` STRING,
  `file_path` STRING,
  `deidentified_file_path` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `audit_log`;

-- Append-only change log. old_values/new_values hold JSON serialized to
-- STRING because ORC/Hive has no native JSON type. Convention:
--   CREATE -> old_values NULL, new_values populated
--   UPDATE -> both populated
--   DELETE -> old_values populated, new_values NULL
-- entity_type is the model name ('user', 'patient').
CREATE TABLE `audit_log` (
  `id` STRING,
  `action` STRING,
  `entity_type` STRING,
  `entity_id` STRING,
  `old_values` STRING,
  `new_values` STRING,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');
