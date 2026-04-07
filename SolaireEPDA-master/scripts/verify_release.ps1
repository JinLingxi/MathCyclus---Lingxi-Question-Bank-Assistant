# 发布前本地验证：pytest（含 choice_layout）+ 可选 LaTeX 示例卷构建。
# 用法：在仓库根目录执行 .\scripts\verify_release.ps1
# 若未安装 TeX，gaokao_sample 构建步骤会失败，可改用 -SkipTex 跳过。

param([switch]$SkipTex)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "==> pytest (full suite, includes test_choice_layout)" -ForegroundColor Cyan
python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipTex) {
  Write-Host "==> ExamCompiler build: examples/gaokao_sample/exam.yaml (requires latexmk/xelatex)" -ForegroundColor Cyan
  python -m solaire.exam_compiler.cli build examples/gaokao_sample/exam.yaml -v
  if ($LASTEXITCODE -ne 0) {
    Write-Host "TeX build failed. Re-run with -SkipTex if TeX is not installed, or close open PDFs on Windows." -ForegroundColor Yellow
    exit $LASTEXITCODE
  }
} else {
  Write-Host "==> Skipped gaokao_sample build (-SkipTex)" -ForegroundColor Yellow
}

Write-Host "OK: verify_release completed." -ForegroundColor Green
