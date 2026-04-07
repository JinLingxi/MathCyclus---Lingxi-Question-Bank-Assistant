# 【已弃用】默认桌面打包已改为 scripts/stage-python-runtime.ps1（嵌入式 Python）。
# 使用 Nuitka 将 solaire 桌面服务入口编译为 Windows 单文件可执行（无控制台）。
# 需已安装：Python 3.11+、MSVC Build Tools、pip install nuitka ordered-set zstandard
# 在仓库根目录执行：.\scripts\nuitka-solaire.ps1
#
# 若存在仓库内 Conda 环境 .conda-solaire（python 3.12），将优先使用，并设置 PYTHONNOUSERSITE=1，
# 避免混入用户目录 site-packages（减少 Nuitka 误扫 matplotlib/Qt 等）。

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$outDir = Join-Path $repoRoot "nuitka_build"
$targetExe = Join-Path $outDir "solaire-server.exe"
$sidecarName = "solaire-server-x86_64-pc-windows-msvc.exe"
$binariesDir = Join-Path $repoRoot "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null

$condaPy = Join-Path $repoRoot ".conda-solaire\python.exe"
if (Test-Path $condaPy) {
  $pyExe = $condaPy
  $pyPrefix = @()
  $env:PYTHONNOUSERSITE = "1"
  Write-Host "==> 使用仓库 Conda 环境: .conda-solaire (PYTHONNOUSERSITE=1)" -ForegroundColor Cyan
} else {
  $pyExe = "py"
  if (-not (Get-Command py -ErrorAction SilentlyContinue)) { $pyExe = "python" }
  $pyPrefix = @("-3.12")
  if (Test-Path env:PYTHONNOUSERSITE) { Remove-Item env:PYTHONNOUSERSITE }
}

Write-Host "==> Nuitka 编译本地服务（耗时较长）..." -ForegroundColor Cyan
& $pyExe @pyPrefix -m pip install -q nuitka ordered-set zstandard

$nuitkaArgs = @(
  "--standalone", "--onefile",
  "--assume-yes-for-downloads",
  "--output-dir=$outDir",
  "--output-filename=solaire-server.exe",
  "--windows-console-mode=disable",
  "--include-package=solaire",
  "--include-package=uvicorn",
  "--include-package=fastapi",
  "--include-package=pydantic",
  "--include-package=starlette",
  "--include-package-data=solaire.exam_compiler",
  "--include-data-dir=src/solaire_doc=src/solaire_doc",
  "--include-data-dir=src/solaire/web/bundled_project_templates/math=sample_project",
  "src/solaire/desktop_entry.py"
)

$invokeArgs = $pyPrefix + @("-m", "nuitka") + $nuitkaArgs
& $pyExe @invokeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$built = Join-Path $outDir "solaire-server.exe"
if (-not (Test-Path $built)) {
  Write-Error "未找到输出：$built"
}

Copy-Item -Force $built (Join-Path $binariesDir $sidecarName)
Write-Host "==> 已复制到 src-tauri/binaries/$sidecarName" -ForegroundColor Green
