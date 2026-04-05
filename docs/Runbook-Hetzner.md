# Lodge Office — Hetzner Cloud runbook (production)

Operational reference for the **Docker-based** deployment of **Lodge Office** on a **single Ubuntu server** (Hetzner Cloud). Local laptop workflows stay in `Runbook.md`.

## System purpose

- Host the Lodge Office **Flask** app for a **very small** user base (on the order of 3–4 people).
- Keep operations **scripted and repeatable**: deploy, rollback, backup, restore, health check.
- **SQLite first** — the codebase is SQLite-only today; PostgreSQL is future work (see `architecture.md`).

## Architecture summary

- **OS:** Ubuntu 24.04 LTS (example: server `lodge`, CX23-class: 2 vCPU, 4 GB RAM, 40 GB disk, backups enabled).
- **Containers:** `app` (Flask + Gunicorn) and `caddy` (reverse proxy, TLS when using a real DNS name).
- **Data:** Docker volume `treasurer-data` mounted at `/data` in the app container (`LodgeOffice.db` + `LodgeOffice.backup.db` by default; legacy `Treasurer*.db` paths still work if set in `.env`).
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
- Git repository cloned to a fixed path (e.g. `/opt/treasurer`) with `origin` pointing at your canonical remote (this repo: **`lodge-office`** on GitHub).
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
   - **First sign-in:** if the database has **no users**, optionally set **`TREASURER_BOOTSTRAP_ADMIN_EMAIL`** and **`TREASURER_BOOTSTRAP_ADMIN_PASSWORD`** (≥ 10 characters) so the first startup creates an **Admin** user. Otherwise create accounts from the app after an admin exists, or use a controlled one-off SQL/script (see `docs/Runbook.md`).
   - Optional **SMTP** (`MAIL_SERVER`, `MAIL_PORT`, etc.) so **forgot password** can send email; without it, reset links may only appear in flash messages (not suitable for untrusted networks).
4. `docker compose up -d --build`
5. `./scripts/healthcheck.sh` (uses **`GET /healthz`**, which does not require authentication)

## Deploy procedure

From the server (as **steve**), in the project folder:

```bash
cd /opt/treasurer
bash scripts/deploy.sh
```

This script:

1. Resets **`scripts/*.sh`** to the last commit (so harmless drift—often **`chmod +x`** or line endings—does not block `git pull`). If **other** tracked files are still modified, the script stops and shows `git status`.
2. Runs a **pre-deploy database backup** (`scripts/backup_db.sh`).
3. Runs **`git pull --ff-only`** (only fast-forward; fails if the server’s branch has diverged).
4. Runs **`docker compose up -d --build`** (rebuild app image and restart containers).
5. Runs **`scripts/healthcheck.sh`**.

If you ever suspect Docker is using a **stale** app image after a pull:

```bash
DEPLOY_NO_CACHE=1 bash scripts/deploy.sh
```

To skip the backup step (not recommended): `DEPLOY_SKIP_BACKUP=1 bash scripts/deploy.sh`

If `bash scripts/deploy.sh` says “Permission denied”, use `bash` as above (no execute bit needed).

### Deploy from your Windows PC

The repo root has **`deploy.bat`**. It runs the same server script over **SSH** (no need to type `ssh` and `cd` by hand).

1. Install **Git for Windows** or ensure **OpenSSH Client** is available (`ssh` in a Command Prompt).
2. Set up **SSH key** login to the server (recommended) or you’ll be prompted for a password each time.
3. Edit **`deploy.bat`** if the server address is not **`91.99.170.73`**, or run: `deploy.bat your.ip.or.hostname`
4. Double‑click **`deploy.bat`** or run it from **Command Prompt** in the project folder.

**Note:** **`deploy.bat`** runs **`git fetch`** and resets **`scripts/*.sh`** on the server **before** **`deploy.sh`**, so a dirty **`scripts/deploy.sh`** (often from **`chmod`**) cannot block **`git pull`** anymore.

Push your changes to **GitHub** before deploying, or `git pull` on the server will have nothing new to fetch.

## Rollback procedure

```bash
cd /opt/treasurer
./scripts/rollback.sh HEAD~1
# or: ./scripts/rollback.sh <full-commit-sha>
```

Then return to `main` when ready: `git checkout main && git pull`.

