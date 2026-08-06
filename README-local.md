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
             # PRINTS THE admin + viewer USER IDS -- copy them, they are
             # the X-User-Id values the API authenticates with.
make verify  # prove INSERT/SELECT/DELETE (ACID) works on ORC
make run     # start the FastAPI app on CDSW_APP_PORT (8100)
make test    # run pytest suite (FastAPI app tests)
```

Expected timings:
- `make up`: container starts in seconds, but HiveServer2 itself isn't
  ready for ~60-120s while Derby initializes. `make check` will fail with a
  connection error during that window -- retry it rather than assuming
  something is broken.
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
| `file_metadata` | one row per file, holding metadata extracted at upload time (PDF / DICOM / Word) as JSON-in-STRING. Schemaless on purpose — a DICOM study and a Word document share almost no fields |
| `patient_applications` | one submission of a patient + their documents for review; holds who did what and when |
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

All of them are gated on `application:*` rather than `patient:*`: these
files are part of a submission, so anyone who may read an application may
read its documents. A patient's documents are reached through their
applications.

### Auth and permissions

Every endpoint except `/health` requires an `X-User-Id` header naming an
active user, and the permission `<model>:<action>` (e.g. `user:view`,
`patient:delete`) on that user's role. Missing/unknown user -> 401;
missing grant -> 403.

The 20 grants are the product of five models -- `user`, `patient`,
`role`, `log`, `application` -- and four actions: `view`, `create`,
`update`, `delete`. Both tuples live in `app/security.py`, and
`scripts/init_db.py`, the test fixtures and the frontend's
`schemas/common.ts` all derive from them rather than restating the list.

**`X-User-Id` is a deliberate local stand-in.** No auth scheme was
specified, and on Cloudera AI the authenticated principal arrives from the
platform (Kerberos/Knox). Swapping it means changing only
`_current_user_id` in `app/security.py` -- routes and permission strings
are unchanged, so nothing branches on environment.

`make init` seeds two roles and prints their user ids: **admin** (all 20
permissions) and **viewer** (read-only). Use those as `X-User-Id`:

```bash
curl -H "X-User-Id: <admin-id>" http://localhost:8100/users
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

**`TSocket read 0 bytes` immediately on connect**
The server is rejecting the transport, not just being slow. The
`apache/hive:4.0.0` image's default `hive.server2.authentication` is
`NONE`, which HiveServer2 still speaks over SASL PLAIN -- incompatible
with impyla's `NOSASL` mode. `conf/hive-site.xml` in this repo already
sets `hive.server2.authentication=NOSASL` to fix this; if you see this
error, confirm that file is still mounted (`docker exec hive-local grep
authentication /opt/hive/conf/hive-site.xml`) and wasn't dropped by an
unrelated compose change.

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
