# Treasurer Hosting Runbook (Azure)

## Purpose

This document is the operational reference for **hosting** the Treasurer app on **Microsoft Azure** (or migrating toward it). It is written for **handover**: a future maintainer should be able to find accounts, resources, and recovery steps without SSH skills or prior cloud experience.

**Primary production path today:** single-server **Docker on Hetzner** — see **`Runbook-Hetzner.md`** for deploy scripts, Caddy, and SQLite backups.

The **local laptop** workflow (SQLite, `start.bat`, mirrored backup) remains documented in `Runbook.md`. This file does not replace that; it covers **Azure** only.

## Design principles

- **No routine Linux administration.** Prefer **Azure App Service** (managed runtime) and **Azure Database for PostgreSQL (Flexible Server)**. Troubleshooting uses the **Azure portal**, **log stream**, and **redeploy from Git**—not a shell on a VM.
- **One subscription per environment** (or clearly named resource groups within one subscription) so costs and access are obvious.
- **Secrets stay out of Git.** Use App Service **Configuration** (application settings) and Azure Key Vault later if warranted.
- **This runbook is living.** Update resource names, URLs, and contacts when anything changes.

## Before you create resources

### Subscription and billing

| Field | Value |
| --- | --- |
| Azure AD tenant (directory) | |
| Subscription **name** | Lodge 5217 |
| Subscription **ID** | `04b5447e-729a-4585-bd6f-4610bf3506c3` |
| **Azure portal sign-in** (primary billing owner) | `developer5217@outlook.com` |
| Offer type (e.g. Free Trial, Pay-As-You-Go) | |
| **Billing owner** (name / email) | `developer5217@outlook.com` |
| **Second owner / admin** (for handover) | |
| Payment method / card last four | |

**Account note:** Billing ownership for subscription **Lodge 5217** is under **`developer5217@outlook.com`**. Sign in to the portal with that address for subscription and billing tasks.

### Region discipline

Azure does not use a single “default region” for your whole account. You choose a **Region** on each resource. For this project, **use one region consistently** (for example **UK South**) for the web app, database, and related services to limit latency and data-transfer complexity.

| Field | Value |
| --- | --- |
| **Chosen region** (e.g. `(Europe) UK South`) | **UK South** — in the portal this often appears as `(Europe) UK South`. |
| **Resource group name** (e.g. `rg-treasurer-dev`) | `rg-treasurer-dev` |

Create a **resource group** first; place subsequent resources in that group unless you have a documented reason not to.

### Cost controls

| Field | Value |
| --- | --- |
| Budget name | |
| Monthly limit (amount / currency) | |
| Alert thresholds (e.g. 50%, 80%, 100%) | |
| Alert email(s) | |

**Note:** Budget alerts **warn**; they do not automatically stop all spend unless you configure additional policies. Review **Cost Management** in the portal regularly during setup.

### Naming convention (suggested)

Use lowercase, hyphens, and a stable prefix, for example: `treasurer-dev-*` for non-production. Record final names in the inventory table below.

## Resource inventory

Fill this in as resources are created. One row per major component.

| Name | Type | Region | Resource group | Purpose |
| --- | --- | --- | --- | --- |
| | App Service (Web App) | UK South | rg-treasurer-dev | Flask application |
| | App Service Plan | UK South | rg-treasurer-dev | Hosting SKU |
| | Azure Database for PostgreSQL – Flexible Server | UK South | rg-treasurer-dev | Application database |
| | (Optional) Storage account | UK South | rg-treasurer-dev | Logs, exports, or static assets |
| | (Optional) Application Insights | UK South | rg-treasurer-dev | Telemetry |

## Application Service (web app)

| Field | Value |
| --- | --- |
| App Service **name** | |
| **Default URL** (`https://….azurewebsites.net`) | |
| **Runtime** (e.g. Python 3.11) | |
| **Deployment** (GitHub Actions, Local Git, ZIP, etc.) | |
| **Repository / branch** that deploys production | |

### Configuration (application settings)

List **names** of settings here; **do not** paste secret values into this file.

The app is **SQLite-first** in the main codebase; Azure may later use PostgreSQL via a separate migration. For the current Flask app, the following are relevant (see `docs/Runbook.md` for full local behaviour):

