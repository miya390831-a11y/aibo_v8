#!/usr/bin/env bash
###############################################################################
# 🥷 AIBO Remote Command Bridge v4.0 - Bootstrap Script
#
# Usage: curl -fsSL https://raw.githubusercontent.com/miya390831-a11y/aibo_v8/main/aibo_bridge/bootstrap.sh | bash
#   または
#   wget -qO- ... | bash
#   または PO がローカルに保存してから:
#   bash bootstrap.sh
#
# このスクリプトは PO の Cursor ターミナル (Windows/Mac/Linux) から実行され、
# GitHub Codespaces 上に AIBO Studio v8.0 Remote Command Bridge を全自動構築する。
#
# PO 介入: ① Token 取得 (3 分) ② curl 1 発 ③ Telegram 認証リンクタップ
# 合計実作業: 約 5 分 + 待機 60-90 分 (Claude Code が自動実行)
#
# 起票: 2026-05-13
# CTO Kuroudo (Claude Opus 4.7)
###############################################################################

set -euo pipefail

# ========================================
# カラー定義 (ターミナル装飾)
# ========================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()      { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR ]${NC} $*"; }
step()    { echo -e "\n${CYAN}${BOLD}━━━ $* ━━━${NC}\n"; }

# ========================================
# バナー
# ========================================
clear
cat <<'EOF'

   █████╗ ██╗██████╗  ██████╗
  ██╔══██╗██║██╔══██╗██╔═══██╗      🥷 AIBO Cyber Studio v8.0
  ███████║██║██████╔╝██║   ██║         Remote Command Bridge
  ██╔══██║██║██╔══██╗██║   ██║              Bootstrap v4.0
  ██║  ██║██║██████╔╝╚██████╔╝
  ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝       by CTO Kuroudo (Opus 4.7)

  📱 スマホ司令室体制 全自動構築
  ⏱  PO 実作業: 5 分 / 全完成: 60-90 分

EOF

# ========================================
# Step 0: 環境検出
# ========================================
step "Step 0/8: 環境検出"

# OS 判定
OS_TYPE="unknown"
case "$(uname -s)" in
    Linux*)  OS_TYPE="linux" ;;
    Darwin*) OS_TYPE="macos" ;;
    CYGWIN*|MINGW*|MSYS*) OS_TYPE="windows" ;;
esac
info "OS: $OS_TYPE"

# Cursor ターミナル判定 (環境変数で判定)
if [ -n "${CURSOR_TRACE_ID:-}" ] || [ -n "${TERM_PROGRAM:-}" ]; then
    info "ターミナル: ${TERM_PROGRAM:-Cursor推定}"
fi

# 必須コマンド確認
MISSING_TOOLS=()
for cmd in curl jq git; do
    if ! command -v "$cmd" > /dev/null 2>&1; then
        MISSING_TOOLS+=("$cmd")
    fi
done

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    warn "不足ツール: ${MISSING_TOOLS[*]}"
    case "$OS_TYPE" in
        macos)
            info "Homebrew で自動インストールを試みます..."
            for tool in "${MISSING_TOOLS[@]}"; do
                brew install "$tool" || error "$tool インストール失敗"
            done
            ;;
        linux)
            info "apt で自動インストールを試みます..."
            sudo apt-get update -qq
            sudo apt-get install -y "${MISSING_TOOLS[@]}"
            ;;
        windows)
            error "Windows の場合は手動で curl/jq/git をインストールしてください"
            error "推奨: WSL2 内で実行 (wsl --install)"
            exit 1
            ;;
    esac
fi
ok "必須ツール OK"

# ========================================
# Step 1: gh CLI 検出 + 自動インストール
# ========================================
step "Step 1/8: GitHub CLI 検出"

if ! command -v gh > /dev/null 2>&1; then
    warn "gh CLI が未インストール"
    info "自動インストールを試みます..."
    case "$OS_TYPE" in
        macos)
            brew install gh
            ;;
        linux)
            # GitHub 公式 apt リポジトリ
            curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
                | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
            echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
                | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
            sudo apt-get update -qq
            sudo apt-get install -y gh
            ;;
        windows)
            error "Windows: https://cli.github.com/ から手動インストール後、再実行してください"
            exit 1
            ;;
    esac
