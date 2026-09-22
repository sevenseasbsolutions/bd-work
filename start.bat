@echo off
REM MBS — API on 8000, frontend on 5174. Two windows; close either to stop it.
setlocal
cd /d "%~dp0"

if not exist "backend\.venv\Scripts\python.exe" (
  echo Making the backend virtualenv...
  python -m venv backend\.venv || goto :fail
  backend\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt || goto :fail
)
if not exist "frontend\node_modules" (
  echo Installing frontend packages...
  pushd frontend && call npm install || goto :fail
  popd
)

start "MBS API" cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload"
start "MBS web" cmd /k "cd /d %~dp0frontend && npm run dev"
echo.
echo   API  http://127.0.0.1:8000
echo   Web  http://127.0.0.1:5174
echo.
exit /b 0

:fail
echo Setup failed. See the messages above.
exit /b 1
