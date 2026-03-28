# Roadmap

## Current phase

Phase 1: Foundation and core records

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
- PostgreSQL database on the DEN PC
- Local launcher
- Seed data
- Dashboard shell
- Documentation and specs

### Phase 2: Authentication and roles

- Login page
- Session management
- Treasurer and secretary roles
- Protected admin routes

### Phase 3: Members and dues

- Member list
- Member detail page
- Dues status management
- Dues entry and editing forms
- CSV export for members and dues

### Phase 4: Events and meal booking

- Event creation
- Booking form
- Dietary notes
- Booking summary for the secretary or dining lead

### Phase 5: Treasurer operations

- Transaction logging
- Reporting screens
- Reconciliation support
- Backup and handover tools

### Phase 6: Member services

- Member login
- View dues status
- Book meals
- Submit queries or updates

### Phase 7: Payments and notifications

- Online payment integration
- Email reminders
- Payment confirmations
- Due-date reminders

## Immediate next slice

Build the members-and-dues screens on top of the revised data model, then add authentication around those admin routes.
