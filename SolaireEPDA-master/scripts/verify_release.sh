#!/usr/bin/env bash
# 发布前本地验证：pytest + 可选 gaokao_sample 构建（需 TeX）。
# 用法：bash scripts/verify_release.sh   或   SKIP_TEX=1 bash scripts/verify_release.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> pytest (full suite, includes test_choice_layout)"
python -m pytest -q

if [[ "${SKIP_TEX:-}" == "1" ]]; then
  echo "==> Skipped gaokao_sample build (SKIP_TEX=1)"
else
  echo "==> ExamCompiler build: examples/gaokao_sample/exam.yaml (requires latexmk/xelatex)"
  python -m solaire.exam_compiler.cli build examples/gaokao_sample/exam.yaml -v
fi

echo "OK: verify_release completed."
