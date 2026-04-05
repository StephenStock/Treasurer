@echo off
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "APP_DATA=%LOCALAPPDATA%\LodgeOffice"
set "LOCAL_DB_DIR=%~dp0"
if exist "%~dp0config.local" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0config.local") do (
        if /i "%%A"=="TREASURER_DATABASE" if not defined TREASURER_DATABASE set "TREASURER_DATABASE=%%B"
        if /i "%%A"=="LODGE_OFFICE_DATABASE" if not defined LODGE_OFFICE_DATABASE set "LODGE_OFFICE_DATABASE=%%B"
        if /i "%%A"=="TREASURER_BACKUP_DATABASE" if not defined TREASURER_BACKUP_DATABASE set "TREASURER_BACKUP_DATABASE=%%B"
        if /i "%%A"=="LODGE_OFFICE_BACKUP_DATABASE" if not defined LODGE_OFFICE_BACKUP_DATABASE set "LODGE_OFFICE_BACKUP_DATABASE=%%B"
    )
)
if not defined TREASURER_DATABASE if defined LODGE_OFFICE_DATABASE set "TREASURER_DATABASE=%LODGE_OFFICE_DATABASE%"
if not defined TREASURER_BACKUP_DATABASE if defined LODGE_OFFICE_BACKUP_DATABASE set "TREASURER_BACKUP_DATABASE=%LODGE_OFFICE_BACKUP_DATABASE%"
if "%TREASURER_DATABASE%"=="" if "%LODGE_OFFICE_DATABASE%"=="" (
  if exist "%LOCAL_DB_DIR%LodgeOffice.db" (
    set "TREASURER_DATABASE=%LOCAL_DB_DIR%LodgeOffice.db"
  ) else if exist "%LOCAL_DB_DIR%Treasurer.db" (
    set "TREASURER_DATABASE=%LOCAL_DB_DIR%Treasurer.db"
  ) else (
    set "TREASURER_DATABASE=%LOCAL_DB_DIR%LodgeOffice.db"
  )
)
set "TEMP=%APP_DATA%\tmp"
set "TMP=%TEMP%"

if not exist "%APP_DATA%" mkdir "%APP_DATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%LOCAL_DB_DIR%" mkdir "%LOCAL_DB_DIR%"

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

echo Live database: %TREASURER_DATABASE%
%PYTHON_CMD% -m flask --app app unlock-runtime-lock
if not %errorlevel%==0 (
    echo Failed to clear the runtime lock.
    pause
    goto :eof
)

pause
