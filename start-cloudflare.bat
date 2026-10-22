@echo off
chcp 65001 >nul
title Hermes Token Dashboard - Cloudflare Tunnel

echo ========================================================
echo   Hermes Token Dashboard + Cloudflare Tunnel
echo ========================================================
echo.

:: 1. Check if server.py is already running on port 8787
netstat -ano | findstr ":8787" | findstr "LISTENING" >nul
if %errorlevel% neq 0 (
    echo [1/2] Starting server.py in background...
    start "" /b python server.py
    timeout /t 2 >nul
) else (
    echo [1/2] server.py is already running on port 8787.
)

:: 2. Locate cloudflared
set CLOUDFLARED=%LOCALAPPDATA%\cloudflared.exe
if not exist "%CLOUDFLARED%" (
    where cloudflared >nul 2>nul
    if %errorlevel% equ 0 (
        set CLOUDFLARED=cloudflared
    ) else (
        echo [ERROR] cloudflared.exe not found at %CLOUDFLARED%
        pause
        exit /b 1
    )
)

echo [2/2] Starting Cloudflare Tunnel...
echo.
echo ========================================================
echo   Waiting for Cloudflare Public URL (trycloudflare.com)...
echo   (Press Ctrl+C to stop)
echo ========================================================
echo.

"%CLOUDFLARED%" tunnel --url http://127.0.0.1:8787
pause