fi
ok "gh CLI: $(gh --version | head -1)"

# gh 認証確認
if ! gh auth status > /dev/null 2>&1; then
    warn "GitHub 未認証"
    info "ブラウザで GitHub にログインしてください..."
    gh auth login --hostname github.com --git-protocol https --web
fi
GITHUB_USER=$(gh api user --jq '.login')
ok "GitHub 認証: $GITHUB_USER"

# ========================================
# Step 2: AIBO リポ存在確認
# ========================================
step "Step 2/8: AIBO リポジトリ確認"

AIBO_REPO="miya390831-a11y/aibo_v8"

if gh repo view "$AIBO_REPO" > /dev/null 2>&1; then
    ok "リポジトリ存在: $AIBO_REPO"
else
    error "リポジトリ $AIBO_REPO にアクセスできません"
    error "1. リポ名が正しいか確認"
    error "2. gh auth status で認証ユーザー確認"
    exit 1
fi

# ========================================
# Step 3: PO Token 対話入力
# ========================================
step "Step 3/8: Telegram Token 入力"

cat <<EOF

📱 ${BOLD}スマホでこの 2 つを取得してください${NC}:

  ${CYAN}1. Telegram Bot Token${NC}
     ・スマホ Telegram で @BotFather に話しかける
     ・/newbot → Bot 名 "AIBO Studio Bridge" → ユーザー名 (例: aibo_bridge_bot)
     ・表示される Token (例: 1234567890:ABC-DEF...) をコピー

  ${CYAN}2. あなたの Telegram User ID${NC}
     ・スマホ Telegram で @userinfobot に話しかける
     ・表示される ID (数字) をコピー

EOF

# Token 入力 (echo OFF にして秘匿)
read -rsp "📲 Telegram Bot Token を貼り付けて Enter: " TELEGRAM_BOT_TOKEN
echo
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    error "Token が空です"
    exit 1
fi

# Token フォーマット検証
if ! [[ "$TELEGRAM_BOT_TOKEN" =~ ^[0-9]+:[A-Za-z0-9_-]+$ ]]; then
    warn "Token のフォーマットが不正の可能性があります"
    read -rp "続行しますか? (y/n): " yn
    [ "$yn" != "y" ] && exit 1
fi

