@echo off
setlocal

REM One-click deploy from Windows: runs bash scripts/deploy.sh on the Hetzner server over SSH.
REM Requires: OpenSSH client (Windows 10/11: usually already installed), and SSH key or password to the server.
REM
REM Usage:
REM   deploy.bat                     Default host 91.99.170.73 (edit below if yours differs)
REM   deploy.bat 203.0.113.50        Use this host for this run
REM   set DEPLOY_HOST=203.0.113.50   Persist host for the session, then deploy.bat

cd /d "%~dp0"

if not "%~1"=="" (
  set "DEPLOY_HOST=%~1"
) else if not defined DEPLOY_HOST (
  set "DEPLOY_HOST=91.99.170.73"
)

echo Deploying to steve@%DEPLOY_HOST% ...
ssh steve@%DEPLOY_HOST% "cd /opt/treasurer && bash scripts/deploy.sh"
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Deploy failed with exit code %EXITCODE%.
  exit /b %EXITCODE%
)
echo.
echo Deploy finished OK.
exit /b 0
