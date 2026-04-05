# Lodge Office

Local-first lodge administration app built with Flask, vanilla JavaScript, and SQLite. Treasury workflows (members, dues, bank, cash, reporting) are the main focus today; other officer views can grow alongside them.

## What this repo contains

- Server-rendered admin app for members, dues, bookings, bank, cash, and reporting
- Local Windows launch flow via `start.bat`
- SQLite locally by default
- Project documentation under `docs/`

## Quick start

Run:

```bat
start.bat
```

This will:

1. Create or reuse a local `.venv` automatically
2. Install the Python dependencies
3. Create the local SQLite database on first run
4. Start the development server at `http://127.0.0.1:5000`

You do not need to activate the environment manually; `start.bat` handles that for you.

By default the live database is `LodgeOffice.db` in the same folder as `start.bat` (if `Treasurer.db` from an older install is still there, that file is used until you rename or remove it). Optional `config.local` (see `config.local.example`) can set `TREASURER_DATABASE` or `TREASURER_BACKUP_DATABASE` if you want the files elsewhere on **this laptop** only.

You can change the mirrored backup location from the app's Settings page. The app creates the folder if needed and keeps `LodgeOffice.backup.db` in sync after successful saves.

If another copy is already open, the launcher will stop with a message telling you to shut the other one down first.

The home page shows a one-line backup status and an `Exit App` button. The detailed backup folder, last-backup timestamp, and restore controls live in Settings.

`start.bat` prefers `py -3` when available, so the machine should have Python 3.10 or newer installed.

## Documentation map

- [`docs/Runbook.md`](docs/Runbook.md): local runtime, backup, restore, imports, and operations
- [`docs/roadmap.md`](docs/roadmap.md): product direction and current delivery phase
- [`docs/specs/`](docs/specs/): feature and business-rule documents
- [`docs/working-agreement.md`](docs/working-agreement.md): implementation workflow for the project

## Current product shape

- Current operational areas:
  - Members and dues
  - Bank ledger and categorisation
  - Cash entry and settlement
  - Reporting and balances
- Standalone use: run locally on the treasurer’s laptop; sharing with another person is expected to be a packaged handover, not ad-hoc hosting

## Product direction

- preferred direction: local-first Lodge Office (treasurer-heavy today)
- SQLite local default
- continuity priority: exportability, handover, and spreadsheet fallback
- canonical operational reference: [`docs/Runbook.md`](docs/Runbook.md)
