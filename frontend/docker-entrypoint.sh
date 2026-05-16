#!/bin/sh
# AIBO Studio v8.0 - Next.js UI Entry Point
# RunPod コンテナ用起動スクリプト

echo "[AIBO UI] Starting Next.js server on port ${PORT:-3000}..."
echo "[AIBO UI] NODE_ENV=${NODE_ENV}"
echo "[AIBO UI] HOSTNAME=${HOSTNAME}"

# Next.js standalone サーバー起動
exec node server.js