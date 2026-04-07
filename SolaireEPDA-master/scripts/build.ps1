# SolEdu Windows 一键构建：可选 Rust 扩展 → 前端 → 嵌入式 Python 运行时 → Tauri 安装包
# 用法（仓库根目录）：.\scripts\build.ps1
# 需：Rust、Node 20+、MSVC、（可选）maturin、cargo-tauri（cargo install tauri-cli）

param(
  [switch]$SkipRust,
  [switch]$SkipPythonRuntime,
  [switch]$SkipNuitka,
  [switch]$SkipTauri
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

Write-Host "仓库: $repoRoot" -ForegroundColor Cyan

$skipPy = $SkipPythonRuntime -or $SkipNuitka
if ($SkipNuitka -and -not $SkipPythonRuntime) {
  Write-Host "提示: -SkipNuitka 已弃用，请改用 -SkipPythonRuntime（含义相同）" -ForegroundColor Yellow
}

if (-not $SkipRust) {
  if (Get-Command maturin -ErrorAction SilentlyContinue) {
    Write-Host "==> maturin build (primebrush-pyo3)" -ForegroundColor Cyan
    Push-Location (Join-Path $repoRoot "primebrush-rs")
    try {
      maturin build -m crates/primebrush-pyo3/Cargo.toml --release
    } catch {
      Write-Host "maturin 跳过或失败（将使用纯 Python PrimeBrush）: $_" -ForegroundColor Yellow
    }
    Pop-Location
  } else {
    Write-Host "未安装 maturin，跳过 PyO3 编译" -ForegroundColor Yellow
  }
}

Write-Host "==> 前端 npm ci + build" -ForegroundColor Cyan
Push-Location (Join-Path $repoRoot "web")
npm ci
npm run build
Pop-Location

if (-not $skipPy) {
  & (Join-Path $repoRoot "scripts\stage-python-runtime.ps1")
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  $pyw = Join-Path $repoRoot "src-tauri\runtime\python\pythonw.exe"
  if (-not (Test-Path $pyw)) {
    Write-Error "嵌入式 Python 未就绪: $pyw"
  }
} else {
  Write-Host '跳过嵌入式 Python（SkipPythonRuntime / SkipNuitka）' -ForegroundColor Yellow
}

if (-not $SkipTauri) {
  $wixCandle = Join-Path $env:LOCALAPPDATA "cache\tauri\WixTools314\candle.exe"
  if (-not (Test-Path $wixCandle)) {
    Write-Host "==> 预下载 WiX（避免 Tauri 从 GitHub 拉取时超时）" -ForegroundColor Cyan
    & (Join-Path $repoRoot "scripts\prepare-wix-tools.ps1")
    if ($LASTEXITCODE -ne 0) {
      Write-Host "WiX 预下载失败。可手动执行 .\scripts\prepare-wix-tools.ps1，或设置镜像 TAURI_BUNDLER_TOOLS_GITHUB_MIRROR（见 docs/desktop-build.md）" -ForegroundColor Red
      exit $LASTEXITCODE
    }
  }
  Write-Host "==> Tauri 打包（npm run tauri:build 或已安装 cargo tauri-cli）" -ForegroundColor Cyan
  Set-Location $repoRoot
  if (Test-Path (Join-Path $repoRoot "node_modules\@tauri-apps\cli")) {
    npm run tauri:build
  } else {
    Write-Host "根目录未 npm install，尝试 cargo tauri build（需 cargo install tauri-cli；须在仓库根目录执行）" -ForegroundColor Yellow
    Set-Location $repoRoot
    cargo tauri build
    if ($LASTEXITCODE -ne 0) {
      Write-Host "cargo tauri build 失败，回退为仅编译 src-tauri release 二进制" -ForegroundColor Yellow
      Push-Location (Join-Path $repoRoot "src-tauri")
      cargo build --release
      Pop-Location
    }
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Tauri 打包失败，退出码 $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
  }
  Write-Host "完成。安装包通常在 src-tauri/target/release/bundle/msi/" -ForegroundColor Green
} else {
  Write-Host '跳过 Tauri（SkipTauri）' -ForegroundColor Yellow
}
