@echo off
chcp 65001 >nul
title AOTR Farm Assistant - Cai dat
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Hay cai Python 3.10+ tu https://www.python.org/downloads/
    echo       Nho tich "Add python.exe to PATH" khi cai.
    pause
    exit /b 1
)

if not exist .venv (
    echo Dang tao moi truong ao .venv ...
    python -m venv .venv || goto :error
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :error

echo.
python -m aotr_farm --check
echo.
echo Cai dat xong! Chay run.bat de mo chuong trinh.
pause
exit /b 0

:error
echo [LOI] Cai dat that bai. Xem thong bao phia tren.
pause
exit /b 1
