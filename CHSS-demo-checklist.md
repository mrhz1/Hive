# CHSS Data Environment – Demo Checklist

Demo: AVSD cohort, 10 SickKids patients, 90 minutes.

Status words: Built = in the app and working · Simulated = works with file import/export instead of the REDCap API · Manual = done by a person outside the app (by decision) · Partly / Missing = gap · Not ours = RIT, Cloudera, REDCap or another team.

Jump to the end for: Before the demo, Suggested demo order, Build-later list, Questions for Cedric.

## Manager's 3 demo goals

| # | Goal | Where in app | Status |
|---|------|--------------|--------|
| A | Patient identifiers table moved to UBRS | Eena's part (outside our app). Our app: Zone 1 → Patients | Eena |
| B | PDFs and images moved and processed through UBRS de-identification / file management | Zone 1 → De-Identifier → Files → Rejections | Built |
| C | Zone 1X for Dom's project with AVSD analysis-ready tables, PDFs, images | Zone 1X → Projects | Built |

## Protocol checklist

### Page 1 – §1 Executive summary, §2 Preamble, §3 Historical data (background)

| Item | Where in app | Status |
|------|--------------|--------|
| Zone-based security model | Left menu groups: Zone 1 / Zone 1X / Zone 2 / Administration | Built |
| Audit trail | Administration → Audit log, Access log | Built |
| Automatic PHI detection and redaction | Zone 1 → De-Identifier | Built |
| Patient code instead of identity (UBRS) | Zone 1 → Patients | Built |
| REDCap integration | Zone 1 → REDCap (simulated with CSV import/export) | Simulated |
| Quality control / validation | Zone 1 → Files, Rejections | Built |
| Different consent standards across cohorts | Zone 1X → Consent matrix | Built |

### Page 2 – §3 (cont.), §4 Technologies & tools, §5 Access & zones

| Item | Where in app | Status |
|------|--------------|--------|
| Abstracted data follows approved de-identification rules | Zone 1 → De-Identifier (redaction before files move on) | Built |
| Runs on Cloudera (Expedition), written in Python | Backend is Python, deployed on Cloudera | Built |
| REDCap as main data collection tool | Zone 1 → REDCap (CSV simulation) | Simulated |
| UBRS manager holds patient identity | Eena's UBRS; our app uses patient codes (Zone 1 → Patients) | Eena |
| Code in SK RIT GitLab | GitLab repo | Done |
| Zone 3 document repository on SharePoint | Outside our app | Not ours |
| Zone 1 = intake, integration, storage | Left menu → Zone 1 group | Built |
| Zone 1X = cleaning and preparation | Left menu → Zone 1X group (Consent matrix, Abstraction folders, Projects) | Built |
| Zone 2 = analytics | Left menu → Zone 2 inbox (release to Zone 2) | Built |
| Access by approval, need, training | Administration → Users, Roles | Built |
| Zone 1X / Zone 2 split by project | App: each project has its own members and its own Zone 2 folder. Folder access on Cloudera: pending storage meeting | Partly |
| PHI only in Zone 1; Zone 1X minimal; none in Zone 2+ | De-Identifier before Zone 1X; Zone 2 inbox can flag a document with PHI and send it back | Built |
| Remediation when PHI leaks past intake | Zone 2 inbox → Flag document → file appears in Zone 1 → Rejections → download, redact in Acrobat Pro → "Replace de-identified copy" | Built |

### Page 3 – Figure 1 (zone diagram), access rules

| Item | Where in app | Status |
|------|--------------|--------|
| Flow: upload → Zone 1 storage → Zone 1X cleaning → temp storage → analysis prep → Zone 2 storage | Zone 1 De-Identifier/Files → Zone 1X Abstraction folders (temp storage) → Projects (analysis prep) → Zone 2 inbox (release) | Built |
| Site upload from internet (Zone 4) | Sites send files by SFTP (set up outside the app) into the intake folder (INTAKE_DIR); the De-Identifier picks them up | Built (SFTP outside app) |
| Patient portal (Zone 4) = follow-up portal | Waiting for Cloudera to allow outside access; build after that. Check later pages | Waiting on Cloudera |
| REDCap → Cloudera database | Zone 1 → REDCap (CSV simulation) | Simulated |
| Analysis VMs in Zone 2 | Cloudera CML workspace, outside app | Not ours |
| Zone 1 only CRQ, VPN | VPN by RIT; app roles in Administration → Roles | Built |
| Only senior analysts run Python scripts in Zone 1 | Administration → Roles: "deidentifier:run" (run de-identifier) and "project:workspace" (build workspace, runs cleaning rules) only for senior roles | Built |
| Zone 1X for non-CRQ: approved need + VPN agreement + REB | Approvals checked by manager outside the app; access via Users/Roles | Manual |
| Prefer de-identify + release to Zone 2 over Zone 1X access | Zone 1X → Projects → Prepare release → Zone 2 inbox | Built |
| Zone 2: approved project, participation agreement, REB, credentials | Project has an approval reference field (REB number); documents tracked by manager | Manual |

### Page 4 – §5 (end), §6.1 Credentials, §6.2 Data residency & backup

