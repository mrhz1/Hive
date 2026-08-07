# Hive Admin dashboard

React + TypeScript dashboard for the FastAPI/Hive service. No login
screen: it asks the API who the caller is and renders from the
permissions that come back.

## Stack

Vite · React 19 · TypeScript · TanStack Query · TanStack Router ·
react-hook-form · zod · Tailwind v4 · axios · sonner · ESLint · Prettier ·
Vitest

## Running it

```bash
# 1. the API must be up first (from the repo root)
make up && make check && make init     # note the admin id it prints
make run                               # FastAPI on :8100

# 2. point the dashboard at a user, then start it
cd frontend
cp .env.example .env.local             # set VITE_DEV_USERNAME
npm install
npm run dev                            # http://localhost:5173
```

`make init` seeds an **admin** (all 20 permissions) and a **viewer**
(read-only). Put one of those usernames in `VITE_DEV_USERNAME` as the
starting identity.

### Switching user to test RBAC

Use the **Switch user** button in the header. It lists the users the
current caller can read, switches to the one you pick, and reloads — no
dev-server restart, because the identity is resolved per request rather
than baked in at startup. There is also a field for typing a username,
for when the current role cannot list users.

"Reset to .env.local user" drops the override and returns to
`VITE_DEV_USERNAME`.

Switching to the viewer is the quickest way to see RBAC working: the
create/edit/delete buttons disappear, the Actions column goes with them,
and `/users/new` renders the 403 page.

The switcher only exists when `VITE_DEV_USERNAME` is set. On Cloudera AI
it is unset, the platform supplies the identity, and the button never
renders — the same configuration switch that decides whether a
`REMOTE-USER` header is sent by the app at all. It grants nothing extra
locally either: the API already trusts that header in this environment,
so this is just a faster way to do what editing `.env.local` did.

### Scripts

| command | does |
|---|---|
| `npm run dev` | dev server with HMR |
| `npm run build` | typecheck then production build |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | ESLint |
| `npm run test` | Vitest (unit) |
| `npm run test:e2e` | Playwright (needs the API + dev server running) |
| `npm run format` | Prettier |

### Running the e2e tests

They drive a real browser against a real API and create/delete their own
records, so both the API and `npm run dev` must be up first.

This WSL image is missing `libasound.so.2`, which Playwright's Chromium
needs, and installing it system-wide requires root. It is extracted
locally instead, so no `sudo` and no change to the machine:

```bash
mkdir -p ~/.local/pwlibs && cd ~/.local/pwlibs
apt-get download libasound2t64 && dpkg -x libasound2t64_*.deb .

cd frontend
LD_LIBRARY_PATH=~/.local/pwlibs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH \
  npm run test:e2e
```

Without that prefix the browser fails to launch and every test errors
with `error while loading shared libraries: libasound.so.2`.

## How identity works

There is no auth in this app by design. `VITE_DEV_USERNAME` is sent as
`REMOTE-USER`, the same header `app/security.py` reads. On Cloudera AI the
platform authenticates the user and sets that header itself, so the
variable is left unset and the API resolves the caller — the app only ever
asks `GET /me`.

Swapping the source of identity means changing `_current_username` in the
backend. No frontend code branches on environment.

Two endpoints were added to the API for this dashboard:

- `GET /me` — current user with `role_name` and `permissions` joined in.
  No permission required, or the shell could not boot.
- `PUT /me` — self-service profile edit. Deliberately **not** gated on
  `user:update` (editing your own name should not require the right to
  edit everyone), so it accepts only `first_name`/`last_name`/`email` —
  never `role_id`, `status` or `is_active`. Otherwise it would be a
  privilege-escalation path.

## Architecture

```
src/
  schemas/      zod schemas -- the single source of truth for types
  lib/api/      axios client, error normalisation, typed resource calls
  lib/          queryClient (cache policy), queryKeys, cn
  hooks/        query/mutation hooks, permissions, theme, forms
  components/   reusable UI: DataTable, ConfirmDeleteModal, fields, shell
  features/     per-model forms (one form serves create AND edit)
  routes/       file-based routes
```

Types are derived from zod (`z.infer`), never hand-written alongside it,
so a schema change cannot leave a stale type behind. Responses are parsed
at the boundary in `lib/api/resources.ts` — a backend shape change fails
loudly there instead of surfacing as `undefined` inside a component.

