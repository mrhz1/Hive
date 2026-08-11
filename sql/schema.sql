
DROP TABLE IF EXISTS `roles`;

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
  `updated_by_id` STRING,
  `status_reason` STRING,
  -- The user who has to do the work. Notifications about this
  -- application's uploads go to them.
  `assigned_to_id` STRING,
  -- Where this application's documents came from. Per application, not
  -- per patient: a second application for the same patient routinely
  -- draws on a different folder.
  `original_file_path` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient_application_files`;

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
  `de_identified_file_path` STRING,
  `review_status` STRING,
  `review_note` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `file_metadata`;

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
