@echo off
setlocal

set "DEPLOY_HOST=18.130.77.196"
set "DEPLOY_USER=ubuntu"
set "DEPLOY_KEY=%USERPROFILE%\.ssh\lodge-app.pem"
set "REMOTE_CMD=if [ -d ~/5217/.git ]; then cd ~/5217; else git clone https://github.com/StephenStock/5217.git ~/5217 && cd ~/5217; fi && git remote set-url origin https://github.com/StephenStock/5217.git && git fetch origin main && git reset --hard origin/main && bash deploy/deploy.sh"

echo Starting deploy to %DEPLOY_USER%@%DEPLOY_HOST%...

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
if errorlevel 1 (
    echo Deploy failed.
    exit /b 1
)

echo Deploy completed successfully.
echo Check the output above for the branch and commit that reached Lightsail.

exit /b 0

endlocal
