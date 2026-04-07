# Solaire Web UI — 一键启动后端 + 前端（本机开发）
# 在仓库根目录执行:  .\start-web.ps1

$ErrorActionPreference = "Stop"
$repoRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $repoRoot

$uvicornLine = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
  $uvicornLine = "Set-Location '$repoRoot'; py -3.12 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $uvicornLine = "Set-Location '$repoRoot'; python -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
  $uvicornLine = "Set-Location '$repoRoot'; python3 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000"
} else {
  Write-Error "未找到 py / python / python3。请安装 Python 3.11+ 并 pip install -e ."
}

Write-Host "仓库: $repoRoot"
Write-Host "启动 FastAPI → http://127.0.0.1:8000"
Start-Process pwsh -ArgumentList "-NoExit", "-Command", $uvicornLine

Start-Sleep -Seconds 2

$viteLine = "Set-Location '$repoRoot\web'; npm run dev"
Write-Host "启动 Vite → http://127.0.0.1:5173"
Start-Process pwsh -ArgumentList "-NoExit", "-Command", $viteLine

Write-Host "已打开两个终端窗口。浏览器访问 http://127.0.0.1:5173"
