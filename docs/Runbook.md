# Treasurer Runbook

## Purpose

This runbook is the single operational reference for the local Treasurer app.

## Operating direction

The current preferred operating model is:

- local-first
- SQLite by default
- single active treasurer or custodian
- spreadsheet export as the continuity fallback

## Current system summary

- Repo: `StephenStock/Treasurer`
- App stack: Flask, server-rendered templates, light vanilla JavaScript
- Preferred operating mode: local Windows app
- Preferred database: local SQLite
- Local database path: `instance\Treasurer.db` inside the project folder
- Local launch script: `start.bat`
- Main docs: `README.md` and `docs/specs/`

## What has been delivered

The app includes:

- Authentication with seeded internal roles
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
- `docs/Runbook.md`: this operational guide
- `docs/specs/`: feature and business-rule documents
- `treasurer_app/schema.sql`: canonical schema

## Local development

### Default behavior

- `start.bat` creates or reuses a local virtual environment
- The launcher installs the Python dependencies if needed
- If the SQLite database does not yet contain the `users` table, the app initializes the schema and seed data
- The app starts at `http://127.0.0.1:5000`

### Local database expectations

- SQLite is the normal and preferred storage engine
- The active local database should live at `instance\Treasurer.db` inside the project folder unless deliberately overridden
- The live database should not be stored inside OneDrive

### Database override

- Set `TREASURER_DATABASE` if you want the SQLite file somewhere else
- The value should be a file path, not a server connection string

## Backups and restore

### Manual backup routine

- Copy the SQLite database file to a safe backup location after important work
- Keep a dated copy before major imports or schema changes
- Treat the workbook export pack as a second continuity layer

### Restore path

- Close the app
- Replace the SQLite database file with the known-good backup
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

## Operational checks

### After a local launch

Confirm:

- the app loads
- bank and cash pages render
- the SQLite database exists in the expected location
- the dashboard and operational pages still load correctly

### After schema-affecting changes

Confirm:

- the app starts cleanly
- the seeded data still renders
- workbook-imported data still renders correctly
- cash settlement behavior still reconciles correctly

## Known transitional items

- `TREASURER_DATABASE` is the current database override variable
- the preferred packaging target is a local Windows workflow
- export pack generation and reconciliation checks are still being tightened

## Documentation policy

- Keep this runbook as the single source of truth for local runtime and recovery setup
- Keep feature intent and business rules in `docs/specs/`
- Avoid creating one-off operational notes when the content belongs here


