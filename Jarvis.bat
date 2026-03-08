@echo off
title Jarvis Assistant
cd /d "%~dp0"
python scripts\start_all.py --profile dev %*
pause
