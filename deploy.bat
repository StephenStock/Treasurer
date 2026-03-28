@echo off
setlocal

set "DEPLOY_HOST=18.130.77.196"
set "DEPLOY_USER=ubuntu"
set "DEPLOY_KEY=%USERPROFILE%\.ssh\lodge-app.pem"
set "REMOTE_CMD=cd ~/Treasurer && bash deploy/deploy.sh"

where ssh >nul 2>nul
if errorlevel 1 (
    echo OpenSSH client was not found on PATH.
    echo Install the Windows OpenSSH client, then try again.
    exit /b 1
)

if not exist "%DEPLOY_KEY%" (
    echo SSH key not found at:
    echo   %DEPLOY_KEY%
    echo.
    echo Download the Lightsail private key or update DEPLOY_KEY to your key path.
    exit /b 1
)

ssh -i "%DEPLOY_KEY%" -o StrictHostKeyChecking=accept-new %DEPLOY_USER%@%DEPLOY_HOST% "%REMOTE_CMD%"

endlocal
