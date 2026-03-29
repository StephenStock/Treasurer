# Treasurer Aid

Local-first treasurer aid built with Flask, vanilla JavaScript, and SQLite.

## What this repo contains

- Server-rendered admin app for members, dues, bookings, bank, cash, and reporting
- Local Windows launch flow via `start.bat`
- SQLite locally by default
- Project documentation under `docs/`
- Recommended repo location: `C:\Code\Treasurer`

## Quick start

Run:

```bat
start.bat
```

This will:

1. Create a local virtual environment if needed
2. Install the Python dependencies
3. Create the local SQLite database on first run
4. Start the development server at `http://127.0.0.1:5000`

`start.bat` reads `config.local` first. For now, treat that file as the local machine-specific hardcode for the live database path. If you put `TREASURER_DATABASE=\\DEN\TreasurerDB\Treasurer.db` in it, that machine will use the shared live database. If `config.local` is missing, it falls back to `C:\TreasurerDB\Treasurer.db`.

Use `config.local.example` as the template for the file.

You can change the mirrored backup folder from the app's Settings page. The app will create the folder if it does not exist and store `Treasurer.backup.db` inside it. The backup is a one-way safety copy written out when the app exits.

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
- Public access:
  - public forms are optional and may remain in Microsoft Forms instead

## Product direction

- preferred direction: local-first treasurer's aid
- SQLite local default
- continuity priority: exportability, handover, and spreadsheet fallback
- canonical operational reference: [`docs/Runbook.md`](docs/Runbook.md)