| Setting name | Purpose |
| --- | --- |
| `SECRET_KEY` | Flask sessions and CSRF; must be set in production |
| `TREASURER_DATABASE` | Path to live SQLite file (if not using default) |
| `TREASURER_BACKUP_DATABASE` | Mirrored backup path |
| `TREASURER_BOOTSTRAP_ADMIN_EMAIL` | Optional: with `TREASURER_BOOTSTRAP_ADMIN_PASSWORD`, creates first **Admin** user when the users table is empty |
| `TREASURER_BOOTSTRAP_ADMIN_PASSWORD` | Bootstrap password (≥ 10 characters) |
| `TREASURER_LOGIN_DISABLED` | If set to a truthy value, disables login (automation only; not for production) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER` | Optional SMTP for forgot-password emails |
| `DATABASE_URL` or discrete PostgreSQL variables | Future use if/when Postgres is adopted for this deployment |
| (Add others as required) | |

After changing configuration, **restart** the App Service if the portal prompts you to.

### Logs and diagnostics

| Field | Value |
| --- | --- |
| Where you view **Log stream** / logs | |
| Application Insights resource (if any) | |

## Database (PostgreSQL)

The production codebase today targets **SQLite** for local use. A **hosted** deployment is expected to use **PostgreSQL** with connection settings supplied via environment variables. Treat migration to PostgreSQL as a **separate delivery** from “create the Azure resources.”

| Field | Value |
| --- | --- |
| Server **name** | |
| **Admin username** (stored in password manager, not here) | |
| **Database name** (e.g. `treasurer`) | |
| **SSL** | Required for Azure PostgreSQL |
| **Firewall / networking** (public IP allowlist, VNet, private access) | Summarize the chosen model |

### Backups

| Field | Value |
| --- | --- |
| Backup retention (days) | |
| Where restore is initiated (portal path) | |

## Secrets and access control

| Field | Value |
| --- | --- |
| Password manager / vault used for admin passwords | |
| Who has **Owner** or **Contributor** on the subscription or resource group | |
| MFA enforced for admin accounts? (yes / no) | |

## Operational procedures

### Deploy a new version

1. Merge to the branch connected to deployment (often `main`).
2. Confirm the deployment pipeline or **Deployment Center** run completes.
3. Open the site and smoke-test: **sign in** (`/auth/login`), dashboard, bank/cash/settings, and **`GET /healthz`** (plain `ok`, no authentication).
4. If something fails, open **Log stream** and recent **deployment logs** before changing infrastructure.

### When the site is down or errors

1. Check **App Service** → **Diagnose and solve problems** and **Log stream**.
2. Verify **Application settings** were not accidentally cleared.
3. Verify **PostgreSQL** is running and firewall rules still allow the App Service outbound IPs (if using IP-based rules—prefer documented stable approaches for production).
4. Restart the App Service once after config changes if needed.

### Emergency: stop spend on a dev environment

1. Development resource group: **`rg-treasurer-dev`** (subscription **Lodge 5217**, region **UK South**).
2. **Deleting the resource group** removes contained resources and stops ongoing charges for those resources (subject to Azure billing rules). **This is destructive.** Take a manual export or backup first if there is data you need.

### Emergency: restore database

1. Use Azure Database for PostgreSQL **point-in-time restore** or backup restore per Microsoft’s current portal flow for your SKU.
2. Update App Service connection strings if the hostname changed.
3. Record what was restored and why in a short note (email or ticket).

## Handover checklist

Use this when transferring responsibility to another person.

- [ ] Second billing admin or subscription **Owner** is assigned.
- [ ] This runbook filled in with **real** subscription IDs, resource names, and URLs (or a secure internal link to same).
- [ ] Admin passwords stored in a **shared** password manager entry with named contacts.
- [ ] MFA enabled on all admin accounts.
- [ ] Someone other than the primary owner has successfully logged into the portal and **found** the App Service and database.
- [ ] Someone has performed a **test deploy** from the documented branch using the documented method.
- [ ] Budget alerts verified (test email received or threshold visible).

## Related documents

- `docs/Runbook.md` — local Windows operation, SQLite, backups, `start.bat`
- `README.md` — project overview and local setup

## Revision history

| Date | Change |
| --- | --- |
| | Initial template |
| 2026-04-03 | Subscription **Lodge 5217** (`04b5447e-729a-4585-bd6f-4610bf3506c3`), resource group **rg-treasurer-dev**, region **UK South** recorded. Billing ownership **`developer5217@outlook.com`**. Application settings table updated for SQLite auth, bootstrap admin, mail, `LOGIN_DISABLED`, and smoke-test steps (`/auth/login`, `/healthz`). Confirm subscription ID in the portal still matches. |
