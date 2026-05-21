@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ================================================
echo    IPO App - 시작프로그램 등록
echo ================================================
echo.

REM 관리자 권한 확인
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 관리자 권한이 필요합니다.
    echo 이 파일을 마우스 우클릭 후 "관리자 권한으로 실행"을 선택해주세요.
    echo.
    pause
    exit /b 1
)

REM 현재 경로를 절대 경로로 변환
for /f "tokens=*" %%i in ('cd') do set "CURRENT_PATH=%%i"
set "VBS_PATH=%CURRENT_PATH%\run_app.vbs"

REM 레지스트리에 등록
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "IPOApp" /t REG_SZ /d "wscript.exe \"%VBS_PATH%\"" /f

if %errorlevel% == 0 (
    echo.
    echo [OK] 시작프로그램 등록 완료!
    echo Windows 시작 시 공모주 앱이 자동으로 실행됩니다.
    echo.
) else (
    echo.
    echo [ERROR] 등록에 실패했습니다.
    echo 관리자 권한이 있는지 확인해주세요.
    echo.
)

pause
