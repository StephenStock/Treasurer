@echo off
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "APP_DATA=%LOCALAPPDATA%\Treasurer"
set "LOCAL_DB_DIR=C:\TreasurerDB"
if "%TREASURER_DATABASE%"=="" set "TREASURER_DATABASE=%LOCAL_DB_DIR%\Treasurer.db"
set "TEMP=%APP_DATA%\tmp"
set "TMP=%TEMP%"

if not exist "%APP_DATA%" mkdir "%APP_DATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%LOCAL_DB_DIR%" mkdir "%LOCAL_DB_DIR%"
if not exist "%LOCAL_DB_DIR%" (
    set "LOCAL_DB_DIR=%APP_DATA%\TreasurerDB"
    set "TREASURER_DATABASE=%LOCAL_DB_DIR%\Treasurer.db"
    if not exist "%LOCAL_DB_DIR%" mkdir "%LOCAL_DB_DIR%"
    echo Using fallback local database folder.
)

set "EXIT_SIGNAL=%TEMP%\treasurer.exit"
if exist "%EXIT_SIGNAL%" del /f /q "%EXIT_SIGNAL%" >nul 2>nul

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [Regex]::Escape((Get-Location).Path); $processes = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw)\.exe$' -and $_.CommandLine -and ($_.CommandLine -match $root -or $_.CommandLine -match 'treasurer_app' -or $_.CommandLine -match 'flask(\.exe)?\s+--app\s+app\s+run' -or $_.CommandLine -match 'app\.py') }; $processes | Select-Object -ExpandProperty ProcessId"`) do (
    taskkill /PID %%P /F >nul 2>nul
)

for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"`) do (
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

for /f "usebackq delims=" %%I in (`%PYTHON_CMD% -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"
for /f "usebackq delims=" %%F in (`%PYTHON_CMD% -c "import os; from pathlib import Path; from treasurer_app.db import resolve_backup_folder_path; print(resolve_backup_folder_path(Path(os.environ['TREASURER_DATABASE'])))"`) do set "TREASURER_BACKUP_FOLDER=%%F"
for /f "usebackq delims=" %%B in (`%PYTHON_CMD% -c "import os; from pathlib import Path; from treasurer_app.db import resolve_backup_database_path; print(resolve_backup_database_path(Path(os.environ['TREASURER_DATABASE'])))"`) do set "TREASURER_BACKUP_DATABASE=%%B"

echo Live database: %TREASURER_DATABASE%
echo Backup folder: %TREASURER_BACKUP_FOLDER%
echo Backup file: %TREASURER_BACKUP_DATABASE%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_treasurer_db.ps1" -PrimaryDb "%TREASURER_DATABASE%" -BackupDb "%TREASURER_BACKUP_DATABASE%" -Mode SyncStart

if not exist "%TREASURER_DATABASE%" (
    %PYTHON_CMD% -m flask --app app init-db
    if errorlevel 1 (
        echo Failed to initialize the database.
        pause
        goto :eof
    )
) else (
    %PYTHON_CMD% -c "import os, sqlite3, sys; conn = sqlite3.connect(os.environ['TREASURER_DATABASE']); exists = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='reporting_periods'\").fetchone(); sys.exit(0 if exists else 1)" >nul 2>nul
    if not %errorlevel%==0 (
        %PYTHON_CMD% -m flask --app app init-db
        if errorlevel 1 (
            echo Failed to initialize the database.
            pause
            goto :eof
        )
    )
)

start "" http://127.0.0.1:5000/
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Get-Location).Path -FilePath '%PYTHON_EXE%' -ArgumentList @('-m','flask','--app','app','run','--debug','--no-reload'); $p.Id"`) do set "FLASK_PID=%%P"
echo.
echo Treasurer is running.
echo Use the Exit App button or press any key here to stop it.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$flaskPid = [int]%FLASK_PID%; $signalPath = '%EXIT_SIGNAL%'; while ($true) { if (Test-Path -LiteralPath $signalPath) { break } if (-not (Get-Process -Id $flaskPid -ErrorAction SilentlyContinue)) { break } if ($Host.UI.RawUI.KeyAvailable) { $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown'); try { Invoke-WebRequest -UseBasicParsing -Method Post -Uri 'http://127.0.0.1:5000/app/exit' | Out-Null } catch {}; break } Start-Sleep -Milliseconds 200 }; if (Get-Process -Id $flaskPid -ErrorAction SilentlyContinue) { Stop-Process -Id $flaskPid -Force }; Remove-Item -LiteralPath $signalPath -Force -ErrorAction SilentlyContinue"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\sync_treasurer_db.ps1" -PrimaryDb "%TREASURER_DATABASE%" -BackupDb "%TREASURER_BACKUP_DATABASE%" -Mode Backup