| Item | Where in app | Status |
|------|--------------|--------|
| Zone 2 access limited to one project | Zone 1X → Projects → open project → "Members" card | Built |
| Zone 2 access auto-revoked every 6 months unless extended | Not automatic (decided 2026-10-13: manager removes access by hand in Users / Members) | Manual (gap vs text) |
| Access revoked at end of project | Projects → open project → "End project" button (after a release) | Built |
| Zone 3 (SharePoint), no PHI | Outside app | Not ours |
| Zone 4: one-time link for patients, RIT credentials for sites, no identifiers | REDCap side; app sends only patient codes (REDCap → "New patient codes (to REDCap)") | Not ours / Simulated |
| Zone 1/1X: VPN + CHSS credentials | VPN by RIT; app has no own login, Cloudera signs the user in (REMOTE-USER) | Built (platform) |
| Entra ID + MFA through Cloudera | Cloudera/RIT | Not ours |
| Role-based access, least privilege | Administration → Roles; Users | Built |
| Unknown / inactive users refused and logged | Administration → Access log | Built |
| RIT monitors sign-ins | RIT; app side: Access log | Not ours / Built |
| No hard-coded credentials for scripts | App uses Cloudera service settings (env vars), no passwords in code | Built |
| CHSS Manager reviews access requests, documents compliance, reviews directory | Manual; Users page + Audit log as evidence | Manual |
| Site coordinators get REDCap follow-up access, split by site (DAG) | REDCap side | Not ours |
| Patient follow-up by one-time REDCap survey link | REDCap → "Follow-up list (to REDCap)" → "Download list (Excel)" (links filled once API is connected) | Simulated |
| Data stays in Canada, in Cloudera; backup / DR by RIT | RIT | Not ours |
| (Related) Security incidents | Administration → Security: "Lock the app", "Record an incident" | Built |

### Page 5 – §6.3 Encryption, Figure 2, §6.4 Key management, §6.5 Logging & breach

| Item | Where in app | Status |
|------|--------------|--------|
| Data encrypted at rest in Cloudera | Cloudera/RIT | Not ours |
| Secrets/keys in approved key management | App reads settings from Cloudera environment, no secrets in code | Built (platform) |
| TLS 1.2+ for data in transit | Cloudera serves the app over HTTPS; app checks TLS certificates when calling Cloudera (CML_VERIFY_TLS) | Built (platform) |
| Figure 2: Entra ID, monitoring, backup, key services | Cloudera/RIT | Not ours |
| §6.4 Key management, vulnerability mgmt, threat detection | RIT | Not ours |
| App writes system/operational logs | Logs go to Cloudera application logs | Built |
| Audit log: user, action, record, date/time | Administration → Audit log (columns Action, Entity, Record, Who, When; filters) | Built |
| Audit log cannot be edited or deleted | No log:update / log:delete permission exists | Built |
| Unauthorized access attempts logged | Administration → Access log → filter What = "denied" / "auth_failure" | Built |
| Alerts and incident response | RIT; app side: Administration → Security → "Record an incident" (24h/72h report deadlines, email reminders), "Lock the app" | Built |

#### Speaker notes – Security, Access log, alerts (read this in the demo)

**Audit log vs Access log**
- Audit log (Administration → Audit log): who CHANGED what. Columns: Action, Entity, Record, Who, When. Nobody can edit or delete it. Never sends email.
- Access log (Administration → Access log): who READ, DOWNLOADED, EXPORTED, and who was REFUSED. Filter "What": read, download, export, denied, auth_failure, integrity.
- A single event never sends an email. It is only written to the log.

**Automatic watcher (scripts/access_alerts.py)**
- Runs on a schedule (should be an hourly Cloudera Job; not scheduled yet).
- Looks at the last 60 minutes (ALERT_WINDOW_MINUTES), counts events per person.
- Default limits (per person, per 60 min):

| Event | Default limit | Level | Setting |
|---|---|---|---|
| Downloads of identified files (real names) | 50 | high | ALERT_DOWNLOAD_LIMIT |
| Exports (Excel/CSV) | 5 | low | ALERT_EXPORT_LIMIT |
| Access denied | 15 | low | ALERT_DENIED_LIMIT |
| Failed logins (unknown / inactive user) | 10 | high | ALERT_AUTH_FAILURE_LIMIT |

- Critical: any rule at 3 × its limit (ALERT_CRITICAL_FACTOR = 3), e.g. 150 identified downloads, 30 failed logins.
- At critical (ALERT_LOCKDOWN_LEVEL = critical) the watcher LOCKS THE APP BY ITSELF, reason "Automatic: …".

**Who gets emailed** (fixed addresses in Cloudera settings, NOT by app role/permission, so a hacked account cannot turn alerts off)
- ALERT_EMAIL_TO → high + critical: Program Manager, app specialist, Host IT.
- ALERT_EMAIL_LOW_TO → low: app specialist (if empty, goes to ALERT_EMAIL_TO).
- Needs SMTP set up; without it emails are skipped (only logged).

**When emails go out**
| Event | Email |
|---|---|
| Watcher finds someone over a limit | Yes: low → LOW list, high/critical → main list |
| App locked (by a person or the watcher) | Yes, right away |
| App unlocked | Yes, right away |
| Incident recorded, level high/critical | Yes, with the 24 h and 72 h deadlines |
| Incident recorded, level low | No |
| 6 h before a report deadline (hour 18, hour 66) | "Due soon", once |
| Deadline passed, report not marked sent | "OVERDUE", once (only if no "Due soon" was sent) |

**Lock / unlock**
- Lock: Administration → Security → "Lock the app" → Reason + Level → "Lock now". Or automatic at critical.
- While locked: everyone without security:manage is blocked ("Hive is locked because of a security incident"). Red banner on every page.
- Unlock: from the red banner at the top, a reason is required, email sent. Lock and unlock are in the audit log.

**Incident (Administration → Security → "Record incident")**
1. Title, Level, Detected at, What happened → Record incident.
2. Deadlines: preliminary 24 h, full 72 h from "Detected at".
3. Fill Data affected, Risk assessment, Containment actions, Affected parties → Save.
4. "Report (.docx)" → send it yourself → "Mark sent" (24 h and 72 h).
5. "Close incident" (needs data affected, containment, full report sent).
- After 24/72 h the app only sends reminder emails. It does not send the report, lock the app, or close the incident.

**Permissions**
- security:view: see Security page, incidents, download report.
- security:manage: lock/unlock, record/close incidents, keep working while locked.

**Demo simulation (no Cloudera Job needed)**
1. Fake failed logins:
   `for i in 1 2 3; do curl -s -o /dev/null -H "REMOTE-USER: intruder-test" localhost:8100/patients; done`
