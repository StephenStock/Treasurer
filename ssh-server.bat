@echo off
setlocal

REM Interactive SSH to the Hetzner server (same defaults as deploy.bat).
REM
REM Usage:
REM   ssh-server.bat                     Connect to default host below
REM   ssh-server.bat 203.0.113.50      Use this host for this run
REM   set DEPLOY_HOST=203.0.113.50       Persist host for the session, then ssh-server.bat

if not "%~1"=="" (
  set "DEPLOY_HOST=%~1"
) else if not defined DEPLOY_HOST (
  set "DEPLOY_HOST=91.99.170.73"
)

ssh steve@%DEPLOY_HOST%
set "EXITCODE=%ERRORLEVEL%"
exit /b %EXITCODE%
