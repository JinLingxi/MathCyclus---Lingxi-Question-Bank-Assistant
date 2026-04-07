# Tauri dev: FastAPI (8000) + Vite (5173). Invoked by src-tauri/tauri.conf.json beforeDevCommand.
# Saved as UTF-8 with BOM so Windows PowerShell parses Chinese literals correctly.
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

function Test-SolaireBackendUp {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2 -UseBasicParsing -ErrorAction Stop
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

function Get-ListenerOn8000 {
  try {
    return Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  } catch {
    # Get-NetTCPConnection may be unavailable on some SKUs.
    return $null
  }
}

# Dev mode should always run backend from current repo source.
$listener = Get-ListenerOn8000
if ($listener) {
  $pid = $listener.OwningProcess
  $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
  $cmdline = ""
  try {
    $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId = {0}" -f $pid) -ErrorAction SilentlyContinue
    if ($wmi -and $wmi.CommandLine) { $cmdline = [string]$wmi.CommandLine }
  } catch {
    # no-op
  }
  $isSolaireUvicorn = ($cmdline -match "uvicorn") -and ($cmdline -match "solaire\.web\.app:app")
  if ($isSolaireUvicorn) {
    Write-Host ("[dev-desktop] Found existing backend on 8000 (PID {0}); restarting to pick latest local code." -f $pid)
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800
  } else {
    $who = if ($proc) { "PID $($proc.Id) ($($proc.ProcessName))" } else { "unknown process" }
    Write-Error ("Port 8000 is in use by {0}. Please stop that process first, then retry tauri dev." -f $who)
    exit 1
  }
}

  $exe = $null
  $argsUv = @(
    "-m", "uvicorn", "solaire.web.app:app",
    "--app-dir", (Join-Path $repoRoot "src"),
    "--host", "127.0.0.1",
    "--port", "8000"
  )
  if (Get-Command py -ErrorAction SilentlyContinue) {
    $exe = "py"
    $argsUv = @("-3.12") + $argsUv
  } elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $exe = "python"
  } else {
    Write-Error "Python not found. Install 3.11+ and run: pip install -e ."
    exit 1
  }

  Start-Process -FilePath $exe -ArgumentList $argsUv -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null
  # Cold import of solaire can take several seconds; fixed 2s was often too short.
  $ready = $false
  for ($i = 0; $i -lt 45; $i++) {
    if (Test-SolaireBackendUp) { $ready = $true; break }
    Start-Sleep -Seconds 1
  }
  if (-not $ready) {
    Write-Error "Backend did not become ready on http://127.0.0.1:8000 within 45s. If uvicorn crashed, run in a terminal: py -3.12 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
    exit 1
  }

Set-Location (Join-Path $repoRoot "web")
npm run dev
