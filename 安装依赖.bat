@echo off
chcp 65001 >nul 2>&1
title YTSubViewer - 安装依赖
cd /d "%~dp0"
call .venv\Scripts\activate
pip install -r requirements.txt
echo.
echo 依赖安装完成，按任意键关闭。
pause >nul
