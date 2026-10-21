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
  `deidentified_file_path` STRING,
  `details_checked_at` STRING,
  `details_checked_by` STRING,
  `no_records` BOOLEAN
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
  `assigned_to_id` STRING,
  `original_file_path` STRING,
  `checklist` STRING
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
  `review_note` STRING,
  `redaction_boxes` INT,
  `leaded_phi` BOOLEAN
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

DROP TABLE IF EXISTS `access_logs`;

CREATE TABLE `access_logs` (
  `id` STRING,
  `occurred_at` TIMESTAMP,
  `action` STRING,
  `outcome` STRING,
  `actor_id` STRING,
  `actor_username` STRING,
  `actor_role` STRING,
  `source_ip` STRING,
  `user_agent` STRING,
  `request_id` STRING,
  `method` STRING,
  `path` STRING,
  `resource_type` STRING,
  `resource_id` STRING,
  `patient_id` STRING,
  `application_id` STRING,
  `identified` BOOLEAN,
  `record_count` INT,
  `byte_count` BIGINT,
  `detail` STRING
) PARTITIONED BY (`event_date` STRING)
STORED AS ORC
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

DROP TABLE IF EXISTS `projects`;

CREATE TABLE `projects` (
  `id` STRING,
  `short_code` STRING,
  `name` STRING,
  `description` STRING,
  `approval_reference` STRING,
  `consent_confirmed` BOOLEAN,
  `documents_approved` BOOLEAN,
  `status` STRING,
  `status_reason` STRING,
  `created_by_id` STRING,
  `created_at` TIMESTAMP,
  `updated_at` TIMESTAMP,
  `workspace_path` STRING,
  `workspace_built_at` STRING,
  `workspace_expires_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `patient_consents`;

CREATE TABLE `patient_consents` (
  `id` STRING,
  `patient_id` STRING,
  `consent_type` STRING,
  `status` STRING,
  `version` STRING,
  `consent_date` STRING,
  `note` STRING,
  `source` STRING,
  `recorded_by_id` STRING,
  `recorded_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `project_patients`;

CREATE TABLE `project_patients` (
  `id` STRING,
  `project_id` STRING,
  `patient_id` STRING,
  `project_patient_id` STRING,
  `date_shift_days` INT,
  `added_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `project_releases`;

CREATE TABLE `project_releases` (
  `id` STRING,
  `project_id` STRING,
  `status` STRING,
  `status_reason` STRING,
  `prepared_by_id` STRING,
  `prepared_at` TIMESTAMP,
  `reviewed_by_id` STRING,
  `reviewed_at` TIMESTAMP,
  `patients` INT,
  `applications` INT,
  `documents` INT,
  `files_included` BOOLEAN,
  `archive_path` STRING,
  `inbox_path` STRING,
  `release_path` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `abstraction_folders`;

CREATE TABLE `abstraction_folders` (
  `id` STRING,
  `name` STRING,
  `purpose` STRING,
  `owner_id` STRING,
  `status` STRING,
  `criteria` STRING,
  `file_ids` STRING,
  `file_count` INT,
  `folder_path` STRING,
  `created_at` TIMESTAMP,
  `expires_at` STRING,
  `deleted_at` STRING,
  `deleted_by_id` STRING,
  `deleted_reason` STRING,
  `assigned_to_id` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `project_members`;

CREATE TABLE `project_members` (
  `id` STRING,
  `project_id` STRING,
  `user_id` STRING,
  `added_by_id` STRING,
  `added_at` TIMESTAMP
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `original_grants`;

CREATE TABLE `original_grants` (
  `id` STRING,
  `file_id` STRING,
  `user_id` STRING,
  `reason` STRING,
  `granted_by_id` STRING,
  `granted_at` TIMESTAMP,
  `revoked_by_id` STRING,
  `revoked_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `incidents`;

CREATE TABLE `incidents` (
  `id` STRING,
  `title` STRING,
  `level` STRING,
  `status` STRING,
  `detected_at` STRING,
  `description` STRING,
  `data_affected` STRING,
  `risk` STRING,
  `containment` STRING,
  `affected_parties` STRING,
  `preliminary_sent_at` STRING,
  `full_sent_at` STRING,
  `preliminary_reminded_at` STRING,
  `full_reminded_at` STRING,
  `created_by_id` STRING,
  `created_at` TIMESTAMP,
  `updated_at` STRING,
  `closed_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `redcap_fields`;

CREATE TABLE `redcap_fields` (
  `id` STRING,
  `dataset` STRING,
  `field_name` STRING,
  `form_name` STRING,
  `field_type` STRING,
  `validation` STRING,
  `label` STRING,
  `choices` STRING,
  `identifier` BOOLEAN,
  `imported_by_id` STRING,
  `imported_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `redcap_values`;

CREATE TABLE `redcap_values` (
  `id` STRING,
  `dataset` STRING,
  `patient_id` STRING,
  `event` STRING,
  `instance` STRING,
  `field_name` STRING,
  `value` STRING,
  `imported_by_id` STRING,
  `imported_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');

DROP TABLE IF EXISTS `redcap_log`;

CREATE TABLE `redcap_log` (
  `id` STRING,
  `dataset` STRING,
  `logged_at` STRING,
  `username` STRING,
  `action` STRING,
  `record` STRING,
  `details` STRING,
  `imported_by_id` STRING,
  `imported_at` STRING
) STORED AS ORC
TBLPROPERTIES ('transactional'='true');