# Bot 生存確認 (API 叩いて即検証)
info "Telegram Bot API を検証中..."
BOT_INFO=$(curl -fsSL "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>/dev/null || echo '{}')
if echo "$BOT_INFO" | jq -e '.ok == true' > /dev/null 2>&1; then
    BOT_NAME=$(echo "$BOT_INFO" | jq -r '.result.username')
    ok "Telegram Bot: @$BOT_NAME 動作確認 OK"
else
    error "Telegram Bot Token が無効です"
    error "@BotFather で再発行してください"
    exit 1
fi

# User ID 入力
read -rp "🆔 あなたの Telegram User ID (数字のみ): " TELEGRAM_USER_ID
if ! [[ "$TELEGRAM_USER_ID" =~ ^[0-9]+$ ]]; then
    error "User ID は数字のみです"
    exit 1
fi
TELEGRAM_CHAT_ID="$TELEGRAM_USER_ID"

# テストメッセージ送信
info "テストメッセージを Telegram に送信中..."
TEST_RESP=$(curl -fsSL -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=🥷 AIBO Bridge bootstrap 実行中... ($(date +%H:%M))" \
    2>/dev/null || echo '{}')

if echo "$TEST_RESP" | jq -e '.ok == true' > /dev/null 2>&1; then
    ok "Telegram メッセージ送信 OK"
    info "スマホで Telegram を確認してください → 通知が届いていれば成功"
else
    error "Telegram メッセージ送信失敗"
    error "User ID が間違っているか、Bot に話しかけていない可能性"
    error "対処: スマホ Telegram で @$BOT_NAME に何か送信してから再試行"
    exit 1
fi

# ========================================
# Step 4: API キー対話入力 (任意)
# ========================================
step "Step 4/8: API キー入力 (Cline + OpenRouter)"

cat <<EOF

🔑 ${BOLD}Cline で N モデルコンペを実現するための API キー${NC}:

  ${CYAN}OpenRouter API キー${NC} (推奨 · 1 つで Claude/GPT/Gemini/DeepSeek 全部)
  ${CYAN}OpenAI API キー${NC}     (既存・任意)

  ★ Claude Code は Max プラン経由で認証されるため API キー不要 ★
  ★ 全部空 Enter で 後から /set_key コマンドで追加可能 ★

EOF

read -rsp "🔑 OpenRouter API Key (sk-or-...) [Enter でスキップ]: " OPENROUTER_API_KEY
echo
read -rsp "🔑 OpenAI API Key (sk-...) [Enter でスキップ]: " OPENAI_API_KEY
echo

# 検証 (入力がある場合のみ)
if [ -n "$OPENROUTER_API_KEY" ]; then
    info "OpenRouter API キー検証中..."
    OR_CHECK=$(curl -fsSL -H "Authorization: Bearer $OPENROUTER_API_KEY" \
        https://openrouter.ai/api/v1/models 2>/dev/null | jq -r '.data | length' || echo "0")
    if [ "$OR_CHECK" -gt 0 ]; then
        ok "OpenRouter API 動作 OK ($OR_CHECK モデル利用可)"
    else
        warn "OpenRouter API 検証失敗 (キーが無効の可能性)"
        read -rp "続行しますか? (y/n): " yn
        [ "$yn" != "y" ] && exit 1
    fi
fi

# ========================================
# Step 5: Codespace 作成
# ========================================
step "Step 5/8: GitHub Codespace 作成"

# 既存 Codespace 確認
EXISTING_CS=$(gh codespace list --repo "$AIBO_REPO" --json name,state \
    --jq '.[] | select(.state == "Available") | .name' 2>/dev/null | head -1 || echo "")

if [ -n "$EXISTING_CS" ]; then
    warn "既存の Codespace を検出: $EXISTING_CS"
    read -rp "既存を使う (y) / 新規作成 (n): " use_existing
    if [ "$use_existing" = "y" ]; then
        CODESPACE_NAME="$EXISTING_CS"
        info "既存 Codespace 使用: $CODESPACE_NAME"
    else
        info "新規 Codespace 作成中..."
        CODESPACE_NAME=$(gh codespace create \
            --repo "$AIBO_REPO" \
            --machine "standardLinux32gb" \
            --display-name "aibo-bridge-$(date +%Y%m%d-%H%M)" \
            2>&1 | tail -1)
    fi
else
    info "Codespace を新規作成中 (1-2 分かかります)..."
    CODESPACE_NAME=$(gh codespace create \
        --repo "$AIBO_REPO" \
        --machine "standardLinux32gb" \
        --display-name "aibo-bridge-$(date +%Y%m%d-%H%M)" \
        2>&1 | tail -1)
fi

if [ -z "$CODESPACE_NAME" ] || [[ "$CODESPACE_NAME" == *"error"* ]]; then
    error "Codespace 作成失敗"
    error "出力: $CODESPACE_NAME"
    exit 1
fi
ok "Codespace: $CODESPACE_NAME"

# Codespace が利用可能になるまで待機
info "Codespace 起動完了を待機中..."
for i in {1..30}; do
    STATE=$(gh codespace view --codespace "$CODESPACE_NAME" --json state --jq '.state' 2>/dev/null || echo "Unknown")
    case "$STATE" in
        Available)
            ok "Codespace 利用可能"
            break
            ;;
        Provisioning|Starting|Queued)
            printf "."
            sleep 10
            ;;
        *)
            warn "Codespace 状態: $STATE (待機継続)"
            sleep 10
            ;;
    esac
    [ "$i" -eq 30 ] && { error "Codespace 起動タイムアウト"; exit 1; }
done

# ========================================
# Step 6: Codespace に Secrets を送信
# ========================================
step "Step 6/8: Codespace に環境変数を送信"

# 環境変数を Codespace の Secrets として登録
# gh secret は CLI から登録可能
info "GitHub Codespaces user secrets に登録中..."

