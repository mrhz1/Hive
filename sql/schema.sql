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

DROP TABLE IF EXISTS `customers`;

-- Same shape as `users` minus `username`, plus `phone_number`/`address`.
-- Customers carry no role_id: roles govern API callers (users), and
-- customers are not API callers.
CREATE TABLE `customers` (
  `id` STRING,
  `email` STRING,
  `first_name` STRING,
  `last_name` STRING,
  `phone_number` STRING,
  `address` STRING,
  `status` STRING,
  `is_active` BOOLEAN,
  `created_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `customer_files`;

-- Documents belonging to a customer.
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
CREATE TABLE `customer_files` (
  `id` STRING,
  `customer_id` STRING,
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
-- entity_type is the model name ('user', 'customer').
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
