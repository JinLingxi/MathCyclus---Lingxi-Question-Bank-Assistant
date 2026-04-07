@echo off
setlocal
cd /d "%~dp0"

echo [Solaire] Checking backend http://127.0.0.1:8000 ...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest 'http://127.0.0.1:8000/api/health' -TimeoutSec 2 -UseBasicParsing; if ($r.StatusCode -ne 200) { exit 1 } } catch { exit 1 }"
if %ERRORLEVEL%==0 (
  echo [Solaire] Backend already running — skip starting uvicorn ^(avoids WinError 10048^).
  goto :frontend
)

powershell -NoProfile -Command "$l = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($l) { exit 2 } else { exit 0 }"
if %ERRORLEVEL%==2 (
  echo [Solaire] ERROR: Port 8000 is in use but /api/health did not succeed. End the process on 8000 ^(Task Manager^) or run: netstat -ano ^| findstr :8000
  echo [Solaire] Starting frontend only.
  goto :frontend
)

echo [Solaire] Starting backend http://127.0.0.1:8000 ...
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  start "Solaire Web - Backend" cmd /k "py -3.12 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
) else (
  start "Solaire Web - Backend" cmd /k "python -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
)
timeout /t 2 /nobreak >nul

:frontend
echo [Solaire] Starting frontend http://127.0.0.1:5173 ...
start "Solaire Web - Frontend" cmd /k "cd /d %~dp0web && npm run dev"
echo Done. Two windows opened ^(or one if backend was already up^).
pause
