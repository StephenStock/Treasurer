# 5217 Runbook

## Purpose

This runbook is the single operational reference for the 5217 app. It replaces the earlier separate deployment, PostgreSQL, subdomain, and handoff notes.

## Current system summary

- Repo: `StephenStock/5217`
- App stack: Flask, server-rendered templates, light vanilla JavaScript
- Production host: AWS Lightsail instance `lodge-app`
- Production app path: `/home/ubuntu/5217`
- Production service: `5217.service`
- App process: `python -m gunicorn --bind 0.0.0.0:5000 app:app`
- Production database: Lightsail PostgreSQL in `eu-west-2`
- Local default database: SQLite at `%LOCALAPPDATA%\5217\Lodge.db`
- Main public website: `https://5217.org.uk/`
- Intended app host: `https://app.5217.org.uk/`

## What has been delivered

The app now includes:

- Authentication with seeded internal roles
- Members and dues screens
- Bank ledger import and category assignment
- Balance sheet reporting
- Cash entry grouped by meeting
- Cash settlement into the bank ledger
- Multiple cash deposits per meeting
- Workbook import support for both `Bank` and `Cash`
- Push-to-deploy flow from Windows to Lightsail

The production repo, deploy scripts, and server paths have been renamed from `Treasurer` to `5217`. A few historic identifiers remain intentionally, mainly `TREASURER_DATABASE_URL`.

## Repository and runtime layout

Important local files:

- `start.bat`: local Windows launcher
- `deploy.bat`: Windows deploy entry point for Lightsail
- `deploy/deploy.sh`: server-side deploy script
- `deploy/5217.service`: systemd unit installed on the server
- `treasurer_app/schema.sql`: canonical schema

Important production paths:

- App checkout: `/home/ubuntu/5217`
- Virtual environment: `/home/ubuntu/5217/.venv`
- Systemd unit: `/etc/systemd/system/5217.service`
- Preferred env file: `/etc/5217/5217.env`
- Legacy env file still accepted during transition: `/etc/treasurer/treasurer.env`

## Local development

### Default behavior

- `start.bat` uses the local Python launcher on Windows
- If no PostgreSQL DSN is supplied, the app uses SQLite
- The live local SQLite database is stored outside OneDrive in `%LOCALAPPDATA%\5217\Lodge.db`

### Local database options

- SQLite is the safe default for local work
- PostgreSQL can be selected by setting `TREASURER_DATABASE_URL`

Example PostgreSQL DSN shape:

```text
postgresql://USER:PASSWORD@HOST:5432/DATABASE
```

## Production deployment

### Normal deploy flow

1. Commit locally
2. Push to `origin/main`
3. Run `.\deploy.bat`

### What `deploy.bat` does

- Connects to Lightsail by SSH
- Ensures the server checkout exists at `/home/ubuntu/5217`
- Forces the server checkout to `origin/main`
- Runs `deploy/deploy.sh`

### What `deploy/deploy.sh` does

- Confirms the app env file is available
- Rebuilds `.venv` if it is missing or broken
- Installs Python dependencies
- Ensures the schema exists
- Installs the current systemd unit file
- Reloads systemd
- Restarts `5217.service`
- Checks service status

### Production secrets

- Keep secrets out of the repo
- Store the production DSN in `/etc/5217/5217.env`
- During transition, `/etc/treasurer/treasurer.env` is still supported

Expected env variable:

```text
TREASURER_DATABASE_URL=postgresql://...
```

## Database notes

### Production database

- The live app uses Lightsail PostgreSQL
- The app server and database should stay in the same AWS region
- While the database is not public, only approved AWS-side resources can connect

### Local and temporary hosts

- The project can still run against SQLite locally
- A local or LAN PostgreSQL host is possible for testing, but it is no longer the primary deployment target
- Do not keep a live SQLite database inside OneDrive

## Workbook import and migration status

### Bank workbook import

- The app can import bank rows from `Accounts 2025-26.xlsx`
- Bank allocations use the same category model as the workbook
- Statement uploads can also be imported from uploaded bank files

### Cash workbook import

- Cash rows from the workbook have already been imported into the live PostgreSQL database
- The current importer reads the `Cash` sheet and creates meeting-linked cash entries

### Spreadsheet-to-app settlement model

The workbook behavior is now represented this way:

- Cash categorisation is recorded in the cash ledger
- Bank deposits are recorded separately in the bank ledger
- A meeting can be settled by one or more deposits
- Those deposits link back to the meeting without duplicating the original cash categorisation

This preserves the running bank statement while avoiding double counting.

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

## Editing and save behavior

The app is moving toward inline-save behavior for operational pages:

- Editing a cash entry now saves in place
- The page no longer jumps back to the top after a cash edit save
- A small inline tick or cross indicates success or failure
- Cash settlement actions also update in place

The same pattern should be used for similar edit flows elsewhere as they are refined.

## DNS, reverse proxy, and HTTPS

Current state:

- The app is live on Lightsail by IP
- The intended public hostname remains `app.5217.org.uk`
- The root website at `5217.org.uk` remains the WordPress public site

Next infrastructure steps:

1. Point `app.5217.org.uk` at the Lightsail static IP
2. Add nginx in front of the Flask service
3. Verify plain HTTP routing
4. Add HTTPS
5. Keep public members on `/forms` and keep admin routes private

## Operational checks

### After a deploy

Confirm:

- the server checkout is on the expected commit
- `5217.service` is active
- the app loads
- bank and cash pages still render
- the current env file still resolves `TREASURER_DATABASE_URL`

### After schema-affecting changes

Confirm:

- the app starts cleanly
- new tables or indexes exist in PostgreSQL
- existing workbook-imported data still renders
- cash settlement behavior still reconciles correctly

## Known transitional items

- `TREASURER_DATABASE_URL` remains the environment variable name
- legacy env-file fallback is still present in deploy logic
- the public subdomain and HTTPS are still pending

## Documentation policy

- Keep this runbook as the single source of truth for operations and environment setup
- Keep feature intent and business rules in `docs/specs/`
- Avoid creating one-off operational notes when the content belongs here
