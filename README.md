# Lodge Treasurer App

Starter web app for a lodge treasurer using Flask, PostgreSQL, and vanilla JavaScript.

## What is included

- Flask application factory
- PostgreSQL database connection to the DEN PC with seeded sample data
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
3. Connect to the PostgreSQL database on the DEN PC
4. Start the development server at `http://127.0.0.1:5000`

The app uses `TREASURER_DATABASE_URL` to decide which database to talk to. By default, it points at the PostgreSQL instance on the DEN PC, so the same data is available whether you launch the app from this machine or there.

If you need to point the app somewhere else, set `TREASURER_DATABASE_URL` before launching it.

`start.bat` prefers `py -3` when available, so whichever machine you use should have Python 3.10 or newer installed.

## Default seeded account

- Username: `treasurer`
- Password: `changeme`

This starter does not yet enforce authentication. The default account is seeded so we can add login next.

## Suggested next steps

- Add authentication and roles
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
