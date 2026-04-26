@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0status-local.ps1" %*
exit /b %errorlevel%
