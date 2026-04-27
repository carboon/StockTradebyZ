@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap-local.ps1" %*
exit /b %errorlevel%
