# Lodge Office — local runbook

## Purpose

This runbook is the single operational reference for the **local** Lodge Office app (treasurer workflows are the bulk of the UI today).

For **Azure hosting**, subscriptions, and handover of cloud resources, use `docs/Runbook-Hosting.md`.

## Operating direction

The current preferred operating model is:

- local-first
- SQLite by default
- single active treasurer or custodian
- spreadsheet export as the continuity fallback

## Current system summary

- App stack: Flask, server-rendered templates, light vanilla JavaScript, Flask-Login for sessions
- Operating mode: local Windows laptop, browser pointed at `127.0.0.1`; **sign-in required** for all app pages except static assets and the **`/healthz`** probe
- Portal accounts: email + password, each user has **one role** (Secretary, Treasurer, Auditor, Admin, Charity Steward, Master). **Role permissions** (Settings → Role permissions) control which **pages and admin actions** each non-admin role may use; the main nav only shows areas the current user may access. Users with the **Admin** role **always** have full access regardless of matrix checkboxes (the Admin column is still useful for reference when tuning other roles)
- Database: SQLite file on this machine (`LodgeOffice.db` next to `start.bat` by default; legacy `Treasurer.db` is still used if present unless overridden in `config.local`)
- Mirrored backup: folder from Settings (or `TREASURER_BACKUP_DATABASE`), kept in sync after successful saves
- Single active-copy lock: only one running copy should hold the database at a time
- Mirrored backup folder can also be changed from the app's Settings page and is stored with the database
- The home page shows a brief backup status line and an `Exit App` button
- Detailed backup folder status, last backup time, and restore controls live in Settings
- Local launch script: `start.bat`
- Main docs: `README.md` and `docs/specs/`

## What has been delivered

The app includes:

- Members and dues screens
- Bank ledger import and category assignment
- Balance sheet reporting
- Cash entry grouped by meeting
- Cash settlement into the bank ledger
- Multiple cash deposits per meeting
- Workbook import support for both `Bank` and `Cash`
- Inline-save behavior on operational pages

## Repository and runtime layout

Important local files:

- `start.bat`: local Windows launcher
- `README.md`: quick-start and local setup summary
- `docs/Runbook.md`: this operational guide (local)
- `docs/Runbook-Hosting.md`: Azure hosting and handover (when used)
- `docs/specs/`: feature and business-rule documents
- `treasurer_app/schema.sql`: canonical schema

## Local development

### Default behavior

- `start.bat` creates or reuses a local `.venv`
- The launcher installs the Python dependencies if needed
- If the SQLite database does not yet contain core tables (for example `reporting_periods`), the app initializes the schema and seed data
- The app starts at `http://127.0.0.1:5000`

The venv is managed automatically by the launcher, so manual activation is not part of the normal flow.

### Local database expectations

- SQLite is the storage engine; one treasurer, one laptop, one canonical `LodgeOffice.db` (legacy `Treasurer.db` supported)
- Default live path: `LodgeOffice.db` in the project folder (`start.bat` sets this unless `config.local` overrides)
- Optional `config.local`: set `TREASURER_DATABASE` to another path **on this PC** if you want the live file outside the repo folder
- Keep the mirrored backup in a safe folder (for example under OneDrive); avoid letting cloud sync fight SQLite on the **live** file
- If another copy of the app is already running, `start.bat` should stop and tell you to close the other instance first

### Database override

- Create `config.local` next to `start.bat` only if you need non-default paths
- `TREASURER_DATABASE`: full path to the live `.db` file on this machine
- `TREASURER_BACKUP_DATABASE`: backup file path or folder (folder receives `LodgeOffice.backup.db`; legacy `Treasurer.backup.db` still readable if configured)
- The Settings page can adjust the backup folder for day-to-day use

### Sign-in and portal administration

- **Sign in:** `http://127.0.0.1:5000/auth/login` (unauthenticated visits to other URLs redirect here). **Sign out** is in the header when signed in.
- **Forgot password:** `/auth/forgot-password`. If outbound **SMTP is not configured**, the app cannot email a link; it will show a one-time reset URL in a flash message (use only in a trusted environment).
- **Portal administration:** under **Settings** — **Portal users** and **Role permissions** (requires the corresponding matrix permissions for non-Admin users; **Admin** role always has full access including these screens).
- **First admin when the database has no users:** set **`TREASURER_BOOTSTRAP_ADMIN_EMAIL`** and **`TREASURER_BOOTSTRAP_ADMIN_PASSWORD`** (at least **10 characters**) in the environment before the first successful startup, **or** add users with a one-off script/SQL after roles exist. Bootstrap runs only when the user table is empty and the app is not in test mode.
- **Automation / tests:** `TREASURER_LOGIN_DISABLED=1` (or `true` / `yes` / `on`) disables the login requirement (do **not** use in production).
- **Sessions and CSRF:** set a strong **`SECRET_KEY`** in production (not the default `change-me`).
- **Password length:** creating users in the UI, self-service reset, and admin password changes require **at least 10 characters**. Logins use whatever hash is stored (including shorter passwords if inserted manually).

