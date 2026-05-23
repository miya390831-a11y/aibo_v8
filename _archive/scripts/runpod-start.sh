#!/bin/bash
# AIBO Studio v8 — RunPod fullstack: FastAPI :8000 + Next.js :3000
set -euo pipefail

BACKEND_DIR="${BACKEND_DIR:-/workspace/aibo}"
FRONTEND_DIR="${FRONTEND_DIR:-/app}"

echo "[AIBO] FastAPI + 同期オーケストラ初期化 (初回は数十分かかることがあります) ..."
cd "$BACKEND_DIR"
python -u 19_runpod_combined_entry.py &
API_PID=$!

cleanup() {
  echo "[AIBO] Shutting down (API pid=$API_PID)"
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 同期ブートストラップ中は 8000 が開かない · 最大 2 時間待機 (5秒 × 1440)
echo "[AIBO] Uvicorn 起動を待機中 (同期初期化が終わるまでポート非応答のことがあります) ..."
for i in $(seq 1 1440); do
  if curl -sf "http://127.0.0.1:8000/api/system/status" >/dev/null 2>&1; then
    echo "[AIBO] FastAPI ready (checks=${i})"
    break
  fi
  sleep 5
done

echo "[AIBO] Starting Next.js on :${PORT:-3000} ..."
cd "$FRONTEND_DIR"
export NODE_ENV=production
export HOSTNAME="${HOSTNAME:-0.0.0.0}"
export PORT="${PORT:-3000}"
exec node server.js
