# Project Docs

This folder keeps the project manageable in small, well-scoped slices.

## How we use this

- `Runbook.md` is the single source of truth for local environment and operational setup
- `Runbook-Hetzner.md` is the production Docker deployment on a single Ubuntu/Hetzner server (scripts, backup, rollback)
- `Runbook-Hosting.md` is the place for optional Azure hosting, subscriptions, and handover
- `architecture.md` is a short system overview (Flask, SQLite, process model)
- `roadmap.md` tracks the bigger picture and what phase we are in
- `working-agreement.md` defines how we want Codex to work on the project
- `specs/` contains feature specs we can implement one at a time

## Recommended workflow

1. Pick one feature spec
2. Keep the scope tight
3. Implement one vertical slice
4. Verify it works
5. Update the relevant spec and the runbook before moving on
