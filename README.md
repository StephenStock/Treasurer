# 5217 Portal

Web app for lodge and chapter operations using Flask, vanilla JavaScript, SQLite for local development, and PostgreSQL in production.

## What this repo contains

- Server-rendered admin app for members, dues, bookings, bank, cash, and reporting
- Local Windows launch flow via `start.bat`
- Production deploy flow via `deploy.bat`
- SQLite locally and PostgreSQL in production
- Project documentation under `docs/`

## Quick start

Run:

```bat
start.bat
```

This will:

1. Create a local virtual environment if needed
2. Install Flask
3. Use a local SQLite database on first run
4. Start the development server at `http://127.0.0.1:5000`

The app uses `TREASURER_DATABASE_URL` to decide which database to talk to. `start.bat` defaults to a local SQLite database in `%LOCALAPPDATA%\5217\Lodge.db` so you can develop on Windows without needing the Lightsail database.

If you need to point the app somewhere else, set `TREASURER_DATABASE_URL` before launching it.

`start.bat` prefers `py -3` when available, so whichever machine you use should have Python 3.10 or newer installed.

## Default seeded account

- Username: `lodgeadmin`, `treasurer`, `secretary`, or `helper`
- Password: `changeme`

The admin pages require login. These seeded accounts are only the starting point and should be changed as part of real setup.

## Documentation map

- [`docs/Runbook.md`](docs/Runbook.md): live environment, deploy flow, database, imports, and operations
- [`docs/roadmap.md`](docs/roadmap.md): product direction and current delivery phase
- [`docs/specs/`](docs/specs/): feature and business-rule documents
- [`docs/working-agreement.md`](docs/working-agreement.md): implementation workflow for the project

## Current product shape

- Internal users:
  - Treasurer
  - Secretary
  - Admin/helper users
- Current operational areas:
  - Members and dues
  - Events and bookings
  - Bank ledger and categorisation
  - Cash entry and settlement
  - Reporting and balances
- Public access:
  - `/forms` remains the intended public-facing route area

## Production summary

- Production app host target: `app.5217.org.uk`
- Production runtime: Lightsail + `systemd` + `gunicorn`
- Canonical operational reference: [`docs/Runbook.md`](docs/Runbook.md)
