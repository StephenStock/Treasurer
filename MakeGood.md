# Make Good: bring the Den PC into the same shape

Use this as the handoff note when I go to the Den PC.

## Goal

Make the Den PC match this machine for running the 5217 app, so I can later install PostgreSQL there and use it as the temporary shared database host.

## Current reference machine

- Windows PC
- Python launcher available as `py`
- Python version here: `Python 3.13.12`
- `py -3 --version` also returns `Python 3.13.12`

## What the Den PC needs

1. Install Python 3.13.x
- Install the same Python family if possible: Python 3.13.x.
- Make sure the Python launcher (`py`) is installed.
- Make sure `python` and `py -3` both resolve to the new install, not an old 3.11 or earlier version.
- During install, enable:
  - `Install launcher for all users`
  - `Add python.exe to PATH`

2. Verify Python is correct
- Run:
  - `python --version`
  - `py -3 --version`
  - `where python`
  - `where py`
- Both version commands should show Python 3.13.x.

3. Do not use the old virtual environment
- If an old `.venv` exists in the repo, do not trust it.
- The launcher now installs requirements with `pip --user`, so the app should run without depending on an old per-machine venv.

4. Make sure the repo is up to date
- The working copy should include the current `start.bat` changes.
- `start.bat` now prefers `py -3`, requires Python 3.10+, and stores the live database in local app data by default.

5. Later, install PostgreSQL on the Den PC
- Once Python is correct, install PostgreSQL on that machine if we decide it should host the temporary shared database.
- Keep PostgreSQL local/private, not internet-exposed.

## Expected app behavior after this

- Running `start.bat` should install dependencies with the correct Python.
- The live SQLite database will be created in:
  - `%LOCALAPPDATA%\5217\Lodge.db`
- If `TREASURER_DATABASE` is set, that path wins instead.

## If Codex is used on the Den PC

Ask Codex to:

- check the installed Python versions
- remove any dependence on an old Python 3.11 install
- verify `py -3` uses Python 3.13.x
- make sure the repo can run `start.bat` cleanly on that machine
- leave the code in a state ready for PostgreSQL installation later

## Notes

- The live database should not be treated as OneDrive-synced data.
- OneDrive is fine for backup copies, but not for the live SQLite file.
- The Den PC is only being prepared so we can later choose where PostgreSQL should live.
- The current PostgreSQL setup on this machine is documented in `docs/operations/postgresql-setup.md`.
