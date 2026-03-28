@echo off
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "APP_DATA=%LOCALAPPDATA%\Treasurer"
if "%TREASURER_DATABASE_URL%"=="" set "TREASURER_DATABASE_URL=%APP_DATA%\Lodge.db"
set "TEMP=%APP_DATA%\tmp"
set "TMP=%TEMP%"

if not exist "%APP_DATA%" mkdir "%APP_DATA%"
if not exist "%TEMP%" mkdir "%TEMP%"

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [Regex]::Escape((Get-Location).Path); Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw)\.exe$' -and $_.CommandLine -and $_.CommandLine -match $root -and ($_.CommandLine -match 'flask(\.exe)?\s+--app\s+app\s+run' -or $_.CommandLine -match 'app\.py') } | Select-Object -ExpandProperty ProcessId"`) do (
    taskkill /PID %%P /F >nul 2>nul
)

set "PYTHON_CMD=python"
where python >nul 2>nul
if %errorlevel%==0 goto :python_found

where py >nul 2>nul
if not %errorlevel%==0 (
    echo Python was not found on PATH.
    echo Install Python 3 for Windows from https://www.python.org/downloads/
    pause
    goto :eof
)

set "PYTHON_CMD=py -3"
%PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not %errorlevel%==0 (
    echo Python 3.10 or newer is required.
    echo Install Python 3 for Windows from https://www.python.org/downloads/
    pause
    goto :eof
)

:python_found

%PYTHON_CMD% -m pip install --user -r requirements.txt
if not %errorlevel%==0 (
    echo Failed to install Python packages.
    pause
    goto :eof
)

%PYTHON_CMD% -c "import os, sys, psycopg; conn = psycopg.connect(os.environ['TREASURER_DATABASE_URL']); exists = conn.execute(\"SELECT to_regclass('public.users')\").fetchone()[0]; sys.exit(0 if exists else 1)" >nul 2>nul
if not %errorlevel%==0 (
    %PYTHON_CMD% -m flask --app app init-db
    if not %errorlevel%==0 (
        echo Failed to initialize the database.
        pause
        goto :eof
    )
)

start "" http://127.0.0.1:5000/
%PYTHON_CMD% -m flask --app app run --debug
