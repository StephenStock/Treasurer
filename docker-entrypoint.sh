#!/bin/bash
set -e
# Named volumes mount at /data with root ownership; app runs as uid 1000 and must own /data for SQLite.

# Legacy volume: only Treasurer*.db present — use them until operator renames to LodgeOffice*.db
if [ "${TREASURER_DATABASE:-}" = "/data/LodgeOffice.db" ] && [ ! -f /data/LodgeOffice.db ] && [ -f /data/Treasurer.db ]; then
  export TREASURER_DATABASE=/data/Treasurer.db
fi
if [ "${TREASURER_BACKUP_DATABASE:-}" = "/data/LodgeOffice.backup.db" ] && [ ! -f /data/LodgeOffice.backup.db ] && [ -f /data/Treasurer.backup.db ]; then
  export TREASURER_BACKUP_DATABASE=/data/Treasurer.backup.db
fi

chown -R appuser:appuser /data
exec gosu appuser "$@"
