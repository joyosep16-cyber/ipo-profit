@echo off
cd /d "%~dp0"

set PYTHON=C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe

echo =============================================
echo    IPO App - Install
echo =============================================
echo.

"%PYTHON%" --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.14 not found.
    echo Path: %PYTHON%
    pause
    exit /b 1
)

echo Python OK.
echo.
echo Installing packages...
echo.

"%PYTHON%" -m pip install -r requirements.txt --quiet

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Package installation failed.
    pause
    exit /b 1
)

echo.
echo =============================================
echo    Done! Run "공모주앱 실행.bat" to start.
echo =============================================
echo.
pause
