@echo off
title Jarvis Assistant
cd /d "%~dp0"
python -m desktop_client.tray_app %*
pause