### Caching

`staleTime` is 60s because a Hive-backed list query costs seconds, not
milliseconds; reads are served from cache across navigation rather than
refetched on every mount. `refetchOnWindowFocus` is off for the same
reason. Freshness comes from explicit invalidation, not short TTLs:

- user/patient writes → invalidate that resource **and** `logs` (writes
  produce audit rows in the background)
- role writes → invalidate `roles`, `users` and `me`, because a role
  change alters what users may do and user reads embed role data

Query keys are hierarchical, so invalidating `['users']` refreshes the
list and every user detail in one call.

### Reuse

- **`DataTable`** is the only table. It renders a real `<table>` from
  `sm` up and a stacked card list below it from one column definition —
  a horizontally scrolling table is unusable on a phone, and duplicating
  markup per page would drift.
- **`ConfirmDeleteModal`** is the only delete dialog, driven by
  `useDeleteDialog`. Built on `<dialog>` so focus trapping and Esc come
  from the platform.
- **One form per model, serving both create and edit.** The route passes
  a record or nothing; `FormLayout` derives the copy.
- **`createCrudHooks`** generates the five query/mutation hooks per
  resource, so cache and toast behaviour is written once.

### Validation

`mode: 'onChange'` + `reValidateMode: 'onChange'` means an error appears
as soon as a character makes a value invalid and clears as soon as it is
valid. Submit revalidates everything, so untouched empty required fields
are caught too. Errors render directly under their input, wired with
`aria-invalid`/`aria-describedby`.

Server rejections are pinned to the field that caused them: a 422 carries
per-field messages, and a 409 uniqueness conflict is matched back to its
input by `applyServerErrors`, so "Username 'jdoe' already exists" appears
under Username rather than only in a toast.

### RBAC

`Can` hides an action; `RequirePermission` renders the 403 page instead
of a route body; the sidebar filters itself from `NAV_ITEMS`. The
dashboard also skips fetching lists the user cannot read, so no request
is fired that is guaranteed to 403.

**This is presentation only.** The API enforces every permission
server-side on every call. Hiding a button avoids a pointless request and
a confusing error; it is not the security boundary.

## Verification status

`npm run typecheck`, `npm run lint`, `npm run test` (21 tests) and
`npm run build` all pass.

Verified against a live API (Hive in Docker + FastAPI), rendered in
headless Chrome:

- dashboard loads real counts (20 users / 10 patients / 2 roles) and all
  20 permissions for the admin role
- users table renders all rows with `role_name` inlined from the join
- switching `VITE_DEV_USERNAME` to `viewer` removes the "New user"
  button, the per-row edit/delete buttons and the whole Actions column
- `/users/new` as viewer renders the 403 page naming `user:create`
- an unknown path renders the 404 page
- profile page shows the account panel with the viewer's four grants
- audit log lists a background-written CREATE entry, and its detail page
  round-trips the JSON-in-STRING values with `Before: None` for a create

Three bugs were found and fixed during this pass: the 404 page nested a
second copy of the app shell, read-only users saw an empty "Actions"
column, and an inactive user's status badge read "inactive (inactive)".

The write path is covered by 8 Playwright tests (`e2e/crud.spec.ts`),
which drive a real browser against the live API — all passing:

- typing one bad character surfaces the error under the input with no
  blur and no submit, and it clears again as the value becomes valid
- submitting an empty form reports every required field and does not
  navigate
- creating a user toasts "User created" and the row appears in the list
  without a reload, proving the mutation's cache invalidation works
- a duplicate username lands **under the Username field**, not only in a
  toast, and the form stays put
- edit loads the shared form pre-filled and persists the change
- delete opens the one shared modal, names its target, and removes the
  row; cancel leaves the record alone
- the theme toggle flips `dark` on `<html>` and survives a reload

The tests create their own records and were cleaned up afterwards; the
seed data is back to 20 users / 10 patients / 2 roles.

## Deviation from "latest versions"

TypeScript is pinned to **5.9.3**, not 7.0.2. No stable `typescript-eslint`
supports TS 7 yet (it requires `>=4.8.4 <6.1.0`), so TS 7 would mean no
working lint. Everything else is on latest.
