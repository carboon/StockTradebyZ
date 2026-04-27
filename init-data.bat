@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0init-data.ps1" %*
exit /b %errorlevel%
