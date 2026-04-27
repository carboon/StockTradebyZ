@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0preflight-local.ps1" %*
exit /b %errorlevel%
