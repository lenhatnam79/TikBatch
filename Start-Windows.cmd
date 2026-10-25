@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -e .
if errorlevel 1 goto failed
.venv\Scripts\python.exe -m tikbatch
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Khong khoi chay duoc. Can Python 3.12 64-bit va ket noi Internet khi cai lan dau.
pause
exit /b 1
