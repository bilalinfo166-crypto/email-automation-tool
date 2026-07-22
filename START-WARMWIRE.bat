@echo off
title WarmWire Server
cd /d "C:\Users\Dell\Desktop\files"
echo Purane server band kar raha hoon...
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 /nobreak >nul
echo Browser khol raha hoon...
start "" http://127.0.0.1:8000/
echo.
echo  ==> Is window ko BAND MAT KARO. Server yahin chalta hai.
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
