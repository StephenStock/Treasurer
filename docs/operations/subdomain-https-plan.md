# Subdomain and HTTPS Plan

## Purpose

This note records the intended public entry point for the Treasurer app and the order we should use to make it secure and maintainable.

## Current public site

- Main lodge website: `https://5217.org.uk/`
- Keep the existing WordPress site live for the lodge overview pages

## Planned app host

- Treasurer/Secretary app: `https://app.5217.org.uk/`
- Public forms can later live under paths such as `/forms`

## Sequence

1. Keep the WordPress site on the root domain unchanged
2. Point `app.5217.org.uk` at the Lightsail static IP
3. Confirm the app works over plain HTTP first
4. Add HTTPS once the subdomain is stable
5. Keep the app and database in the same AWS region

## Notes

- The app is already running on Lightsail with a static IP
- The deployment flow is already in place through `deploy.bat`
- The next live change should be DNS, not app architecture
- Once DNS is pointed, HTTPS should be added before treating the app as public-facing
