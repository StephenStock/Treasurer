# Roadmap

## Current phase

Phase 5: Treasurer operations, continuity, and local-first packaging

## Goal

Build a maintainable web app for lodge treasury administration that can later be handed over to a new treasurer without losing data or process knowledge.

## Guiding principles

- Keep the system understandable for a non-specialist maintainer
- Prefer simple server-rendered pages over heavy frontend architecture
- Build exports and backups into the design early
- Add member-facing features only after treasurer workflows are solid

## Planned phases

### Phase 1: Foundation

- Flask app structure
- Local launcher
- SQLite local default
- Seed data
- Dashboard shell
- Documentation and specs

Status:
- Completed

### Phase 2: Authentication and roles

- Login page
- Session management
- Treasurer and secretary roles
- Protected admin routes

Status:
- Deferred — current product is **single treasurer, one laptop**, browser on `127.0.0.1` only; packaging for another user is a separate deliverable

### Phase 3: Members and dues

- Member list
- Member detail page
- Dues status management
- Dues entry and editing forms
- CSV export for members and dues

Status:
- Core slice delivered

### Phase 4: Events and meal booking

- Event creation
- Booking form
- Dietary notes
- Booking summary for the secretary or dining lead

Status:
- De-emphasized and under review

### Phase 5: Treasurer operations

- Bank transaction import
- Bank category assignment
- Cash entry by meeting
- Cash settlement into bank
- Balance sheet reporting
- Workbook import support
- Reconciliation support
- Backup and handover tools

Status:
- In progress

### Phase 6: Member services

- View dues status
- Book meals
- Submit queries or updates

Status:
- Deferred unless continuity-safe and genuinely needed

### Phase 7: Payments and notifications

- Online payment integration
- Email reminders
- Payment confirmations
- Due-date reminders

Status:
- Not started

## Immediate next slice

- Formalize the local-first product pivot around the business continuity spec
- Define a spreadsheet fallback export pack for treasury operations
- Define the target for a packaged local Windows app
- Continue improving inline-save UX across operational pages
- Build out reconciliation checks and exception handling
