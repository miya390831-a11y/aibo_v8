#!/usr/bin/env bash
set -euo pipefail
TF="/mnt/c/Users/yuuki/aibo_v7/aibo_bridge/.tokens_tmp.txt"
TOKEN=$(sed -n '1p' "$TF" | tr -d '\r')
CHAT_ID=$(sed -n '2p' "$TF" | tr -d '\r')
echo "L1_LEN=${#TOKEN}"
echo "L2_LEN=${#CHAT_ID}"
BOT=$(curl -fsSL "https://api.telegram.org/bot${TOKEN}/getMe" | jq -r .result.username)
echo "BOT=@${BOT}"
UPD=$(curl -fsSL "https://api.telegram.org/bot${TOKEN}/getUpdates?limit=10")
echo "UPD_COUNT=$(echo "$UPD" | jq '.result|length')"
echo "CHAT_IDS=$(echo "$UPD" | jq -r '.result[].message.chat.id' 2>/dev/null | sort -u | tr '\n' ',' | sed 's/,$//')"
RESP=$(curl -sS -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" -d "chat_id=${CHAT_ID}" -d "text=bootstrap probe")
echo "SEND_OK=$(echo "$RESP" | jq -r .ok)"
echo "SEND_ERR=$(echo "$RESP" | jq -r '.description // empty')"
echo "SEND_CODE=$(echo "$RESP" | jq -r '.error_code // empty')"
WH=$(curl -fsSL "https://api.telegram.org/bot${TOKEN}/getWebhookInfo")
echo "WEBHOOK_URL=$(echo "$WH" | jq -r '.result.url // empty')"
echo "PENDING_UPDATES=$(echo "$WH" | jq -r '.result.pending_update_count // 0')"
