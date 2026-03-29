@echo off
cd /d "%~dp0"

if "%LOCALAPPDATA%"=="" set "LOCALAPPDATA=%USERPROFILE%\AppData\Local"
set "APP_DATA=%LOCALAPPDATA%\Treasurer"
set "INSTANCE_DIR=%~dp0instance"
if "%TREASURER_DATABASE%"=="" set "TREASURER_DATABASE=%INSTANCE_DIR%\Treasurer.db"
set "TEMP=%APP_DATA%\tmp"
set "TMP=%TEMP%"

if not exist "%APP_DATA%" mkdir "%APP_DATA%"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%INSTANCE_DIR%" mkdir "%INSTANCE_DIR%"

if not exist "%TREASURER_DATABASE%" if exist "%APP_DATA%\Treasurer.db" copy /Y "%APP_DATA%\Treasurer.db" "%TREASURER_DATABASE%" >nul

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

for /f "usebackq delims=" %%I in (`%PYTHON_CMD% -c "import sys; print(sys.executable)"`) do set "PYTHON_EXE=%%I"

%PYTHON_CMD% -c "import os, sqlite3, sys; conn = sqlite3.connect(os.environ['TREASURER_DATABASE']); exists = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table' AND name='reporting_periods'\").fetchone(); sys.exit(0 if exists else 1)" >nul 2>nul
if not %errorlevel%==0 (
    %PYTHON_CMD% -m flask --app app init-db
    if errorlevel 1 (
        echo Failed to initialize the database.
        pause
        goto :eof
    )
)

start "" http://127.0.0.1:5000/
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -PassThru -WindowStyle Hidden -WorkingDirectory (Get-Location).Path -FilePath '%PYTHON_EXE%' -ArgumentList @('-m','flask','--app','app','run','--debug'); $p.Id"`) do set "FLASK_PID=%%P"
echo.
echo Treasurer is running.
echo Press any key to stop it.
pause >nul
taskkill /PID %FLASK_PID% /T /F >nul 2>nul
