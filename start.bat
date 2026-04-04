@echo off
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "APP_DATA=%LOCALAPPDATA%\Treasurer"
set "LOCAL_DB_DIR=%~dp0"
set "VENV_DIR=%~dp0.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
if exist "%~dp0config.local" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0config.local") do (
        if /i "%%A"=="TREASURER_DATABASE" if not defined TREASURER_DATABASE set "TREASURER_DATABASE=%%B"
        if /i "%%A"=="TREASURER_BACKUP_DATABASE" if not defined TREASURER_BACKUP_DATABASE set "TREASURER_BACKUP_DATABASE=%%B"
    )
)
if "%TREASURER_DATABASE%"=="" set "TREASURER_DATABASE=%LOCAL_DB_DIR%\Treasurer.db"
set "TEMP=%APP_DATA%\tmp"
set "TMP=%TEMP%"

if not exist "%APP_DATA%" mkdir "%APP_DATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%LOCAL_DB_DIR%" mkdir "%LOCAL_DB_DIR%"

set "EXIT_SIGNAL=%TEMP%\treasurer.exit"
if exist "%EXIT_SIGNAL%" del /f /q "%EXIT_SIGNAL%" >nul 2>nul

set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    where py >nul 2>nul
    if errorlevel 1 (
        echo Python was not found on PATH.
        echo Install Python 3 for Windows from https://www.python.org/downloads/
        pause
        goto :eof
    )

    set "PYTHON_CMD=py -3"
    %PYTHON_CMD% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is required.
        echo Install Python 3 for Windows from https://www.python.org/downloads/
        pause
        goto :eof
    )
)

if not exist "%VENV_PYTHON%" (
    echo Creating local virtual environment...
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo Failed to create the virtual environment.
        pause
        goto :eof
    )
)

set "PYTHON_EXE=%VENV_PYTHON%"
"%VENV_PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install Python packages.
    pause
    goto :eof
)

set "TREASURER_BACKUP_FOLDER="

if defined TREASURER_BACKUP_DATABASE (
    for %%I in ("%TREASURER_BACKUP_DATABASE%") do (
        if /i "%%~xI"==".db" (
            set "TREASURER_BACKUP_FOLDER=%%~dpI"
        ) else (
            set "TREASURER_BACKUP_FOLDER=%%~fI"
            set "TREASURER_BACKUP_DATABASE=%%~fI\Treasurer.backup.db"
        )
    )
)

if not defined TREASURER_BACKUP_FOLDER (
    if exist "%USERPROFILE%\Documents" (
        set "TREASURER_BACKUP_FOLDER=%USERPROFILE%\Documents\Treasurer Backups"
    ) else if defined OneDriveCommercial (
        set "TREASURER_BACKUP_FOLDER=%OneDriveCommercial%\Treasurer Backups"
    ) else if defined OneDriveConsumer (
        set "TREASURER_BACKUP_FOLDER=%OneDriveConsumer%\Treasurer Backups"
    ) else if defined OneDrive (
        set "TREASURER_BACKUP_FOLDER=%OneDrive%\Treasurer Backups"
    ) else (
        set "TREASURER_BACKUP_FOLDER=%USERPROFILE%\Treasurer Backups"
    )
)

if not defined TREASURER_BACKUP_DATABASE set "TREASURER_BACKUP_DATABASE=%TREASURER_BACKUP_FOLDER%\Treasurer.backup.db"

set "TREASURER_BACKUP_FOLDER_CAPTURE=%TEMP%\treasurer_backup_folder.txt"
set "TREASURER_BACKUP_DATABASE_CAPTURE=%TEMP%\treasurer_backup_database.txt"
if exist "%TREASURER_BACKUP_FOLDER_CAPTURE%" del /f /q "%TREASURER_BACKUP_FOLDER_CAPTURE%" >nul 2>nul
if exist "%TREASURER_BACKUP_DATABASE_CAPTURE%" del /f /q "%TREASURER_BACKUP_DATABASE_CAPTURE%" >nul 2>nul

