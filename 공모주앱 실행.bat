@echo off
cd /d "%~dp0"
"C:\Users\ADMIN\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app.py --browser.gatherUsageStats false
pause
