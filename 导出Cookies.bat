@echo off
chcp 65001 >nul 2>&1
title 导出 YouTube Cookies
cd /d "%~dp0"
call .venv\Scripts\activate
python 导出YouTubeCookies.py
