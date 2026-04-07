# Stage Windows embeddable Python + pip install into src-tauri/runtime/python for Tauri bundle.resources.
# Run from repo root: .\scripts\stage-python-runtime.ps1
# Requires network: python.org, bootstrap.pypa.io (or pre-populate .cache/python-embed)

param(
  [string]$PythonVersion = "3.12.7",
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$runtimeRoot = Join-Path $repoRoot "src-tauri\runtime\python"
$cacheDir = Join-Path $repoRoot ".cache\python-embed"
$embedName = "python-$PythonVersion-embed-amd64.zip"
$embedUrl = "https://www.python.org/ftp/python/$PythonVersion/$embedName"
$getPipUrl = "https://bootstrap.pypa.io/get-pip.py"

New-Item -ItemType Directory -Force -Path $cacheDir | Out-Null

if ($Force -and (Test-Path $runtimeRoot)) {
  Write-Host "==> Remove old runtime: $runtimeRoot" -ForegroundColor Yellow
  Remove-Item -Recurse -Force $runtimeRoot
}

function Write-RuntimeReadmeStub {
  param([string]$Dir)
  $stub = @'
This folder is populated by scripts/stage-python-runtime.ps1 (embeddable Python + pip install).
Run that script or the full repo build (.\scripts\build.ps1) before packaging.
'@
  Set-Content -Path (Join-Path $Dir "README.txt") -Value $stub.Trim() -Encoding UTF8
}

function Sync-SampleProject {
  param([string]$RepoRoot)
  $sampleSrc = Join-Path $RepoRoot "src\solaire\web\bundled_project_templates\math"
  $sampleDst = Join-Path $RepoRoot "src-tauri\runtime\sample_project"
  if (-not (Test-Path $sampleSrc)) {
    Write-Warning "Sample project source missing: $sampleSrc"
    return
  }
  Write-Host "==> Sync built-in sample project -> $sampleDst" -ForegroundColor Cyan
  if (Test-Path $sampleDst) { Remove-Item -Recurse -Force $sampleDst }
  Copy-Item -Recurse -Force $sampleSrc $sampleDst
}

if ((Test-Path $runtimeRoot) -and (Test-Path (Join-Path $runtimeRoot "python.exe")) -and -not $Force) {
  Write-Host "==> Embedded Python already exists (use -Force to rebuild): $runtimeRoot" -ForegroundColor Cyan
  Sync-SampleProject -RepoRoot $repoRoot
  exit 0
}

$zipLocal = Join-Path $cacheDir $embedName
if (-not (Test-Path $zipLocal)) {
  Write-Host "==> Download embeddable: $embedUrl" -ForegroundColor Cyan
  Invoke-WebRequest -Uri $embedUrl -OutFile $zipLocal -UseBasicParsing
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
Write-RuntimeReadmeStub $runtimeRoot
Write-Host "==> Expand-Archive to $runtimeRoot" -ForegroundColor Cyan
Expand-Archive -Path $zipLocal -DestinationPath $runtimeRoot -Force

$pthPath = Get-ChildItem -Path $runtimeRoot -Filter "python*._pth" -File | Select-Object -First 1
if (-not $pthPath) {
  Write-Error "python*._pth not found under $runtimeRoot"
}
$pth = Get-Content -Path $pthPath.FullName -Raw
$pth = $pth -replace '#\s*import site', 'import site'
if ($pth -notmatch '(?m)^import site\s*$') {
  $pth = $pth.TrimEnd() + "`r`nimport site`r`n"
}
Set-Content -Path $pthPath.FullName -Value $pth -NoNewline

$pythonExe = Join-Path $runtimeRoot "python.exe"
$getPipPath = Join-Path $cacheDir "get-pip.py"
if (-not (Test-Path $getPipPath)) {
  Write-Host "==> Download get-pip.py" -ForegroundColor Cyan
  Invoke-WebRequest -Uri $getPipUrl -OutFile $getPipPath -UseBasicParsing
}

Write-Host "==> Install pip" -ForegroundColor Cyan
& $pythonExe $getPipPath --no-warn-script-location
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> pip install repo (may take a while)" -ForegroundColor Cyan
Push-Location $repoRoot
try {
  & $pythonExe -m pip install -U pip wheel setuptools
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $pythonExe -m pip install --no-warn-script-location .
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
  Pop-Location
}

# Optional: double-click to start local server (troubleshooting)
$bat = @'
@echo off
cd /d "%~dp0"
"%~dp0pythonw.exe" -m solaire.desktop_entry --port 8000
'@
Set-Content -Path (Join-Path $runtimeRoot "SolEdu-LocalServer.bat") -Value $bat -Encoding ASCII

Sync-SampleProject -RepoRoot $repoRoot

Write-Host "==> Done: $runtimeRoot" -ForegroundColor Green
