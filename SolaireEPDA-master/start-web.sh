#!/usr/bin/env bash
# Solaire Web UI — 一键启动（macOS / Linux）
# 用法: chmod +x start-web.sh && ./start-web.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[Solaire] 仓库: $ROOT"
echo "[Solaire] 启动 FastAPI → http://127.0.0.1:8000"

if command -v py >/dev/null 2>&1; then
  (cd "$ROOT" && py -3.12 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000) &
elif command -v python3 >/dev/null 2>&1; then
  (cd "$ROOT" && python3 -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000) &
elif command -v python >/dev/null 2>&1; then
  (cd "$ROOT" && python -m uvicorn solaire.web.app:app --host 127.0.0.1 --port 8000) &
else
  echo "未找到 py / python3 / python。请安装 Python 3.11+ 并 pip install -e ." >&2
  exit 1
fi

UV_PID=$!
cleanup() { kill "$UV_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

sleep 2
echo "[Solaire] 启动 Vite → http://127.0.0.1:5173"
cd "$ROOT/web"
npm run dev
