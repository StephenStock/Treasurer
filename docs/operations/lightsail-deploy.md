# Lightsail Deploy

## Purpose

This note records the first production-style deployment setup for the 5217 app on Lightsail.

## Current target

- Lightsail app instance: `lodge-app`
- Static IP: `18.130.77.196`
- Lightsail PostgreSQL database: `eu-west-2`
- Application database: `dblodge`

## Runtime model

- The app should run as a `systemd` service on the Lightsail instance
- `gunicorn` should serve the Flask app in production instead of the Flask development server, launched through the venv's Python
- The app should read its database connection from `TREASURER_DATABASE_URL`

## Files in the repo

- `deploy.bat` runs the remote deploy from Windows by SSHing into the Lightsail instance
- `deploy/deploy.sh` updates code on the server, installs dependencies, refreshes the schema if needed, and restarts the service
- `deploy/5217.service` defines the systemd service used by the Lightsail instance

## Server setup summary

1. Clone the repo on the Lightsail instance into `/home/ubuntu/5217`
2. Create the virtual environment in `/home/ubuntu/5217/.venv`
3. Copy `deploy/5217.service` to `/etc/systemd/system/5217.service`
4. Create `/etc/5217/5217.env` with the database connection string
5. Enable and start the service with `systemctl`
6. Download or install an SSH private key on Windows so `deploy.bat` can reach the instance

## Deploy flow

- Make code changes locally
- Commit and push to GitHub
- Run `deploy.bat` from Windows
- `deploy.bat` SSHes into the Lightsail instance, ensures the repo lives at `/home/ubuntu/5217`, force-updates it to `origin/main`, and then runs `deploy/deploy.sh`
- The server script pulls the latest code, installs dependencies, refreshes the schema if needed, and restarts the service
- The server script also installs the repo's systemd unit file before restarting so the service path stays in sync

## Notes

- Keep the database credentials out of the repo and store them in `/etc/5217/5217.env`
- Keep the web port closed to the public if a reverse proxy is added later
- Once a domain is pointed at the server, we can add HTTPS and a proper reverse proxy
- The SSH private key used by `deploy.bat` should live outside the repo, such as `%USERPROFILE%\\.ssh\\lodge-app.pem`
