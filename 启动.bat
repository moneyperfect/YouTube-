@echo off
chcp 65001 >nul 2>&1
title YTSubViewer
cd /d "%~dp0"
call .venv\Scripts\activate
python app.py
pause