gh secret set TELEGRAM_BOT_TOKEN --user --app codespaces --body "$TELEGRAM_BOT_TOKEN" --repos "$AIBO_REPO" 2>/dev/null || \
    warn "TELEGRAM_BOT_TOKEN 登録失敗 (権限不足の可能性)"

gh secret set TELEGRAM_USER_ID --user --app codespaces --body "$TELEGRAM_USER_ID" --repos "$AIBO_REPO" 2>/dev/null || true
gh secret set TELEGRAM_CHAT_ID --user --app codespaces --body "$TELEGRAM_CHAT_ID" --repos "$AIBO_REPO" 2>/dev/null || true

[ -n "$OPENROUTER_API_KEY" ] && \
    gh secret set OPENROUTER_API_KEY --user --app codespaces --body "$OPENROUTER_API_KEY" --repos "$AIBO_REPO" 2>/dev/null || true
[ -n "$OPENAI_API_KEY" ] && \
    gh secret set OPENAI_API_KEY --user --app codespaces --body "$OPENAI_API_KEY" --repos "$AIBO_REPO" 2>/dev/null || true

# Codespace 再起動 (Secrets を反映)
info "Codespace を再起動して Secrets を反映..."
gh codespace stop --codespace "$CODESPACE_NAME" 2>/dev/null || true
sleep 5
gh codespace ssh --codespace "$CODESPACE_NAME" -- "echo started" > /dev/null 2>&1 || \
    sleep 30  # 起動再待機

ok "Secrets 登録完了"

# ========================================
# Step 7: Codespace 内で全自動セットアップ実行
# ========================================
step "Step 7/8: Codespace 内で Claude Code 自動セットアップ起動"

# v4 指示書を取得 (リポから or 同梱)
INSTRUCTION_PATH="aibo_bridge/cursor_instruction_bridge_v4_codespaces_auto.md"

# Codespace 内に転送 + 実行
info "Claude Code に v4 指示書を投下中..."

# ヒアドキュメントで Codespace 内のセットアップスクリプトを実行
gh codespace ssh --codespace "$CODESPACE_NAME" -- bash <<'REMOTE_SCRIPT'
set -euo pipefail

echo "🥷 Codespace 内セットアップ開始"

# 必須パッケージ
sudo apt-get update -qq
sudo apt-get install -y -qq tmux jq python3-pip python3-venv ripgrep inotify-tools

# Node.js 確認 (Codespaces 標準で v20)
node --version

# Claude Code インストール (Codespaces は Linux x64 なので公式手順そのまま)
if ! command -v claude > /dev/null 2>&1; then
    npm install -g @anthropic-ai/claude-code
fi

# Cline インストール (Linux x64 で動く)
if ! command -v cline > /dev/null 2>&1; then
    npm install -g cline 2>/dev/null || npm install -g @cline/cli
fi

# 作業ディレクトリ
WORK="/workspaces/aibo_v8"
BRIDGE="${WORK}/aibo_bridge"
mkdir -p "$BRIDGE"/{bin,bot,config,logs,inbox,outbox/images,scripts}

# .env を Secrets から組み立て
cat > "$BRIDGE/config/.env" <<ENVEOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_USER_ID=${TELEGRAM_USER_ID:-}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}
TELEGRAM_ALLOWED_USER_ID=${TELEGRAM_USER_ID:-}
OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}
OPENAI_API_KEY=${OPENAI_API_KEY:-}
AIBO_REPO_PATH=${WORK}
AIBO_INSTRUCTION_DIR=${WORK}/cursor_instructions
AIBO_BRIDGE_ROOT=${BRIDGE}
CLAUDE_TMUX_SESSION=aibo-claude
CLINE_TMUX_SESSION=aibo-cline
BOT_TMUX_SESSION=aibo-bot
IMAGE_WATCH_DIR=${BRIDGE}/outbox/images
LOG_DIR=${BRIDGE}/logs
ENVEOF
chmod 600 "$BRIDGE/config/.env"

echo "✅ Codespace 内 ベース準備完了"
echo "次のステップ: Claude Code が v4 指示書を実行します"

REMOTE_SCRIPT

