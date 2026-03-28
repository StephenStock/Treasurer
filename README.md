# Lodge Treasurer App

Starter web app for a lodge treasurer using Flask, PostgreSQL in production, and vanilla JavaScript.

## What is included

- Flask application factory
- Local SQLite for development, PostgreSQL on Lightsail for production
- Server-rendered dashboard for members, dues, bookings, and messages
- `start.bat` launcher for local development

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

The app uses `TREASURER_DATABASE_URL` to decide which database to talk to. `start.bat` defaults to a local SQLite database in `%LOCALAPPDATA%\Treasurer\Lodge.db` so you can develop on Windows without needing the Lightsail database.

If you need to point the app somewhere else, set `TREASURER_DATABASE_URL` before launching it.

`start.bat` prefers `py -3` when available, so whichever machine you use should have Python 3.10 or newer installed.

## Default seeded account

- Username: `lodgeadmin`, `treasurer`, `secretary`, or `helper`
- Password: `changeme`

The app now enforces login for the admin pages. These seeded accounts are meant as the starting point for the four internal users we discussed, and you can change the passwords later as part of handover.

## Suggested next steps

- Add forms for members, dues, and events
- Build CSV export/import for handover and reporting
- Add payment workflow once the core record-keeping is solid

## Project planning

The project now includes a lightweight spec-driven docs structure:

- `docs/roadmap.md`
- `docs/working-agreement.md`
- `docs/specs/`
- `docs/sessions/`

This is intended to keep development in small, low-surprise slices.

Workbook analysis has also been captured in:

- `docs/specs/workbook-derived-requirements.md`