Rollback assumes the previous revision is **compatible** with the existing SQLite file; schema changes without migrations are an ops risk — prefer small, tested deploys.

## Backup and restore

**Host-side tar (full `/data` volume):**

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

**In-app SQLite file (Settings → Copy database file):**

- **Download database file** — saves a consistent snapshot of the live SQLite file through your browser (e.g. to your laptop). Use this for an extra off-server copy without SSH.
- **Upload and replace database** — replaces the live database with the chosen `.db` file. The previous file is copied aside in the same folder as `Treasurer.before-restore.<UTC stamp>.db`. Use when promoting data from a local PC to the server or restoring a known-good copy.

**Deployment and data survival:** `docker compose up -d --build` does **not** remove the named volume `treasurer-data`; your SQLite files under `/data` in the container persist across deploys. Only `docker compose down -v`, deleting the volume manually, or restoring from backup will replace that data.

**Protecting the database in practice:**

| Layer | What to do |
| --- | --- |
| **Deploys** | Use normal `deploy.sh` / `docker compose up -d --build`. **Never** run `docker compose down -v` unless you intend to wipe the volume. |
| **Pre-deploy** | `scripts/deploy.sh` runs `backup_db.sh` first (tar of `/data` into `backups/` on the host). Keep those tars **off-server** too. |
| **Running system** | Settings → **Back up now** maintains the mirrored backup file; **Download database file** gives a full copy through the browser. |
| **Schema / new tables** | New releases run `ensure_financial_tables` (and related seeds) on startup so the SQLite file **gains** tables and columns as the code evolves—no separate manual migration step for normal deploys. |

**Cash book vs local Excel:** the app can **seed** cash book rows from the treasurer workbook in the project root **only** when that workbook exists on the machine **and** the cash book table was empty. A typical server has **no** workbook, so you will not see those seeded rows there unless you enter them in the **Cash** UI or **upload** a database that already contains them (from local or from backup).

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
docker compose exec app sqlite3 /data/LodgeOffice.db
```

Only for break-glass scenarios; **no** PostgreSQL CLI until Postgres is adopted.

Document *who* ran *what* and *why* when manual SQL is unavoidable.

## Bank / finance data handling

- Treat manual SQL as **exceptional**; record operator, time, and reason.
- If structured **admin correction + audit log** is not implemented for a given entity, treat that as a **roadmap** item (see `roadmap.md`).

## Known risks / gotchas

- **SQLite + multi-worker Gunicorn:** the image uses **one worker** by design. Do not raise worker count without moving off SQLite.
- **Application login:** the app requires **sign-in** for normal pages (`/auth/login`). **Roles** (Secretary, Treasurer, Auditor, Admin, Charity Steward, Master) exist; **route-level permission enforcement is not fully wired yet** — treat network exposure as sensitive until you are comfortable with that model. Do not expose the app container port **8000** directly to the internet; use **Caddy** on **80/443** only.
- **`SECRET_KEY`:** must be set in production; sessions and CSRF rely on it.
- **Runtime lock (`TREASURER_RUNTIME_LOCK`):** intended for single-desktop use; keep **off** on the server unless you understand the implications.
- **Case sensitivity:** this repo is developed on Windows; deployment paths are Linux — avoid mixed-case assumptions in scripts.

## What is still provisional

- Hostname, TLS certificates, and **off-site** backup destination.
- **PostgreSQL** migration (not started in code).
- Optional: **finer-grained** rules inside a page (beyond the role matrix) if needed later.
- Optional: CI job to build/push images, log aggregation, Uptime Kuma, etc.

## Related documents

- `docs/Runbook.md` — local Windows operation
- `docs/architecture.md` — system view and persistence
- `docs/Runbook-Hosting.md` — optional Azure notes (not required for Hetzner)

## Revision history

| Date | Change |
| --- | --- |
| 2026-04-03 | Initial Hetzner Docker runbook and scripts. |
| 2026-04-03 | Documented portal sign-in, bootstrap admin, optional mail, `/healthz` unauthenticated, and replaced outdated “no application login” note. |
| 2026-04-05 | Product naming: Lodge Office; GitHub repo `lodge-office`; operational filenames (`Treasurer.db`, etc.) unchanged. |
| 2026-04-06 | Default SQLite files: `LodgeOffice.db` / `LodgeOffice.backup.db`; legacy `Treasurer*.db` supported. |