2. Run the watcher, small limit, print only:
   `ALERT_AUTH_FAILURE_LIMIT=3 python scripts/access_alerts.py --window 60 --dry-run`
3. Show Access log → What = auth_failure → intruder-test rows.
4. Optional auto-lock (real lock; sends real emails if SMTP is set):
   `ALERT_AUTH_FAILURE_LIMIT=3 ALERT_CRITICAL_FACTOR=1 python scripts/access_alerts.py --window 60`
   Then unlock from the red banner.

**To do later**
- Create hourly Cloudera Jobs for scripts/access_alerts.py and scripts/incident_reminders.py.
- Set ALERT_EMAIL_TO, ALERT_EMAIL_LOW_TO and SMTP on Cloudera.

### Page 6 – §6.5 (end) Incident response, §6.6 Lineage, §6.7 Retention, §6.8 Training, §7 UBRS, §8 Code repository

| Item | Where in app | Status |
|------|--------------|--------|
| Automated notifications to CHSS Manager, App Specialist, RIT when breach detected | Watcher job scripts/access_alerts.py emails ALERT_EMAIL_TO (see speaker notes) | Built (job not scheduled yet) |
| Automated incident CREATION and tracking | Watcher emails and can lock, but does not create the incident record; a person records it in Security → "Record incident" | Partly (gap) |
| Gradual response: low → alert app specialist; high/critical → lockdown | Low → ALERT_EMAIL_LOW_TO; high/critical → automatic lock when ALERT_LOCKDOWN_LEVEL=high (default is critical) | Built (setting) |
| Breach report: time of detection, scope, risk, containment, affected parties | Security → incident → fields + "Report (.docx)" | Built |
| Preliminary report 24 h, full 72 h | Security → incident → deadlines, "Mark sent", reminder emails | Built |
| §6.6 Data lineage: track movements and transformations | Audit log (every change); workspace cleaning_log.csv; Zone 2 release archive id_map.csv, document_map.csv, original/ copies | Built |
| REDCap logs and data revision history | REDCap keeps its own log; §9.1.12 also asks for a copy: REDCap → Import a REDCap export → What = "Logging (audit trail)" (stored in its own table, not shown on a page yet) | Simulated |
| §6.7 Retention of logs, audit, backups | Cloudera/RIT; app logs are append-only | Not ours |
| Delete data on consent withdrawal / approved deletion | Rejected files can be purged; consent-withdrawal purge NOT built (known gap #1) | Missing |
| §6.8 Training: TCPS2, iLearn, US equivalent; proof kept by manager | Manual by CHSS Manager (no training field in app) | Manual |
| §7 UBRS: random 6-char alphanumeric code, nothing from identity or cohort | UBRS (Eena) assigns it; app reads the code from the file/folder name. Default pattern is 2–4 letters + 3–4 digits (e.g. AA1234); user confirmed the codes meet §7 | Built |
| §8 Code repository in RIT GitLab, 4 code bases | Developers commit and push by hand (terminal / IDE); the app never writes to git. New cleaning rules: edit cleaning/, commit, push, pull in Cloudera | Not ours (manual) |
| Code base 3: cohort-level processing incl. data corrections | cleaning/ folder (instrument/, cohort/ rules, applied when a workspace is built) | Built |
| Only CRQ senior staff commit to code bases 1–3 | GitLab permissions | Not ours |

### Page 7 – §9 Platform components, §9.1.1 Inbox storage blob, Figure 3

| Item | Where in app | Status |
|------|--------------|--------|
| Sites submit by SFTP | SFTP set up outside the app, lands in the intake folder (INTAKE_DIR) | Not ours (Cloudera/RIT) |
| One upload = one patient | App reads the patient code from each file's folder/name, so mixed uploads are still split per patient | Built (per file) |
| Malware scan on incoming files | Not built (decided 2026-10-13: skip for now) | Missing (decision) |
| Integrity check | SHA-256 checksum: identical files are caught as duplicates and excluded | Partly |
| Holding folder named site + UBRS + time | App files by patient code; app does not track sites | Deviation |
| Known patient: UBRS as filename prefix | De-Identifier reads the code from path/file name; allowed formats shown at the top ("Accepted patient codes") | Built |
| Known vs new patient | Code already in Zone 1 → Patients = known: file goes to that patient. Code not there = new: De-Identifier creates the patient + draft application automatically. Migration files all carry their final code (Cedric's decision), so no temporary code is needed | Built |
| New patient: site-specific temporary prefix (future enrolments without a code yet) | Not built; who assigns the final code (UBRS/Eena)? Ask Cedric | Open question |
| Email CRQ staff when new data processed | "Intake run finished" email after each De-Identifier run, to users whose role has "deidentifier:notify". (Optional "New intake files" email on arrival needs scripts/intake_notify.py as a Cloudera Job, not scheduled) | Built |
| Missing/incorrect UBRS → files deleted + submitter emailed | Set aside in De-Identifier → "Excluded", not deleted. Conflict: pick the right code in the app. No code / unsupported / duplicate: only "Retry" (site must re-send a fixed file). No Delete button, no "assign code". Staff, not the site, are emailed | Deviation / gap |
| Only the UBRS application reads the inbox, no human | Cloudera folder permissions on INTAKE_DIR | Not ours |
| Figure 3: PDF / Image / Temporary storage | storage/submitted_data (originals), de_identified (redacted), pending + abstraction folders (temporary) | Built |
| Figure 3: Primary DB, backup, cache | Hive tables in Cloudera; backup by RIT | Built / Not ours |

#### Reminders (from page 7)
- [ ] Sentence 7: create a Cloudera Job for scripts/intake_notify.py ("New intake files" email on arrival).
- [ ] Sentence 8 gap 1: "Delete" button for Excluded files (with reason, in audit log).
- [ ] Sentence 8 gap 2: "Assign code" for files with no code.
- [ ] Sentence 8 gap 3: email the submitting site (app does not track sites).

### Page 8 – §9.1.2 UBRS application

| Item | Where in app | Status |
|------|--------------|--------|
| Manages patient identity + contact info | Zone 1 → Patients (open / edit patient) | Built |
| Generates UBRS for new patients | Code comes from the files (Cedric's decision); new code → patient created automatically | Built (decision) |
| Built on Cloudera AI (CAI) | App runs as a CML application | Built |
| Access only for CRQ intake staff and manual follow-up staff | Administration → Roles | Built |
| Files taken from inbox (by patient, or oldest first automatically) | Zone 1 → De-Identifier → Start (all waiting files); staff pick a patient code when building an application | Built |
| Existing patient: check change-of-contact form, update info | Zone 1 → Patients → patient → Edit; CONTACT document type is detected | Built |
| New patient: document contact info, create patient | Created automatically; "Patient details not checked yet" banner in the application until staff confirm (asked once) | Built |
| Python extracts metadata: document type + date | Types: ENROLLMENT, CONTACT, CONSENT, OPERATIVE, DISCHARGE, ECHO_REPORT, ANGIO_REPORT, MRI_REPORT, ECG_REPORT, IMAGE, STS_EXTRACT, OTHER; DICOM date from tags | Built |
| Rename: UBRS + document type + date + 16-digit serial (unique) | Name = CODE-TYPE-DATE-SERIAL (serial = 13-digit time + 3-digit counter = 16 digits) | Built |
| Staff validate/correct type and date | Application → file menu → "Set type & date": "Document type / modality", "Document date", "Date unknown" | Built |
| Staff verify no identifiers | Application → file review (view de-identified copy, Reject) | Built |
| Enrolment checklist (4 points) | Application → Submit → "Enrollment checklist": All required files were submitted / The patient is eligible / The right consent form is present / No identifiers were found | Built |
| Reject if a point fails | Cancel checklist → Reject → "What failed?" + Reason | Built |
| Site coordinator emailed on rejection with reason (+ UBRS for 1, 3, 4) | Staff with deidentifier:notify emailed, not the site (no sites in app) | Deviation (= page 7 gap 3) |
| Rejected for 2 (not eligible) → all data purged | Built: point 2 deletes all documents | Built |
| Rejected for 1, 3, 4 → inbox files deleted | Files kept in Zone 1 → Rejections so they can be replaced | Deviation |
| Add filename to every PDF page | App stamps the PATIENT CODE (not the full file name) on every page at submit | Partly |
| Generate metadata for PACS images; images to PACS | JPG/PNG converted to DICOM with the code; stored in the app's image folder, no PACS | Partly / Not ours |
| PDFs / images / structured data stored by type | Originals, de-identified, data files folders | Built |
| Metadata stored for search | Zone 1 → Metadata (search + Excel export) | Built |
| Migration: master patient index, batch enrol | Zone 1 → Patients → "Import" (Excel/CSV) | Built |
| Migration: process all PDFs/images automatically | Zone 1 → De-Identifier → Start | Built |
| Future: first submission needs info validation | "Patient details not checked yet" → confirm once | Built |
| Sites not sharing records: no records/no ID option, no missing-info queries | Patients → Edit → "Site does not share records or contact details" | Built |
| No data entry without a valid UBRS | Files with no code are Excluded; REDCap → "New patient codes (to REDCap)" | Built |

#### Reminders (from page 8)
- [ ] Make practice patient-import Excel: 10 AVSD codes, fake identifiers, same columns as Patients → Import → "Download template". Codes must match the file names.

#### Storage folders (corrected)
| Stage | Folder |
|---|---|
| Inbox (SFTP) | storage/incoming_data/ |
| After De-Identifier, application still draft (waiting for staff Submit) | storage/pending_data/original/<CODE>/, storage/pending_data/de_identified/<CODE>/ |
| Failed / Excluded | storage/pending_data/failed/, storage/pending_data/needs_attention/ |
| After Submit (final) | storage/submitted_data/original/<CODE>/, storage/submitted_data/de_identified/<CODE>/ |
| Files uploaded by hand in an application (not via De-Identifier) | storage/submitted/<CODE>/original/, storage/submitted/<CODE>/de_identified/ |

#### REDCap pipeline today (simulated with files)
IN (REDCap → app):
1. Someone with REDCap access exports 3 CSVs from the REDCap project: Data dictionary, Records (raw), Logging.
2. App → Zone 1 → REDCap → "Import a REDCap export": What = Data dictionary, Dataset = avsd_clinical, file → Preview → Import. Then Records. (Logging optional.)
3. Records whose code is not a patient in the app are skipped and listed (sample AVSD9999 shows this).
4. Data goes into the project workspace (redcap_avsd_clinical.csv) and Zone 2 release (only coded / number / date fields, never identifier or free-text fields).
   Alternative: put the CSVs in REDCAP_DROP_DIR and run scripts/redcap_sync.py (simulates the nightly sync).
OUT (app → REDCap):
5. "New patient codes (to REDCap)" → Download CSV → upload in REDCap Data Import Tool (creates empty records with valid codes).
6. "Follow-up list (to REDCap)" → Download list (Excel): automated (online survey) / manual / not-contacted lists.
LATER: set REDCAP_URL + one token per dataset → the same sync uses the API, no files.

### Page 9 – Figure 4 (UBRS workflow), §9.1.3 Archival PDF storage blob

| Item | Where in app | Status |
|------|--------------|--------|
| Figure 4 = same zone flow as Figure 1 (site upload → UBRS app → primary storage → Zone 1X → Zone 2) | See page 3 row | Built |
| Archive stores all PDFs, incl. historical | storage/submitted_data/original/<CODE>/ (originals after Submit) | Built |
| Name = UBRS + type + date + 16-digit serial | CODE-TYPE-DATE-SERIAL | Built |
| Old documents not systematically de-identified; vetted at abstraction; inactive cohorts not re-done | Migration files still go through De-Identifier; staff check in review | Built (does more than asked) |
| UBRS app copies new files into the archive | Submit moves originals to submitted_data/original | Built |
| Archive needs specific permission | Role permission "files:view_original" + a per-file grant once the application is submitted | Built |
| Only the CHSS Manager grants it | Permission "files:grant_original" (give it only to the manager's role) | Built |
| Only for files suspected damaged by redaction | Application → file menu → "Access to the original…" → "Give access to" + "Why"; dialog text says use only when the redacted copy looks damaged | Built |
| Every grant and every opening logged | Audit log (grant) + Access log (opening, Identified = yes; refusal = denied) | Built |

### Page 10 – §9.1.4 Automated PDF PHI redaction, Figure 5, §9.1.5 Active PDF storage, §9.1.6 Abstraction temporary storage, §9.1.7 Manual redaction (start)

| Item | Where in app | Status |
|------|--------------|--------|
| All PDFs go through automated redaction | Zone 1 → De-Identifier → Start (PDF, DICOM, Word) | Built |
| Python finds PHI in typed and handwritten text, with locations | OCR pipeline (OCR/ folder): text + boxes per page | Built (handwriting: only as well as PaddleOCR reads it) |
| OCR with PaddleOCR | PP-OCRv6 detection + recognition | Built |
| Presidio + spaCy en_core_web_sm + StanfordAIMI stanford-deidentifier-base | Stage 2 of the pipeline | Built |
| Redaction with MuPDF | Text under the box is removed, not just covered; metadata cleaned | Built |
| "_R" suffix on auto-redacted file | Yes ("_RR" for manual re-redaction) | Built |
| Redacted PDF = approved version for abstraction and analysis | De-identified copy used everywhere downstream | Built |
| Figure 5: REDCap → API Management → Functions → Logic App → Cloudera/Blob | This is the REDCap API path (caption looks wrong); simulated with files (see REDCap pipeline) | Simulated |
| §9.1.5 Active PDF storage = all redacted PDFs, main source | storage/submitted_data/de_identified/<CODE>/ | Built |
| §9.1.6 Whole active storage only for senior analysts | Permission to see all files (Zone 1 → Files) only for senior roles | Built |
| Copy needed files to a temporary folder, chosen by metadata | Zone 1X → Abstraction folders → "New abstraction folder": Patient codes, Types / modalities, Document date from/to, Text in file name or metadata, File types | Built |
| Access only for the end user | Folder is per user, read-only copy | Built |
| Assign folder to a user and/or project | "Assign to" a user: built. To a project: NOT built (known gap #4) | Partly |
| Delete when task is done | Folder menu → "Delete" | Built |
| Auto-delete after 3 months unless extended | 90 days (ABSTRACTION_EXPIRY_DAYS); "Extend 90 days"; deletion runs in scripts/abstraction_cleanup.py → needs a daily Cloudera Job (not scheduled) | Built (job missing) |
| Can be regenerated | Deleted folder record stays, folder can be made again | Built |
| No new data in temporary folders | Read-only copy | Built |
| §9.1.7 Manual redaction with Adobe Pro | Rejections → "Replace de-identified copy" (file gets "_RR") — rest on next page | Built |

#### Reminders (from page 10)
- [ ] Create daily Cloudera Jobs: scripts/abstraction_cleanup.py and scripts/workspace_cleanup.py (otherwise expired folders/workspaces are never deleted).
- [ ] Known gap #4: assign an abstraction folder to a project.

### Page 11 – §9.1.7 (end) Manual redaction, §9.1.8 Image storage, §9.1.9 Image retrieval + leading, §9.1.10 Primary DB, §9.1.11 Backup, §9.1.12 REDCap import APIs

| Item | Where in app | Status |
|------|--------------|--------|
| Manual redaction: extra "R" → "_RR", re-upload, redaction status updated | Rejections → "Replace de-identified copy" → file named _RR, record updated, old copy fingerprint in audit log | Built |
| §9.1.8 DICOM header de-identification | De-Identifier cleans DICOM tags, removes private tags, blacks out text burned into pixels | Built |
| Non-DICOM images converted to DICOM with metadata | JPG/PNG/TIFF/BMP/GIF → DICOM with patient code, modality, date | Built |
| Placeholder values when metadata missing | Modality OTHER / date UNKNOWN, staff fix with "Set type & date" | Built |
| DICOM metadata kept for search/retrieval | Zone 1 → Metadata | Built |
| §9.1.9 List images of interest by metadata → temporary folder | Zone 1X → Abstraction folders → "New abstraction folder" | Built |
| Purpose-built script to update metadata | scripts/update_file_metadata.py <spreadsheet> (dry run, then --apply; writes audit log) | Built |
| Leaded images: mark in metadata, keep in Zone 1 / 1X, not Zone 2 | Application → file menu → "Mark as leaded" → red badge "leaded · not for Zone 2"; blocks Zone 2 prepare/approve. Bulk: "Leaded" column in update_file_metadata | Built |
| §9.1.10 Primary DB in Cloudera | Hive tables in Expedition | Built |
| Only approved apps/scripts change data; humans by role | App + scripts write; users by Roles | Built |
| Data definitions + validation rules | REDCap data dictionary (decides safe fields); import checks (Preview); patient import checks | Built |
| Extraction includes data definitions | data_dictionary.csv in every Zone 2 release; "Data dictionary" sheet in Excel exports | Built |
| §9.1.11 Backup / restore | Cloudera / RIT | Not ours |
| §9.1.12 Nightly Python REDCap import APIs | scripts/redcap_sync.py: today reads files from REDCAP_DROP_DIR; with REDCAP_URL + token per dataset → API. Needs a nightly Cloudera Job | Simulated (job missing) |
| Import REDCap metadata (data dictionary) | REDCap → Import → What = "Data dictionary" | Simulated |

#### Reminders (from page 11)
- [ ] Nightly Cloudera Job for scripts/redcap_sync.py (once API or drop folder is ready).

### Page 12 – §9.1.12 (end), §9.1.13 QC script, §9.1.14 Manual follow-up, §9.1.15 Automated follow-up, §9.2 Zone 1X, §9.2.1 Cohort explorer

| Item | Where in app | Status |
|------|--------------|--------|
| REDCap metadata incl. record creation/update, query log, variable history | REDCap → Import → What = "Logging (audit trail)" (+ Data dictionary) | Simulated |
| §9.1.13 Automatic Python QC script after each import | scripts/qc_check.py (17 rules: P01–P07 patients, A01–A02 applications, D01–D06 documents, C01–C02 consent). Run by hand or as a Job; NOT triggered after import | Partly (job missing) |
| Missing critical variables, logical contradictions | e.g. P01 date of birth missing, P02 death before birth, D03 document before birth | Built |
| Conflicting information between sources (e.g. app vs REDCap) | Not checked (rules do not read REDCap data) | Missing |
| PDF report per cohort, sent to designated staff | qc-report.pdf + qc-report.xlsx in REPORTS_DIR, email to QC_EMAIL_TO; ONE report for all cohorts | Partly (not per cohort) |
| Query suppression engine | storage/qc/suppressions.csv (rule, record, reason, by, date); suppressed issues listed in their own sheet; stale suppressions counted | Built |
| §9.1.14 Manual follow-up list (not eligible for automated) | REDCap → "Follow-up list (to REDCap)" → "Download list (Excel)" → sheet "Manual" (with why) | Built |
| Manual: pull identifiers/contact, personalized printable forms, copy to follow-up storage | Not built (only the list) | Missing |
| §9.1.15 Check alive + not withdrawn | Follow-up eligibility | Built |
| 3 criteria: latest consent version, recent site follow-up, online preference (in consent matrix) | "Latest consent version", "Recent follow-up from the site (days)" fields → Check | Built |
| Failures → manual list; rest → automated with email + first name | Sheets "Automated" / "Manual" / "Not contacted" | Built |
| Consent update needed (e.g. turning 18, transfer of responsibility) | consent_update column in Automated sheet | Built |
| Personalized REDCap link + invitation email via REDCap email API | survey_link empty until API is connected | Simulated |
| Runs periodically | Today on demand (button); no scheduled job | Partly |
| §9.2 Each project has its own Zone 1X, only approved people | Zone 1X → Projects → project → "Members"; workspace in PROJECTS_DIR/<code>/workspace/ | Built (folder access on Cloudera pending storage meeting) |
| §9.2.1 Cohort by named cohort or inclusion/exclusion criteria | Project → "Patients" card: Cohort (code prefixes), Registered from/to, Age at registration from/to, Institution codes, Countries, States / provinces, Has documents of type or modality, Document dated from/to, Exclude these codes, Living patients only | Built |
| Consent matrix removes unauthorized patients | Refused/withdrawn consent blocks the patient from cohort/workspace/prepare (Zone 1X → Consent matrix) | Built |

#### Reminders (from page 12)
- [ ] QC: Cloudera Job for scripts/qc_check.py (or run after each import); set QC_EMAIL_TO.
- [ ] QC: one report per cohort (known partial).
- [ ] QC: checks between sources (app vs REDCap).
- [ ] Manual follow-up: personalized printable forms + follow-up storage folder.
- [ ] (Optional, asked page 11) "Bulk corrections" button on Metadata page instead of running scripts/update_file_metadata.py by hand.

#### Note (page 12): REDCap logging import
- REDCap's log rows go to their OWN table (redcap_log), not into the app's Audit log.
- The Audit log gets ONE row per import ("CREATE redcap_log", who, file name, counts).
- No page shows the REDCap log rows yet (only the count in "Datasets in the app"). Possible later: a "REDCap log" view or merge into Audit log.

#### Questions to ask Cedric tomorrow (follow-up, §9.1.14 / §9.1.15)
1. Do we need follow-up now, or after the REDCap API and outside access (patient portal) are ready?
2. Manual follow-up (§9.1.14): what goes on the personalized form (which questionnaire / consent version)? Printed by whom? Where is the follow-up storage folder?
3. Automated follow-up (§9.1.15): how often should it run (monthly, yearly per patient)? Who sends the email: REDCap email API only, or the app?
4. Where is the "prefers online follow-up" choice recorded today, and the latest consent version number?
5. "Recent follow-up from the site": how many days counts as recent (default 365)?
6. Today: the app only produces the Excel lists (Automated / Manual / Not contacted). Is that enough for the first phase?

### Page 13 – §9.2.1 (end), §9.2.2 Project storage, §9.2.3 Analysis-ready script, §9.2.4 Zone 2 data preparation

| Item | Where in app | Status |
|------|--------------|--------|
| Project-specific storage with the patients' PDFs and images (if needed) | Project → "Workspace (Zone 1X)" → tick "Copy the PDFs and images" → "Build workspace" | Built |
| Standard tables extracted from the database | Workspace: patients.csv, applications.csv, documents.csv, redcap_<dataset>.csv | Built |
| Cleanup scripts at cohort level and instrument level applied | cleaning/cohort/<PREFIX>.py, cleaning/instrument/<table or MODALITY>.py; cleaning_log.csv | Built |
| §9.2.2 Provisioned by App Specialist / Manager, with access | "Build workspace" needs permission project:workspace; folder PROJECTS_DIR/<code>/workspace/ (Cloudera access pending storage meeting) | Built |
| 90-day retention unless extended by approval | Workspace expiry 90 days; "Extend 90 days" asks which approval (goes to audit log); auto-delete needs daily Job scripts/workspace_cleanup.py | Built (job missing) |
| §9.2.3 Exploration: distributions, outliers, frequency tables | profile.xlsx in every workspace (summary per column: missing, distinct, lowest, highest, mean; frequencies; outliers) | Built |
| Correction rule 1: single error → fix at source (REDCap) | Process; app does not change source data | Process |
| Correction rule 2: recurring → code in cohort explorer/dataset builder | cleaning/ rules | Built |
| Correction rule 3: analysis-specific → analysis-ready script | Analysts write their own script (template dropped by decision) | Process |
| Never correct in Excel | Rules are code in GitLab, logged | Built |
| Analysis-ready data dictionary | data_dictionary.csv in every Zone 2 release | Built |
| §9.2.4 Zone 2 prep script applied to every release | Project → "Safe copy (Zone 2)" → "Prepare safe copy" | Built |
| 1) Remove remaining PHI (e.g. date of birth) | Names, addresses, phones, emails, DOB left out; age at registration instead | Built |
| 2) Date shift: one random whole number per patient between -1826 and +1826 days | Per patient, kept in id_map.csv, applied to all dates incl. DICOM | Built |
| 3) Remove all free-text fields | Only coded / number / date fields go (data dictionary decides) | Built |
| 4) Delete PDFs/images from project storage unless approved | Not copied to Zone 2 unless "Approved for documents (PDFs and images)"; workspace copies NOT deleted after release (known gap #3) | Partly |
| 5) Project-specific patient IDs | project_patient_id, different from CHSS code | Built |
| Archive original + ID map + approved data | PROJECTS_DIR archive: original/, id_map.csv, application_map.csv, document_map.csv | Built |
| Copy approved data to Zone 2 inbox | Zone 2 → "Zone 2 inbox" → review → "Send back" or "Release to Zone 2" | Built |

#### Finding (page 13): Zone 2 safe copy does NOT use the cleaned workspace
- "Prepare safe copy" reads straight from the database; the cleaning rules (cleaning/) are NOT applied, and nothing the analyst produced in the workspace is used.
- So in Zone 2, country may still be "CAN" while the workspace says "Canada".
- Protocol: clean in Zone 1X, then move to Zone 2. → Build: apply cleaning.apply() in Zone 2 prepare (and decide whether analyst outputs from the workspace can be released).

#### Reminders (from page 13)
- [ ] Zone 2 prepare should apply the cleaning rules (finding above).
- [ ] Question for Cedric: which extra metadata fields (if any) should go to Zone 2 documents.csv?
- [ ] Question for Cedric: should the analyst's analysis-ready output (from the workspace) be what goes to Zone 2?

### Page 14 – Figure 6 (Zone 2 flow), §9.3 Zone 2, §9.3.1 Inbox, §9.3.2 VMs, §9.3.3 Images/PDFs in Zone 2, §9.3.4 SAS 9.4, §9.4 Zone 3 SharePoint

| Item | Where in app | Status |
|------|--------------|--------|
| Fig 6: Request received → Check approvals | New project; "Prepare safe copy" refuses until it has an approval reference, consent confirmed, at least one patient | Built |
| Incomplete → return to requester | Done by the manager outside the app (button stays disabled, says what is missing) | Manual |
| Define cohort → Check consent | Project → "Patients" card; consent matrix blocks refused/withdrawn; "Patient consent confirmed" box | Built |
| Extract data → Clean data | "Build workspace" (tables + cleaning rules) | Built (Zone 2 prep does not reuse the cleaning, see page 13 finding) |
| Zone 2 prep → Remove PHI → Shift dates → Create project IDs | "Prepare safe copy" | Built |
| Manager review → Approve: release / Reject: revise | Zone 2 → "Zone 2 inbox": open, spot-check, "Flag", "Send back" or "Release to Zone 2" | Built |
| §9.3.1 Inbox = isolated area during review by Manager / data manager | storage/zone2_inbox/<project>/<release>/; permission zone2:review | Built |
| Check no identifiers + prep applied | Inbox shows tables (first 5 rows) and documents; spot-check + Flag | Built |
| §9.3.2 Standard analysis VMs (Anaconda, R, Python, GitLab, O365) | Cloudera CML sessions (no Azure VMs) | Not ours |
| Custom VMs, GPU, SAS Viya | Cloudera / RIT | Not ours |
| §9.3.3 Images/PDFs to Zone 2 only with demonstrated need and full review | "Approved for documents (PDFs and images)" box; spot-check + Flag in inbox; leaded files block release | Built |
| §9.3.4 Desktop SAS 9.4 linked to project storage | Outside app | Not ours |
| §9.4 Zone 3 SharePoint, no PHI, Entra ID | Outside app | Not ours |

#### Reminders (from page 13/14)
- [ ] (Optional, no answer yet) scripts/try_cleaning_rule.py: run one cleaning rule on a workspace CSV and show before/after.

### Page 15 – §9.5 Zone 4: REDCap consent & contact matrix, clinical datasets, periodic follow-up, email/survey tool, Figure 7

| Item | Where in app | Status |
|------|--------------|--------|
| §9.5.1 Consent matrix lives in REDCap, machine readable | Copy in app: Zone 1X → Consent matrix ("Import from a spreadsheet" = REDCap export; or scripts/redcap_sync.py reads consent.csv) | Simulated |
| Consent status + version per patient | Types: research, documents, online_followup; status: granted / refused / withdrawn; version; date | Built |
| Specific permissions/restrictions from the forms | Only these 3 types today; more types can be added | Partly |
| Applied to abstraction | Refused/withdrawn blocks cohort, workspace and Zone 2 prepare; online_followup used by follow-up list | Built |
| Contact information | Kept in Zone 1 → Patients (contact fields) | Built |
| Sites enter their own data via data access groups | REDCap side | Not ours |
| Extracted with custom REDCap import API | Simulated with file import | Simulated |
| §9.5.2 One REDCap clinical dataset per active cohort | REDCap → Import, Dataset = avsd_clinical (one dataset per cohort) | Simulated |
| §9.5.3 Standard periodic follow-up questionnaire (consents, 18-year transition, health status, PedsQL, CHQ, ASQ, DASS21, SCORE15) | Built in REDCap, not in app | Not ours (future) |
| §9.5.4 REDCap email client + survey tool, personalized link | REDCap; app only makes the list (Follow-up list) | Future |
| Figure 7 Patient follow-up workflow | Same logic as §9.1.15 (Follow-up list: Automated / Manual / Not contacted) | Built (lists only) |


---

## Before the demo (tonight / tomorrow morning)

- [ ] Work laptop: copy the latest code, run `python scripts/migrate_columns.py` then `--apply`, restart backend and frontend (otherwise pages show "The database did not answer as expected").
- [ ] Work laptop: give your role the new permissions in Administration → Roles (REDCap exchange: View / Import / Export; check Consent, Project, Zone 2, Security rows too).
- [ ] Work laptop: PATIENT_CODE_FORMATS must allow the real codes of the 10 patients (e.g. add `AVSD:4`). On this laptop it is `AA:4,BBCDE:4`, so AVSD codes are refused by Patients → Import and the De-Identifier.
- [ ] Patient import file: practice file `demo/avsd-practice-patients.xlsx` (10 AVSD codes, fake identifiers, 3 rows with country CAN/CA to show the cleaning rule). For the real demo use the same columns with the real identifiers; codes must match the file names.
- [ ] REDCap sample files ready: `Sample/redcap/avsd_clinical/dictionary.csv`, `records.csv`, `log.csv`, `Sample/redcap/consent.csv`.
- [ ] Optional: practice the security simulation (speaker notes under page 5).

## Suggested demo order (≈ 90 min)

| Min | Step | Where | Protocol |
|---|---|---|---|
| 5 | Zones and the river picture | Left menu groups; Figure 1 | §5 |
| 10 | Goal A – master patient index | Zone 1 → Patients → Import → Preview → Import | §9.1.2 migration |
| 15 | Goal B – files through the De-Identifier | Zone 1 → De-Identifier → Start; Excluded / Failed cards; Files; Metadata | §9.1.1–9.1.8 |
| 10 | Review + 4-point checklist | Applications → open → "Set type & date", view de-identified, "Mark as leaded" → Submit → Enrollment checklist | §9.1.2, §9.1.9 |
| 5 | Archived originals | "Access to the original…" grant; Access log | §9.1.3 |
| 10 | REDCap (simulated) | REDCap: dictionary → records → log; Follow-up list "Check"; New patient codes | §9.1.12, §9.1.15, §9.5 |
| 5 | Consent | Consent matrix: import consent.csv, set one patient withdrawn | §9.5.1 |
| 15 | Goal C – Dom's project | Projects → New → approval reference, consent confirmed, Members → Patients (Cohort AVSD) → Build workspace (profile.xlsx, cleaning_log.csv) → Prepare safe copy | §9.2 |
| 5 | Zone 2 review | Zone 2 inbox → spot-check / Flag → Release to Zone 2; show id_map.csv | §9.2.4, §9.3.1 |
| 5 | Security and logs | Audit log, Access log, Security (incident), QC report (`python scripts/qc_check.py --no-email`) | §6.5, §9.1.13 |
| 5 | Gaps and next steps | Build-later list below | — |

## Build-later list (all gaps found in the review)

Jobs and settings (no code needed)
- [ ] Cloudera Jobs: `scripts/access_alerts.py` (hourly), `scripts/incident_reminders.py` (hourly), `scripts/intake_notify.py` (every 15–60 min), `scripts/abstraction_cleanup.py` (daily), `scripts/workspace_cleanup.py` (daily), `scripts/redcap_sync.py` (nightly), `scripts/qc_check.py` (after imports / nightly).
- [ ] Settings: ALERT_EMAIL_TO, ALERT_EMAIL_LOW_TO, QC_EMAIL_TO, SMTP; ALERT_LOCKDOWN_LEVEL=high if high threats should lock too (§6.5).

Code
- [ ] Zone 2 member access expiry: "Access expires on" (+6 months) per project member, "Extend" with approval, nightly removal (§5).
- [ ] Watcher creates the incident record automatically (§6.5).
- [ ] Consent withdrawal → delete the patient's documents, copies and metadata; keep patient, consent row, logs; list projects already in Zone 2 (§6.7, known gap #1).
- [ ] De-Identifier Excluded list: "Delete" button, "Assign code" for no-code files, email to the submitting site (§9.1.1).
- [ ] Zone 2 prepare should apply the cleaning rules (finding, page 13).
- [ ] Delete workspace PDFs/images after release (§9.2.4, known gap #3).
- [ ] Abstraction folder → project (§9.1.6, known gap #4).
- [ ] Excel / registry extracts from sites: accept and store (known gap #2).
- [ ] QC: one report per cohort; checks between sources (app vs REDCap) (§9.1.13).
- [ ] Manual follow-up: personalized printable forms + follow-up folder (§9.1.14) – future.
- [ ] REDCap log viewer page (§9.1.12) – optional.
- [ ] "Bulk corrections" button on Metadata page (instead of the script) – optional.
- [ ] `scripts/try_cleaning_rule.py` to test a rule on a CSV – optional.
- [ ] Virus scan of incoming files (§9.1.1, skipped by decision).
- [ ] Sites in the app: holding folder site + code + time, temporary site code for new patients (§9.1.1) – deviation by design.
- [ ] Stamp the full file name (not only the code) on every PDF page; PACS (§9.1.2) – deviation.

## Questions for Cedric

1. Follow-up (§9.1.14 / 9.1.15): now or after the REDCap API and outside access? Is the Excel list enough for phase 1? (6 detailed questions under page 12.)
2. Future new patients without a code: who assigns the final code (UBRS / Eena)?
3. Consent forms: any restrictions besides research / documents / online follow-up?
4. Zone 2: which extra metadata fields (if any) should go to documents.csv?
5. Zone 2: should the analyst's own output from the workspace be what is released?
6. Zone 2 access expiry: automatic every 6 months (as the protocol says) or manual?
7. Bad intake files: delete them (protocol) or keep them to fix (today)? Should sites get the rejection email?
8. Zone 2 / workspace folder access on Cloudera: outcome of the storage meeting.
