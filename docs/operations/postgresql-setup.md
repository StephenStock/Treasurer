# PostgreSQL Setup

## Purpose

This note records the PostgreSQL setup on the DEN PC so the Treasurer app can point at the same database from whichever machine you use on the home network.

## Current host

- Windows PC
- PostgreSQL 18.3
- Service name: `postgresql-x64-18`
- LAN IP: `192.168.1.201`
- Port: `5432`

## Lightsail database

- Region: `eu-west-2`
- Endpoint: `ls-4a3f9c5fb6c6b2db323a0b9f0a34e7962102a48c.ctasfsdggcyv.eu-west-2.rds.amazonaws.com`
- Port: `5432`
- Public mode: disabled

## Database and role

- Database: `treasurer`
- Role: `treasurer`
- Password used at setup time: `lodge`

## Connectivity

- `listen_addresses` is set to allow network connections
- `pg_hba.conf` includes a home LAN rule for `192.168.1.0/24`
- PostgreSQL accepts connections on the LAN IP with:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 192.168.1.201 -U treasurer -d treasurer
```

## Remaining manual step

Windows Firewall still needs an inbound TCP rule for port `5432` if it has not already been added manually with admin rights:

```powershell
New-NetFirewallRule -DisplayName "PostgreSQL 5432 Inbound" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5432 -RemoteAddress 192.168.1.0/24 -Profile Private
```

## App connection string

The app now defaults to this PostgreSQL database URL:

```text
postgresql://treasurer:lodge@192.168.1.201:5432/treasurer
```

## Notes

- Keep the database host private on the home network.
- Do not use OneDrive for the live database.
- If the app needs to point elsewhere, override `TREASURER_DATABASE_URL` before launch.
- The Lightsail database only accepts connections from Lightsail resources in the same region while public mode is disabled.