### Environment variables (auth and mail)

| Variable | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask session signing; required for real deployments |
| `TREASURER_BOOTSTRAP_ADMIN_EMAIL` | Optional; with `TREASURER_BOOTSTRAP_ADMIN_PASSWORD`, creates first **Admin** user when there are zero users |
| `TREASURER_BOOTSTRAP_ADMIN_PASSWORD` | Must be ≥ 10 characters if used with bootstrap email |
| `TREASURER_LOGIN_DISABLED` | If truthy (`1`, `true`, `yes`, `on`), skips login (tests/automation only) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | Optional SMTP for forgot-password emails |

## Backups and restore

### Manual backup routine

- The app keeps a mirrored backup copy in sync automatically after writes
- **Settings → Copy database file:** **Download database file** saves a snapshot of the live `.db` to your PC; **Upload and replace database** installs a `.db` you choose (the previous file is copied aside as `Treasurer.before-restore.<timestamp>.db` in the same folder)
- Copy the SQLite database file to a safe dated backup location before major imports or schema changes
- Treat the workbook export pack as a second continuity layer

### Restore path

- Close the app
- Replace the SQLite database file with the known-good backup, or let `start.bat` restore the newest mirrored copy
- Start the app again with `start.bat`
- Confirm the dashboard and bank/cash pages load correctly

## Workbook import and migration status

### Bank workbook import

- The app can import bank rows from `Accounts 2025-26.xlsx`
- Bank allocations use the same category model as the workbook
- Statement uploads can also be imported from uploaded bank files

### Cash workbook import

- Cash rows from the workbook can be imported into the cash ledger
- Imported cash rows are linked to the meeting workflow used by the app

### Spreadsheet-to-app settlement model

The workbook behavior is represented this way:

- Cash categorisation is recorded in the cash ledger
- Bank deposits are recorded separately in the bank ledger
- A meeting can be settled by one or more deposits
- Those deposits link back to the meeting without duplicating the original cash categorisation

## Current financial model highlights

### Cash categories currently supported

- Subs
- Dining
- Gavel
- Raffle
- Copper Pot
- Donations
- Almoner
- Tyler

### Bank categories currently supported

- Cash
- Pre-Subs
- Pre-Dining
- Subs
- Dining
- Visitor
- Initiation
- SumUp
- Gavel
- Donations
- Raffle
- Copper Pot
- Chapter LOI
- LOI
- Relief
- Almoner
- Tyler
- UGLE
- PGLE
- Orsett
- WoolMkt
- Caterer
- Bank Charges
- Widows
- LOI-Expenses

## Operational checks

### After a local launch

Confirm:

- the app loads and you can **sign in** (or that you intentionally disabled login for automation)
- bank and cash pages render
- the SQLite database exists in the expected location
- the dashboard and operational pages still load correctly
- **`GET /healthz`** returns plain `ok` without signing in (for scripts and health probes)

### After schema-affecting changes

Confirm:

- the app starts cleanly
- the seeded data still renders
- workbook-imported data still renders correctly
- cash settlement behavior still reconciles correctly

## Known transitional items

- the preferred packaging target is a local Windows workflow
- export pack generation and reconciliation checks are still being tightened
- finer-grained rules (per-action inside a page) may be added later; the matrix is **per area** (e.g. Bank, Members), not per button

## Documentation policy

- Keep this runbook as the single source of truth for local runtime and recovery setup
- Keep cloud and subscription operations in `docs/Runbook-Hosting.md`
- Keep feature intent and business rules in `docs/specs/`
- Avoid creating one-off operational notes when the content belongs in one of the runbooks

## Revision history

| Date | Change |
| --- | --- |
| 2026-04-03 | Documented sign-in, roles, admin screens, bootstrap admin, mail and `LOGIN_DISABLED` env vars, and `/healthz` behavior. |
| 2026-04-05 | Product naming: Lodge Office; local runbook title updated; on-disk DB names unchanged. |
| 2026-04-06 | Default DB files: `LodgeOffice.db` / `LodgeOffice.backup.db`; legacy `Treasurer*.db` still supported. |

