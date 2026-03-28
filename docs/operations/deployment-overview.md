# Deployment Overview

## Purpose

This note records the current public website, the planned application hosting, and the deployment approach so we can keep the project aligned as it moves to AWS.

## Current public site

- Main lodge website: `https://5217.org.uk/`
- Current site is WordPress-hosted and provides the lodge overview pages
- Keep this site as-is for now so the public web presence is not disrupted

## Planned app layout

- New Treasurer/Secretary app should live on a subdomain such as `app.5217.org.uk`
- Public forms can live inside the app under a route such as `/forms`
- The main lodge website and the app should stay separate to keep maintenance simpler

## AWS direction

- Use Amazon Lightsail for the app server
- Use a Lightsail PostgreSQL database for the app data
- Keep the app server and database in the same AWS region
- Current Lightsail database region is `eu-west-2`
- Start with the simplest possible setup and add extras only when needed

## Deployment approach

- Prefer automated deploys over manual SSH steps
- Local changes should be pushed to GitHub
- A deploy script can then update the Lightsail app server and restart the service
- The app should run under `systemd` with `gunicorn` instead of the Flask development server
- No CI/CD pipeline complexity is needed beyond that basic push-to-deploy flow
- Local development on Windows should use the SQLite file created by `start.bat`
- `deploy.bat` on Windows should SSH into Lightsail and run the server deploy script
- The next public step is DNS and HTTPS for `app.5217.org.uk`
- nginx should proxy `app.5217.org.uk` on port 80 to the Flask service on `127.0.0.1:5000`

## Notes

- Reuse the existing domain instead of introducing a new public domain unless there is a strong reason to do so
- Keep the WordPress site live while the new app is introduced gradually
- Document any final DNS choices here once the subdomain is confirmed
- While public mode is disabled, only Lightsail resources in the same region can connect to the database
- See `docs/operations/lightsail-deploy.md` for the current server-side deploy plan
- See `docs/operations/subdomain-https-plan.md` for the public DNS and HTTPS sequence
