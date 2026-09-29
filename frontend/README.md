# Hive dashboard

React + TypeScript frontend for the Hive API. There's no login page, the
app calls `GET /me` and shows what the user's permissions allow.

Stack: Vite, React 19, TypeScript, TanStack Query, TanStack Router,
react-hook-form, zod, Tailwind v4, axios, sonner, Vitest, Playwright.

## Running

```bash
# API first (from the repo root)
make up && make check && make init
make run                          # API on :8100

# then the dashboard
cd frontend
cp .env.example .env.local        # set VITE_DEV_USERNAME
npm install
npm run dev                       # http://localhost:5173
```

`make init` creates an `admin` user (all permissions) and a `viewer`
(read only).

### Switching users

Locally, the Switch user button in the header lets you change the user
without restarting, to test permissions. It only shows when
`VITE_DEV_USERNAME` is set. On Cloudera it's not set and the platform
sends the `REMOTE-USER` header.

### Scripts

| command | |
|---|---|
| `npm run dev` | dev server |
| `npm run build` | typecheck + build |
| `npm run typecheck` | `tsc -b --noEmit` |
| `npm run lint` | ESLint |
| `npm run test` | unit tests |
| `npm run test:e2e` | Playwright (API and dev server must be running) |
| `npm run format` | Prettier |

On WSL, Playwright's Chromium needs `libasound.so.2`. Without root:

```bash
mkdir -p ~/.local/pwlibs && cd ~/.local/pwlibs
apt-get download libasound2t64 && dpkg -x libasound2t64_*.deb .
cd frontend
LD_LIBRARY_PATH=~/.local/pwlibs/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH npm run test:e2e
```

## Identity

`VITE_DEV_USERNAME` is sent as the `REMOTE-USER` header, which is what
`app/security.py` reads. On Cloudera the platform sets that header.

`GET /me` returns the current user with role and permissions. `PUT /me`
lets users edit their own first name, last name and email only.

## Structure

```
src/
  schemas/      zod schemas (types come from z.infer)
  lib/api/      axios client and API calls
  lib/          query client, query keys, helpers
  hooks/        query/mutation hooks, permissions, theme, forms
  components/   shared UI (DataTable, dialogs, fields, layout)
  features/     forms and components per model
  routes/       pages (file-based routing)
```

API responses are validated with zod in `lib/api/resources.ts`.

### Caching

`staleTime` is 60s and refetch on focus is off, since Hive queries are
slow. Data is refreshed by invalidating queries after writes:

- user/patient changes also invalidate `logs`
- role changes also invalidate `users` and `me`

### Shared pieces

- `DataTable`: the table used on every page (cards on mobile)
- `ConfirmDeleteModal` + `useDeleteDialog`: the delete dialog
- one form per model for both create and edit
- `createCrudHooks`: the standard query/mutation hooks for a resource

### Forms

Validation runs on change, so errors show while typing. Server errors
(422, and 409 for duplicates) are shown under the matching field.

### Permissions

`Can` hides buttons, `RequirePermission` shows a 403 page, and the sidebar
only shows allowed pages. The API checks permissions on every request
anyway, this is only for the UI.

## Note

TypeScript is on 5.9.3 because `typescript-eslint` doesn't support
TypeScript 7 yet.
