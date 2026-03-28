# Roadmap

## Current phase

Phase 5: Treasurer operations, hardening, and handover

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
- PostgreSQL support
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
- Completed

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
- Partially delivered

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

- Member login
- View dues status
- Book meals
- Submit queries or updates

Status:
- Not started

### Phase 7: Payments and notifications

- Online payment integration
- Email reminders
- Payment confirmations
- Due-date reminders

Status:
- Not started

## Immediate next slice

- Continue improving inline-save UX across operational pages
- Build out reconciliation checks and exception handling
- Complete DNS, reverse proxy, and HTTPS for `app.5217.org.uk`