ok "Codespace ベース準備完了"

# v4 指示書を Codespace に転送して Claude Code 全自動実行
info "Claude Code に v4 指示書を完全自動モードで投下..."

gh codespace cp \
    "$(dirname "$0")/cursor_instruction_bridge_v4_codespaces_auto.md" \
    "remote:/workspaces/aibo_v8/aibo_bridge/" \
    --codespace "$CODESPACE_NAME" 2>/dev/null || warn "指示書転送スキップ (リポに含まれている前提)"

# Claude Code をヘッドレスモードで起動 (完全自動)
gh codespace ssh --codespace "$CODESPACE_NAME" -- bash <<'AUTO_SCRIPT'
set -euo pipefail
cd /workspaces/aibo_v8/aibo_bridge

# 既に v4 指示書が手元にある前提
INSTRUCTION="cursor_instruction_bridge_v4_codespaces_auto.md"

# tmux セッションで非同期実行 (bootstrap の SSH が切れても継続)
tmux new-session -d -s aibo-setup \
    "claude -p \"\$(cat $INSTRUCTION)\" \
        --dangerously-skip-permissions \
        --output-format stream-json \
        --verbose \
        --max-turns 50 \
        > /workspaces/aibo_v8/aibo_bridge/logs/setup.log 2>&1
     
     # 完了通知
     curl -s -X POST \"https://api.telegram.org/bot\${TELEGRAM_BOT_TOKEN}/sendMessage\" \
         -d \"chat_id=\${TELEGRAM_CHAT_ID}\" \
         -d \"text=🎉 セットアップ完了!\n/help でコマンド一覧確認\""

echo "✅ Claude Code バックグラウンド実行開始"
echo "tmux セッション: aibo-setup"
echo "進捗ログ: /workspaces/aibo_v8/aibo_bridge/logs/setup.log"
AUTO_SCRIPT

ok "Claude Code 自動実行開始 (バックグラウンド)"

# ========================================
# Step 8: 完了報告 + PO への次のアクション
# ========================================
step "Step 8/8: Bootstrap 完了"

# Telegram に完了通知
curl -fsSL -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "parse_mode=Markdown" \
    -d "text=🥷 *Bootstrap 完了*

Codespace: \`${CODESPACE_NAME}\`
GitHub User: @${GITHUB_USER}

⏳ Claude Code が裏で自動セットアップ中...
60-90 分で完成通知が来ます

PO はこの間:
  🌸 サウナでも カフェでも OK
  📱 スマホ Telegram を待機するだけ

完成後、/help でコマンド一覧が見られます" > /dev/null

cat <<EOF

${GREEN}${BOLD}╔══════════════════════════════════════════════════════════╗${NC}
${GREEN}${BOLD}║          🎉 Bootstrap 完了 · Claude Code 起動中 🎉        ║${NC}
${GREEN}${BOLD}╚══════════════════════════════════════════════════════════╝${NC}

  ${CYAN}Codespace${NC}:     ${CODESPACE_NAME}
  ${CYAN}GitHub User${NC}:   @${GITHUB_USER}
  ${CYAN}Bot${NC}:           @${BOT_NAME}
  ${CYAN}Telegram${NC}:      User ID ${TELEGRAM_USER_ID}

  ${YELLOW}🤖 Claude Code がバックグラウンドで自動セットアップ実行中${NC}
  ${YELLOW}   想定時間: 60-90 分${NC}

  ${MAGENTA}📱 PO の次のアクション${NC}:
    1. このターミナルは閉じて OK
    2. スマホ Telegram を Pin 留め
    3. サウナ・カフェ・散歩で完成通知を待つ
    4. 通知が来たら /help で使い方確認

  ${BLUE}🔍 進捗確認 (任意)${NC}:
    gh codespace ssh -c ${CODESPACE_NAME} -- tail -f /workspaces/aibo_v8/aibo_bridge/logs/setup.log

  ${RED}⚠️ 緊急停止${NC}:
    gh codespace stop -c ${CODESPACE_NAME}

EOF

ok "All done. Codespace 上で Claude Code が走っています."
ok "サウナ行ってこい 🌸♨️☕"
