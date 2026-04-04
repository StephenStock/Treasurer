# Treasurer — Hetzner Cloud runbook (production)

Operational reference for the **Docker-based** deployment on a **single Ubuntu server** (Hetzner Cloud). Local laptop workflows stay in `Runbook.md`.

## System purpose

- Host the Treasurer **Flask** app for a **very small** user base (on the order of 3–4 people).
- Keep operations **scripted and repeatable**: deploy, rollback, backup, restore, health check.
- **SQLite first** — the codebase is SQLite-only today; PostgreSQL is future work (see `architecture.md`).

## Architecture summary

- **OS:** Ubuntu 24.04 LTS (example: server `lodge`, CX23-class: 2 vCPU, 4 GB RAM, 40 GB disk, backups enabled).
- **Containers:** `app` (Flask + Gunicorn) and `caddy` (reverse proxy, TLS when using a real DNS name).
- **Data:** Docker volume `treasurer-data` mounted at `/data` in the app container (`Treasurer.db` + `Treasurer.backup.db`).
- **Firewall (Hetzner):** inbound **22**, **80**, **443** only; no public database port.

Repository layout for deployment:

| Path | Role |
| --- | --- |
| `Dockerfile` | App image |
| `docker-compose.yml` | `app` + `caddy` + volumes |
| `deploy/Caddyfile` | `{$SITE_ADDRESS}` → `reverse_proxy app:8000` |
| `.env` | **On server only** — `SECRET_KEY`, paths, `SITE_ADDRESS` |
| `scripts/deploy.sh` | Pull, backup, build, up, health check |
| `scripts/rollback.sh` | Checkout older revision, rebuild, health check |
| `scripts/backup_db.sh` | Tar of `/data` to `./backups/` |
| `scripts/restore_db.sh` | Restore from backup tar |
| `scripts/healthcheck.sh` | Calls `/healthz` inside the app container |

## Server assumptions

- Docker Engine and Docker Compose plugin installed.
- Git repository cloned to a fixed path (e.g. `/opt/treasurer`) with `origin` pointing at your canonical remote.
- SSH key access for administrators; **non-root** deploy user with `sudo` if required.
- **Hetzner Cloud firewall** attached to the server with the rules above.

## Access required

- SSH to the server.
- Git credentials (deploy key or HTTPS token) to `git pull`.
- DNS (if using HTTPS) pointing the chosen hostname to the server IPv4/IPv6.

## Directory layout on server (suggested)

```text
/opt/treasurer/          # git clone of this repo
  .env                   # not in git; copy from .env.example
  backups/               # host-side DB tar archives (gitignored locally)
```

## First-time setup

1. Install Docker (official docs) and add your user to the `docker` group **or** use `sudo docker compose`.
2. Clone the repo: `sudo git clone <url> /opt/treasurer` and `chown` to the deploy user.
3. `cp .env.example .env` and set:
   - **`SECRET_KEY`** — long random string (see comment in `.env.example`).
   - **`SITE_ADDRESS`** — `:80` for HTTP-only tests, or `treasurer.example.com` for automatic HTTPS (Caddy).
   - Paths default to `/data/...` and match `docker-compose.yml`.
4. `docker compose up -d --build`
5. `./scripts/healthcheck.sh`

## Deploy procedure

```bash
cd /opt/treasurer
./scripts/deploy.sh
```

This runs a **pre-deploy backup**, `git pull --ff-only`, `docker compose up -d --build`, and the health check.

## Rollback procedure

```bash
cd /opt/treasurer
./scripts/rollback.sh HEAD~1
# or: ./scripts/rollback.sh <full-commit-sha>
```

Then return to `main` when ready: `git checkout main && git pull`.

Rollback assumes the previous revision is **compatible** with the existing SQLite file; schema changes without migrations are an ops risk — prefer small, tested deploys.

## Backup and restore

**Backup (on demand or cron):**

```bash
cd /opt/treasurer
./scripts/backup_db.sh
```

Archives land in `backups/treasurer-db-*.tar`. Copy them **off-server** (another region, object storage, or encrypted backup).

**Restore:**

```bash
./scripts/restore_db.sh backups/treasurer-db-YYYYMMDDTHHMMSSZ.tar
```

Stops the app container briefly, restores `/data`, restarts, health-checks.

## Patching routine

- **Application:** deploy via `./scripts/deploy.sh` after merging to the tracked branch.
- **OS:** `sudo apt update && sudo apt upgrade` on a schedule; reboot if the kernel updates.
- **Docker images:** `docker compose pull` when bumping the `caddy` image; rebuild app image on deploy.

## Health-check procedure

```bash
./scripts/healthcheck.sh
```

The app exposes **`GET /healthz`** (plain `ok`, HTTP 200). It does **not** hit the database (liveness-oriented).

## Manual / emergency database access

**Preferred:** use the app’s own screens and exports; for finance-style rows, **prefer in-app corrections** with a clear audit trail when that feature exists.

**Last resort — SQLite shell on the server:**

```bash
docker compose exec app sqlite3 /data/Treasurer.db
```

Only for break-glass scenarios; **no** PostgreSQL CLI until Postgres is adopted.

Document *who* ran *what* and *why* when manual SQL is unavoidable.

## Bank / finance data handling

- Treat manual SQL as **exceptional**; record operator, time, and reason.
- If structured **admin correction + audit log** is not implemented for a given entity, treat that as a **roadmap** item (see `roadmap.md`).

## Known risks / gotchas

- **SQLite + multi-worker Gunicorn:** the image uses **one worker** by design. Do not raise worker count without moving off SQLite.
- **No application login:** restrict by network; do not expose port 8000 publicly (only via Caddy on 80/443).
- **`SECRET_KEY`:** must be set in production; sessions and CSRF rely on it.
- **Runtime lock (`TREASURER_RUNTIME_LOCK`):** intended for single-desktop use; keep **off** on the server unless you understand the implications.
- **Case sensitivity:** this repo is developed on Windows; deployment paths are Linux — avoid mixed-case assumptions in scripts.

## What is still provisional

- Hostname, TLS certificates, and **off-site** backup destination.
- **PostgreSQL** migration (not started in code).
- Optional: CI job to build/push images, log aggregation, Uptime Kuma, etc.

## Related documents

- `docs/Runbook.md` — local Windows operation
- `docs/architecture.md` — system view and persistence
- `docs/Runbook-Hosting.md` — optional Azure notes (not required for Hetzner)

## Revision history

| Date | Change |
| --- | --- |
| 2026-04-03 | Initial Hetzner Docker runbook and scripts. |