"%PYTHON_EXE%" -c "import os; from pathlib import Path; from treasurer_app.db import resolve_backup_folder_path; print(resolve_backup_folder_path(Path(os.environ['TREASURER_DATABASE'])))" > "%TREASURER_BACKUP_FOLDER_CAPTURE%"
if not errorlevel 1 if exist "%TREASURER_BACKUP_FOLDER_CAPTURE%" (
    set /p "TREASURER_BACKUP_FOLDER="<"%TREASURER_BACKUP_FOLDER_CAPTURE%"
)

"%PYTHON_EXE%" -c "import os; from pathlib import Path; from treasurer_app.db import resolve_backup_database_path; print(resolve_backup_database_path(Path(os.environ['TREASURER_DATABASE'])))" > "%TREASURER_BACKUP_DATABASE_CAPTURE%"
if not errorlevel 1 if exist "%TREASURER_BACKUP_DATABASE_CAPTURE%" (
    set /p "TREASURER_BACKUP_DATABASE="<"%TREASURER_BACKUP_DATABASE_CAPTURE%"
)

if exist "%TREASURER_BACKUP_FOLDER_CAPTURE%" del /f /q "%TREASURER_BACKUP_FOLDER_CAPTURE%" >nul 2>nul
if exist "%TREASURER_BACKUP_DATABASE_CAPTURE%" del /f /q "%TREASURER_BACKUP_DATABASE_CAPTURE%" >nul 2>nul

echo Live database: %TREASURER_DATABASE%
echo Backup folder: %TREASURER_BACKUP_FOLDER%
echo Backup file: %TREASURER_BACKUP_DATABASE%

if not exist "%TREASURER_DATABASE%" (
    if exist "%TREASURER_BACKUP_DATABASE%" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_treasurer_db.ps1" -PrimaryDb "%TREASURER_DATABASE%" -BackupDb "%TREASURER_BACKUP_DATABASE%" -Mode Restore
    )
)

if not exist "%TREASURER_DATABASE%" (
    "%PYTHON_EXE%" -m flask --app app init-db
    if errorlevel 1 (
        echo Failed to initialize the database.
        pause
        goto :eof
    )
) else (
    "%PYTHON_EXE%" -c "import os, sqlite3, sys; conn = sqlite3.connect(os.environ['TREASURER_DATABASE']); exists = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='reporting_periods'\").fetchone(); sys.exit(0 if exists else 1)" >nul 2>nul
    if errorlevel 1 (
        "%PYTHON_EXE%" -m flask --app app init-db
        if errorlevel 1 (
            echo Failed to initialize the database.
            pause
            goto :eof
        )
    )
)

"%PYTHON_EXE%" -m flask --app app check-runtime-lock
if errorlevel 1 (
    echo You cant run here unless you shut the other one down.
    pause
    goto :eof
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [Regex]::Escape((Get-Location).Path); $processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw)\.exe$' -and $_.CommandLine -and ($_.CommandLine -match $root -or $_.CommandLine -match 'treasurer_app' -or $_.CommandLine -match 'flask(\.exe)?\s+--app\s+app\s+run' -or $_.CommandLine -match 'app\.py') }; $processes | Select-Object -ExpandProperty ProcessId"`) do (
    taskkill /PID %%P /F >nul 2>nul
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"`) do (
    taskkill /PID %%P /F >nul 2>nul
)

start "" http://127.0.0.1:5000/
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Get-Location).Path -FilePath '%PYTHON_EXE%' -ArgumentList @('-m','flask','--app','app','run','--no-reload'); $p.Id"`) do set "FLASK_PID=%%P"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -WindowStyle Hidden -WorkingDirectory (Get-Location).Path -FilePath 'powershell' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0scripts\watch_treasurer_launch.ps1','-FlaskPid','%FLASK_PID%','-ExitSignalPath','%EXIT_SIGNAL%','-PrimaryDb','%TREASURER_DATABASE%','-BackupDb','%TREASURER_BACKUP_DATABASE%') | Out-Null"
exit /b
