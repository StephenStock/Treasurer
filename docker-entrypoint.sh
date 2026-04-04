#!/bin/bash
set -e
# Named volumes mount at /data with root ownership; app runs as uid 1000 and must own /data for SQLite.
chown -R appuser:appuser /data
exec gosu appuser "$@"
