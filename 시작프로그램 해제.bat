@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ================================================
echo    IPO App - 시작프로그램 해제
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

REM 레지스트리에서 해제
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "IPOApp" /f 2>nul

if %errorlevel% == 0 (
    echo.
    echo [OK] 시작프로그램 해제 완료!
    echo Windows 시작 시 공모주 앱이 자동 실행되지 않습니다.
    echo.
) else (
    echo.
    echo [INFO] 등록된 시작프로그램이 없습니다.
    echo.
)

pause
