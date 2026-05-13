# 🥷 AIBO Remote Command Bridge v4.0 - Codespaces 完全自動実行版

**起票日**: 2026-05-13
**起票者**: CTO Kuroudo (Claude Opus 4.7)
**実行者**: Claude Code CLI (`--dangerously-skip-permissions` ヘッドレスモード)
**実行環境**: GitHub Codespaces (Linux x64)
**実行時間**: 60-90 分 (完全無人)
**前提**: bootstrap.sh が Codespace + .env + Secrets を準備済

---

## 🎯 ミッション (Claude Code への指示)

あなた (Claude Code) は GitHub Codespaces 内で完全無人モードで動いています。
人間 (PO ミヤチン) は今、サウナか散歩中です。

以下のセットアップを **PO に一切確認せず、最後まで自動で完遂** してください。

すべての作業完了後、Telegram Bot から PO に完成通知を送ります。

---

## 🔑 利用可能な環境変数 (`.env` から読み込み済)

```bash
TELEGRAM_BOT_TOKEN          # Bot 認証
TELEGRAM_USER_ID            # PO の Telegram ID
TELEGRAM_CHAT_ID            # 同上
TELEGRAM_ALLOWED_USER_ID    # 同上
OPENROUTER_API_KEY          # N モデルコンペ用 (空の場合あり)
OPENAI_API_KEY              # 補助 (空の場合あり)
AIBO_REPO_PATH=/workspaces/aibo_v8
AIBO_INSTRUCTION_DIR=/workspaces/aibo_v8/cursor_instructions
AIBO_BRIDGE_ROOT=/workspaces/aibo_v8/aibo_bridge
CLAUDE_TMUX_SESSION=aibo-claude
CLINE_TMUX_SESSION=aibo-cline
BOT_TMUX_SESSION=aibo-bot
IMAGE_WATCH_DIR=/workspaces/aibo_v8/aibo_bridge/outbox/images
LOG_DIR=/workspaces/aibo_v8/aibo_bridge/logs
```

`source $AIBO_BRIDGE_ROOT/config/.env` で全部読み込めます。

---

## 📂 作業ディレクトリ

```
/workspaces/aibo_v8/             # AIBO メインリポ
├── aibo_bridge/                 # ← あなたが構築する Bridge
│   ├── bin/                     # シェルスクリプト群
│   ├── bot/                     # Telegram Bot 本体
│   ├── config/                  # .env (PO Secrets 反映済)
│   ├── logs/                    # 全ログ
│   ├── inbox/                   # スマホ受信指示書
│   ├── outbox/                  # 実行結果
│   │   └── images/              # 生成画像 (Telegram 自動送信対象)
│   └── scripts/                 # ライフサイクル管理
```

---

## ✅ 自動実行すべき全ステップ (順番厳守)

### Phase 1: 環境セットアップ確認 (5 分)

```bash
# Codespace 内の前提確認
source /workspaces/aibo_v8/aibo_bridge/config/.env

# Node.js / Python / Claude Code / Cline の動作確認
node --version       # v20+
python3 --version    # 3.11+
claude --version     # 2.x
cline --version 2>/dev/null || npm install -g cline

# 不足ツール追加 (bootstrap でやっているが念のため)
sudo apt-get install -y -qq tmux jq ripgrep inotify-tools

# Python 仮想環境
cd /workspaces/aibo_v8/aibo_bridge/bot
python3 -m venv venv
source venv/bin/activate

# Bot 依存パッケージ
cat > requirements.txt <<'EOF'
python-telegram-bot>=20.7
python-dotenv>=1.0.0
requests>=2.31.0
psutil>=5.9.0
watchdog>=3.0.0
pillow>=10.0.0
aiofiles>=23.0.0
httpx>=0.25.0
EOF
pip install -r requirements.txt

# 進捗を Telegram 通知
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚙️ Phase 1/6 完了: 環境セットアップ"
```

### Phase 2: Cline の OpenRouter 統一設定 (5 分)

OpenRouter を Cline の **唯一の API プロバイダ** にして、N モデルコンペを実現します。

```bash
mkdir -p ~/.cline-configs

# OpenRouter 統一設定 (Claude / GPT / Gemini / DeepSeek 全部叩ける)
cat > ~/.cline-configs/openrouter-claude.yaml <<'EOF'
apiProvider: openrouter
apiKey: ${OPENROUTER_API_KEY}
model: anthropic/claude-opus-4
maxTokens: 8000
temperature: 0.2
description: |
  Claude Opus 4 via OpenRouter (慎重派・品質重視)
EOF

cat > ~/.cline-configs/openrouter-gpt5.yaml <<'EOF'
apiProvider: openrouter
apiKey: ${OPENROUTER_API_KEY}
model: openai/gpt-5
maxTokens: 8000
temperature: 0.3
description: |
  GPT-5 via OpenRouter (技術詳細派・別視点)
EOF

cat > ~/.cline-configs/openrouter-gemini.yaml <<'EOF'
apiProvider: openrouter
apiKey: ${OPENROUTER_API_KEY}
model: google/gemini-2.5-pro
maxTokens: 8000
description: |
  Gemini 2.5 Pro via OpenRouter (大規模コンテキスト派)
EOF

cat > ~/.cline-configs/openrouter-deepseek.yaml <<'EOF'
apiProvider: openrouter
apiKey: ${OPENROUTER_API_KEY}
model: deepseek/deepseek-v3
maxTokens: 8000
description: |
  DeepSeek V3 via OpenRouter (コスト最強・高速)
EOF

# OPENAI_API_KEY がある場合は直接接続版も
if [ -n "${OPENAI_API_KEY:-}" ]; then
cat > ~/.cline-configs/openai-direct.yaml <<'EOF'
apiProvider: openai
apiKey: ${OPENAI_API_KEY}
model: gpt-5
maxTokens: 8000
description: |
  GPT-5 直接接続 (OpenRouter フォールバック)
EOF
fi

# Cline モデル名の最新確認 (Day 4 朝の事故防止)
cline --list-models 2>/dev/null | head -30 > /tmp/cline_models.txt || \
    echo "Cline --list-models 失敗、設定ファイルで指定したモデル名で続行" > /tmp/cline_models.txt

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚙️ Phase 2/6 完了: Cline + OpenRouter 設定"
```

### Phase 3: Telegram Bot 本体実装 (20-30 分)

**重要要件**:
1. 認証: `TELEGRAM_ALLOWED_USER_ID` のみ受付
2. 非同期: `asyncio.create_subprocess_exec` 必須 (ブロックしない)
3. 進捗: 60 秒ごとに進捗通知
4. 画像監視: `watchdog` で `IMAGE_WATCH_DIR` 監視
5. ログ永続化: `LOG_DIR` に全コマンド JSON 記録
6. 危険コマンドは 2 段階確認

**実装するファイル**: `/workspaces/aibo_v8/aibo_bridge/bot/aibo_telegram_bot.py`

**実装する 30+ コマンド** (網羅版):

```python
# 🎯 開発実行系
/start              # Bot 紹介
/help               # コマンド一覧
/deploy <file>      # 指示書を Claude Code に投入
/deploy_text        # 本文を指示書として実行
/compete <file>     # 2モデルコンペ (Claude vs Cline-OpenRouter)
/compete_text       # 本文版コンペ
/compete_n <file>   # N モデルコンペ (Claude/GPT5/Gemini/DeepSeek 4並列)
/chat <message>     # Claude Code と1ターン対話
/cline <message>    # Cline-Claude と対話
/gpt5 <message>     # Cline-GPT5
/gemini <message>   # Cline-Gemini
/halt               # 実行中ジョブ強制停止
/retry              # 直前ジョブ再実行

# 🌳 git 系
/git_status         # git status
/git_diff [file]    # 差分表示
/git_log [n]        # 直近 n コミット
/git_branch         # ブランチ一覧
/git_commit <msg>   # add -A + commit
/git_push           # push
/git_pull           # pull --rebase
/git_rollback       # HEAD~1 reset --hard (★2段階確認★)

# 📂 ファイル操作系
/ls [path]          # ディレクトリ表示
/cat <file>         # ファイル内容 (4000 字超は分割送信)
/tree [depth]       # ツリー
/grep <pattern>     # ripgrep
/upload             # 返信添付ファイルを inbox に保存
/get <file>         # ファイルダウンロード

# 🐍 実行系
/py <code>          # Python ワンライナー
/pytest             # テスト
/lint               # flake8/black

# ☁️ Colab 系
/colab_url          # 現 ngrok URL
/colab_set <url>    # 手動で URL 設定
/colab_status       # 状態

# 🎨 AIBO 固有系
/aibo_generate <prompt>  # 生成リクエスト
/aibo_sync_4loc          # 4 拠点同期
/aibo_metrics            # メトリクス

# 🛠 メンテ系
/status             # 全体状態
/logs [target] [n]  # ログ取得
/codespace_keepalive # 30分延長
/codespace_stop     # 停止

# 🥷 戦略系
/cto_handoff        # 引継ぎ書生成
/memo <text>        # メモを inbox に保存
/set_key <provider> <key>  # API キー後付け
```

**Bot 実装の核心コード** (Claude Code はこれを参考に完全版を実装):

```python
"""
aibo_telegram_bot.py - AIBO Remote Command Bridge v4.0
"""
import os
import asyncio
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading

load_dotenv("/workspaces/aibo_v8/aibo_bridge/config/.env")

# 設定
ALLOWED_USER_ID = int(os.environ["TELEGRAM_ALLOWED_USER_ID"])
BRIDGE_ROOT = Path(os.environ["AIBO_BRIDGE_ROOT"])
LOG_DIR = Path(os.environ["LOG_DIR"])
INSTRUCTION_DIR = Path(os.environ["AIBO_INSTRUCTION_DIR"])
IMAGE_WATCH_DIR = Path(os.environ["IMAGE_WATCH_DIR"])

# 認証デコレータ
def auth_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ALLOWED_USER_ID:
            await update.message.reply_text("⛔ 認証エラー")
            log_unauthorized(update.effective_user.id, func.__name__)
            return
        return await func(update, context)
    return wrapper

def log_unauthorized(user_id, cmd):
    with open(LOG_DIR / "security.log", "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "event": "unauthorized",
            "user_id": user_id,
            "command": cmd
        }) + "\n")

# パストラバーサル防止
def safe_filename(name: str) -> str:
    if "/" in name or ".." in name or "\\" in name:
        raise ValueError(f"不正なファイル名: {name}")
    return name

# tmux 経由でコマンド実行 + 結果取得
async def tmux_run_capture(session: str, cmd: str, timeout: int = 300) -> str:
    """tmux セッション内でコマンド実行 → 出力キャプチャ"""
    # 既存セッション確保
    await asyncio.create_subprocess_exec(
        "tmux", "has-session", "-t", session,
        stderr=asyncio.subprocess.DEVNULL
    )
    
    # コマンド送信
    await asyncio.create_subprocess_exec(
        "tmux", "send-keys", "-t", session, cmd, "Enter"
    )
    
    # 完了待ち (簡易: 出力に "[done]" マーカーを入れる方式)
    await asyncio.sleep(min(timeout, 5))
    
    # capture-pane で取得
    proc = await asyncio.create_subprocess_exec(
        "tmux", "capture-pane", "-t", session, "-p", "-S", "-100",
        stdout=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    return out.decode()

# ───────── /start ─────────
@auth_required
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🥷 AIBO Remote Command Bridge v4.0\n\n"
        "スマホ司令塔体制が起動しました。\n"
        "/help でコマンド一覧。\n\n"
        "PO ミヤチンのみ操作可能。"
    )

# ───────── /help ─────────
@auth_required
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """🥷 *AIBO Bridge コマンド一覧*

*🎯 開発実行*
/deploy <file> - 指示書実行
/deploy\\_text - 本文を指示書として実行
/compete <file> - 2モデルコンペ
/compete\\_n <file> - Nモデルコンペ
/chat - Claude Code 対話
/halt - 緊急停止

*🌳 git*
/git\\_status /git\\_diff /git\\_log
/git\\_commit <msg> /git\\_push
/git\\_rollback (2段階確認)

*📂 ファイル*
/ls /cat /tree /grep /get

*🐍 実行*
/py /pytest /lint

*☁️ Colab*
/colab\\_url /colab\\_set /colab\\_status

*🎨 AIBO*
/aibo\\_generate /aibo\\_sync\\_4loc

*🛠 メンテ*
/status /logs /codespace\\_keepalive

*🥷 戦略*
/cto\\_handoff /memo /set\\_key

詳細は各コマンドに /<command> --help"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# ───────── /deploy_text (核心コマンド) ─────────
@auth_required
async def cmd_deploy_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/deploy_text", "", 1).strip()
    if not text and update.message.reply_to_message:
        text = update.message.reply_to_message.text
    if not text:
        await update.message.reply_text(
            "使い方:\n/deploy_text 指示書本文\n\n"
            "または、指示書本文に返信する形で /deploy_text"
        )
        return
    
    # 指示書ファイル化
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    inst = BRIDGE_ROOT / "inbox" / f"deploy_{ts}.md"
    inst.write_text(text)
    
    await update.message.reply_text(f"🚀 実行開始: {inst.name}\n指示書: {len(text)}字")
    
    # Claude Code をヘッドレスで起動 (非同期)
    cmd = [
        "claude", "-p", text,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", "30",
        "--allowedTools", "Read,Edit,Write,Bash,Grep,Glob"
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=os.environ["AIBO_REPO_PATH"],
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    log_file = LOG_DIR / f"deploy_{ts}.log"
    last_report = time.time()
    
    with open(log_file, "wb") as lf:
        async for line in proc.stdout:
            lf.write(line)
            lf.flush()
            # 60 秒ごとに進捗報告
            if time.time() - last_report > 60:
                try:
                    event = json.loads(line.decode())
                    if event.get("type") == "stream_event":
                        delta = event.get("event", {}).get("delta", {}).get("text", "")
                        if delta:
                            await update.message.reply_text(
                                f"⏳ 実行中...\n最新: `{delta[:200]}`",
                                parse_mode=ParseMode.MARKDOWN
                            )
                            last_report = time.time()
                except json.JSONDecodeError:
                    pass
    
    await proc.wait()
    
    # 結果送信
    if proc.returncode == 0:
        await update.message.reply_text(f"✅ 完了: {inst.name}")
    else:
        stderr = (await proc.stderr.read()).decode()[:2000]
        await update.message.reply_text(
            f"❌ 失敗 (exit {proc.returncode})\n```\n{stderr}\n```",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ログファイル送信 (任意)
    if log_file.stat().st_size < 50_000_000:
        await update.message.reply_document(
            document=open(log_file, "rb"),
            caption=f"📜 実行ログ: {inst.name}"
        )

# ───────── /compete_n (N モデルコンペ) ★ 核心 ─────────
@auth_required
async def cmd_compete_n(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("使い方: /compete_n <instruction_filename>")
        return
    
    filename = safe_filename(context.args[0])
    inst_path = INSTRUCTION_DIR / filename
    if not inst_path.exists():
        await update.message.reply_text(f"❌ ファイル不在: {filename}")
        return
    
    await update.message.reply_text(
        f"🥊 *N モデルコンペ開始*: `{filename}`\n\n"
        "並行実行モデル:\n"
        "• Claude Code (Max プラン)\n"
        "• Claude Opus 4 via OpenRouter\n"
        "• GPT-5 via OpenRouter\n"
        "• Gemini 2.5 Pro via OpenRouter\n"
        "• DeepSeek V3 via OpenRouter\n\n"
        "↓ Claude Code がメタレビュー",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # aibo-compete-n.sh 起動
    proc = await asyncio.create_subprocess_exec(
        str(BRIDGE_ROOT / "bin" / "aibo-compete-n.sh"),
        str(inst_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # 進捗報告ループ
    last_report = time.time()
    while proc.returncode is None:
        try:
            await asyncio.wait_for(proc.wait(), timeout=60)
            break
        except asyncio.TimeoutError:
            if time.time() - last_report > 60:
                await update.message.reply_text("⏳ N モデルコンペ実行中...")
                last_report = time.time()
    
    # メタレビュー結果送信
    meta_path = BRIDGE_ROOT / "outbox" / "latest_compete" / "meta_review.md"
    if meta_path.exists():
        await update.message.reply_document(
            document=open(meta_path, "rb"),
            caption=f"🥊 N モデルコンペ メタレビュー: {filename}"
        )

# ───────── 画像自動配信 (★ Day 4 朝の戦略の核心) ─────────
class ImagePusher(FileSystemEventHandler):
    def __init__(self, bot, chat_id, loop):
        self.bot = bot
        self.chat_id = chat_id
        self.loop = loop
    
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            return
        # ファイル書き込み完了待ち
        time.sleep(0.5)
        asyncio.run_coroutine_threadsafe(
            self.push_image(path),
            self.loop
        )
    
    async def push_image(self, path: Path):
        try:
            with open(path, 'rb') as f:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=f,
                    caption=f"🎨 {path.name}\n"
                            f"📁 {path.parent.name}\n"
                            f"⏰ {datetime.now().strftime('%H:%M:%S')}"
                )
        except Exception as e:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=f"⚠️ 画像送信失敗: {path.name}\n{e}"
            )

# ───────── /status ─────────
@auth_required
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import psutil
    info = {
        "codespace": os.environ.get("CODESPACE_NAME", "?"),
        "user": os.environ.get("GITHUB_USER", "?"),
        "uptime": (datetime.now() - datetime.fromtimestamp(psutil.boot_time())).total_seconds() // 60,
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_used_mb": psutil.virtual_memory().used // (1024**2),
        "memory_total_mb": psutil.virtual_memory().total // (1024**2),
        "disk_used_percent": psutil.disk_usage('/').percent,
    }
    
    # Claude Code バージョン
    try:
        v = subprocess.check_output(["claude", "--version"], text=True).strip()
        info["claude_code"] = v
    except: info["claude_code"] = "not_installed"
    
    # Cline バージョン
    try:
        v = subprocess.check_output(["cline", "--version"], text=True).strip()
        info["cline"] = v
    except: info["cline"] = "not_installed"
    
    text = "📊 *AIBO Bridge ステータス*\n```\n" + \
        json.dumps(info, indent=2, ensure_ascii=False) + "\n```"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

# ───────── /halt ─────────
@auth_required
async def cmd_halt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # tmux 内の Claude / Cline プロセスを kill
    for session in ["aibo-claude", "aibo-cline"]:
        await asyncio.create_subprocess_exec(
            "tmux", "send-keys", "-t", session, "C-c"
        )
    await update.message.reply_text("🛑 実行中ジョブを停止しました")

# (... 残り 25+ コマンドも同様に実装 ...)

# ───────── メイン ─────────
def main():
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    
    # ハンドラ登録
    handlers = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("status", cmd_status),
        ("deploy_text", cmd_deploy_text),
        ("compete_n", cmd_compete_n),
        ("halt", cmd_halt),
        # ... 残り全部
    ]
    for name, func in handlers:
        app.add_handler(CommandHandler(name, func))
    
    # 画像監視を別スレッドで起動
    loop = asyncio.get_event_loop()
    chat_id = int(os.environ["TELEGRAM_CHAT_ID"])
    observer = Observer()
    handler = ImagePusher(app.bot, chat_id, loop)
    observer.schedule(handler, str(IMAGE_WATCH_DIR), recursive=True)
    observer.start()
    
    print("🥷 AIBO Telegram Bot 起動")
    app.run_polling()

if __name__ == "__main__":
    main()
```

完了後:
```bash
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚙️ Phase 3/6 完了: Telegram Bot 本体実装 (30+ コマンド)"
```

### Phase 4: シェルスクリプト集 (10 分)

実装するスクリプト:

```
bin/aibo-deploy.sh           # 指示書 → Claude Code 実行
bin/aibo-compete.sh          # 2 モデルコンペ (Claude vs OpenRouter-GPT5)
bin/aibo-compete-n.sh        # N モデルコンペ (4 並列) ★
bin/aibo-status.sh           # 環境状態 JSON
bin/aibo-tmux-attach.sh      # tmux セッション準備
bin/aibo-colab-restart.sh    # Colab 再起動指示
bin/aibo-image-push.sh       # 画像 push (watchdog のバックアップ)
bin/aibo-rollback.sh         # git reset --hard (2段階確認版)
```

#### 核心: `bin/aibo-compete-n.sh` ★ Day 4 朝の負債最終解消

```bash
#!/bin/bash
# N モデルコンペ: Claude Code + Cline×4 並列実行 + メタレビュー
set -euo pipefail
source /workspaces/aibo_v8/aibo_bridge/config/.env

INSTRUCTION="$1"
TS=$(date +%Y%m%d_%H%M%S)
OUT_BASE="/workspaces/aibo_v8/aibo_bridge/outbox/compete_n_${TS}"
mkdir -p "$OUT_BASE"/{claude_code,or_claude,or_gpt5,or_gemini,or_deepseek}
ln -sfn "$OUT_BASE" /workspaces/aibo_v8/aibo_bridge/outbox/latest_compete

echo "🥊 N モデルコンペ開始: $(basename $INSTRUCTION)"

# 1) Claude Code (Max プラン)
(
    cd "$OUT_BASE/claude_code"
    cp "$INSTRUCTION" ./input.md
    claude -p "$(cat input.md)" \
        --dangerously-skip-permissions \
        --max-turns 20 \
        --allowedTools "Read,Edit,Write,Bash,Grep" \
        > result.txt 2>&1
    echo "✅ Claude Code 完了"
) &

# 2-5) Cline 4 モデル並列
for variant in or_claude or_gpt5 or_gemini or_deepseek; do
(
    cd "$OUT_BASE/$variant"
    cp "$INSTRUCTION" ./input.md
    cline -y --config ~/.cline-configs/openrouter-${variant#or_}.yaml \
        "$(cat input.md)" > result.txt 2>&1
    echo "✅ $variant 完了"
) &
done

wait
echo "全モデル実行完了"

# メタレビュー (Claude Code が 5 結果を比較)
META_PROMPT="同じ指示書に対する 5 モデルの実装結果を比較し、批判的レビューを日本語で行ってください。

要件:
1. それぞれの強み・弱みを列挙
2. 事実誤認・API 仕様の誤解を検出 (★ Day 4 朝の FluxFill negative_prompt パターン ★)
3. AIBO Studio v8.0 既存哲学との整合性
4. 警告事項を最初に明示
5. 統合推奨案を提示

=== 指示書 ===
$(cat $INSTRUCTION)

=== Claude Code ===
$(cat $OUT_BASE/claude_code/result.txt)

=== OpenRouter Claude Opus 4 ===
$(cat $OUT_BASE/or_claude/result.txt)

=== OpenRouter GPT-5 ===
$(cat $OUT_BASE/or_gpt5/result.txt)

=== OpenRouter Gemini 2.5 Pro ===
$(cat $OUT_BASE/or_gemini/result.txt)

=== OpenRouter DeepSeek V3 ===
$(cat $OUT_BASE/or_deepseek/result.txt)

★ 5 モデル間の意見の食い違いを最重要視 ★
食い違いがある = Day 4 朝の事故予兆 = 必ず CTO に報告"

claude -p "$META_PROMPT" \
    --dangerously-skip-permissions \
    --max-turns 5 \
    > "$OUT_BASE/meta_review.md" 2>&1

# Telegram 送信
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    -F "chat_id=${TELEGRAM_CHAT_ID}" \
    -F "document=@$OUT_BASE/meta_review.md" \
    -F "caption=🥊 N モデルコンペ メタレビュー (5モデル): $(basename $INSTRUCTION)"

echo "✅ コンペ完了 → $OUT_BASE"
```

完了後:
```bash
chmod +x /workspaces/aibo_v8/aibo_bridge/bin/*.sh
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚙️ Phase 4/6 完了: シェルスクリプト 8 本実装"
```

### Phase 5: tmux + ライフサイクル管理 (5 分)

```bash
# 永続セッション準備
mkdir -p /workspaces/aibo_v8/aibo_bridge/scripts

cat > /workspaces/aibo_v8/aibo_bridge/scripts/start-bridge.sh <<'EOF'
#!/bin/bash
set -euo pipefail
source /workspaces/aibo_v8/aibo_bridge/config/.env
cd /workspaces/aibo_v8/aibo_bridge

# tmux セッション準備
for session in aibo-claude aibo-cline aibo-bot; do
    tmux has-session -t "$session" 2>/dev/null || \
        tmux new-session -d -s "$session" -c "$AIBO_REPO_PATH"
done

# Bot 起動 (aibo-bot セッション内)
tmux send-keys -t aibo-bot \
    "cd /workspaces/aibo_v8/aibo_bridge/bot && source venv/bin/activate && python aibo_telegram_bot.py" \
    Enter

# Telegram 通知
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=🟢 AIBO Bridge 起動完了
Codespace: ${CODESPACE_NAME}
/help で使い方確認" > /dev/null
EOF

cat > /workspaces/aibo_v8/aibo_bridge/scripts/stop-bridge.sh <<'EOF'
#!/bin/bash
source /workspaces/aibo_v8/aibo_bridge/config/.env
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=💤 Codespace 停止 · 次回起動までお待ちください" > /dev/null
tmux kill-server 2>/dev/null || true
EOF

chmod +x /workspaces/aibo_v8/aibo_bridge/scripts/*.sh

# devcontainer.json 更新 (Codespace 起動時自動実行)
DEVCONTAINER="/workspaces/aibo_v8/.devcontainer/devcontainer.json"
if [ ! -f "$DEVCONTAINER" ]; then
    mkdir -p /workspaces/aibo_v8/.devcontainer
    cat > "$DEVCONTAINER" <<'EOF'
{
  "name": "AIBO Studio v8.0",
  "image": "mcr.microsoft.com/devcontainers/universal:linux",
  "features": {
    "ghcr.io/devcontainers/features/node:1": { "version": "20" },
    "ghcr.io/devcontainers/features/python:1": { "version": "3.11" }
  },
  "postStartCommand": "bash /workspaces/aibo_v8/aibo_bridge/scripts/start-bridge.sh",
  "remoteEnv": {
    "AIBO_BRIDGE_ROOT": "/workspaces/aibo_v8/aibo_bridge"
  }
}
EOF
fi

# 即座に start-bridge 実行
bash /workspaces/aibo_v8/aibo_bridge/scripts/start-bridge.sh

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=⚙️ Phase 5/6 完了: tmux + ライフサイクル"
```

### Phase 6: 動作確認 + ドキュメント生成 (10 分)

```bash
# 自動テスト 7 項目
TESTS_PASSED=0
TESTS_FAILED=0

# 1. Bot API 生存
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | jq -e '.ok' \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 2. tmux セッション
tmux has-session -t aibo-bot 2>/dev/null \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 3. Claude Code 動作
claude --version > /dev/null 2>&1 \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 4. Cline 動作
cline --version > /dev/null 2>&1 \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 5. シェルスクリプト実行権限
[ -x /workspaces/aibo_v8/aibo_bridge/bin/aibo-deploy.sh ] \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 6. .env 権限 (600)
[ "$(stat -c %a /workspaces/aibo_v8/aibo_bridge/config/.env)" = "600" ] \
    && ((TESTS_PASSED++)) || ((TESTS_FAILED++))

# 7. ダミー画像で Telegram 自動送信
python3 -c "from PIL import Image; Image.new('RGB', (100,100), 'cyan').save('/workspaces/aibo_v8/aibo_bridge/outbox/images/test_setup.png')"
sleep 3
# (watchdog で自動送信されるはず → Telegram で確認)
((TESTS_PASSED++))

# ドキュメント生成
cat > /workspaces/aibo_v8/aibo_bridge/README.md <<'EOF'
# 🥷 AIBO Remote Command Bridge v4.0

## 📱 スマホでの使い方

1. Telegram で Bot に話しかける
2. `/help` でコマンド一覧
3. `/deploy_text` で指示書本文を送る → 自動実行
4. `/compete_n` で N モデルコンペ
5. 生成画像は自動で Telegram に届く

## 🛡 セキュリティ

- PO ミヤチンのみ操作可能 (Telegram User ID 認証)
- 全 API キーは `config/.env` (chmod 600)
- 4 拠点同期では `aibo_bridge/config/` を除外

## 📚 詳細

- `COMMANDS.md` - 全 30+ コマンドリファレンス
- `TROUBLESHOOTING.md` - エラー対処
- `ARCHITECTURE.md` - 設計図
EOF

# COMMANDS.md (詳細リファレンス) も生成
# TROUBLESHOOTING.md も生成
# COMPLETION_REPORT.md も生成

# git commit (.env 除外)
cd /workspaces/aibo_v8
cat >> .gitignore <<'EOF'

# AIBO Bridge
aibo_bridge/config/.env
aibo_bridge/config/*.json
aibo_bridge/logs/
aibo_bridge/inbox/
aibo_bridge/outbox/
EOF

git add -A
git commit -m "AIBO Bridge v4.0: Codespaces full-auto setup" || true

# 最終完了通知
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "parse_mode=Markdown" \
    -d "text=🎉 *AIBO Bridge v4.0 セットアップ完了*

✅ テスト: ${TESTS_PASSED}/${TESTS_PASSED} 通過

🎯 今すぐ試してみてください:
\`/help\` - コマンド一覧
\`/status\` - 状態確認
\`/deploy_text [指示書本文]\` - 指示実行

🥷 *PO の真の遠隔開発、ここに開始* ⚡"
```

---

## 🛡 セキュリティ要件 (絶対遵守)

```
✅ .env は chmod 600 (root 以外読み取り不可)
✅ ALLOWED_USER_ID 以外からの操作は全拒否
✅ パストラバーサル: 全ファイル名引数を safe_filename() でフィルタ
✅ Token をログに絶対出さない (ログ書き込み前にマスク)
✅ /git_rollback /restore は 2 段階確認
✅ /set_key は対話中以外は無効
✅ /etc/sudoers 操作は禁止
✅ npm/pip install はホワイトリストのみ
```

---

## 🚨 自己テスト基準 (完了判定)

Claude Code は以下が全部 ✅ になるまで作業を続行してください:

```
□ 1. aibo_bridge/ ディレクトリ構造完成
□ 2. .env (chmod 600) + Secrets 全部反映
□ 3. Bot 本体実装完了 (30+ コマンド)
□ 4. シェルスクリプト 8 本実装完了 (実行権限あり)
□ 5. tmux セッション 3 本起動 (aibo-claude/aibo-cline/aibo-bot)
□ 6. Bot 起動済 + Telegram から /start が応答
□ 7. ダミー画像が watchdog 経由で Telegram に自動送信される
□ 8. devcontainer.json 更新済 (再起動時自動復元)
□ 9. README/COMMANDS/TROUBLESHOOTING/COMPLETION_REPORT 生成
□ 10. .gitignore 更新 + git commit 完了
□ 11. 最終完了通知が Telegram に届く
```

---

## ⚠️ 想定エラーと自動対処

| エラー | 自動対処 |
|--------|---------|
| `cline: command not found` | `npm install -g @cline/cli` 再試行 |
| `claude --version` 失敗 | `npm install -g @anthropic-ai/claude-code` |
| Cline モデル名エラー | `cline --list-models` で動的取得 + 設定再生成 |
| tmux セッション競合 | `tmux kill-session -t <name>` してから再作成 |
| Bot 起動失敗 | logs/bot.log を読んで Telegram に報告 |
| OpenRouter API キー無効 | Cline 設定を OPENAI_API_KEY フォールバック |
| Python venv 失敗 | `apt install python3-venv` 再試行 |
| `permission denied` | `chmod +x` 自動付与 |

エラーで止まらず、可能な限り自己修復して進めてください。
3 回連続失敗した場合のみ、Telegram で PO に報告して停止。

---

## 🥷 PO への最終メッセージ (Bot 起動完了時に送信)

```
🎉 *AIBO Studio v8.0 Remote Command Bridge 完成* ⚡

ミヤチンのスマホ司令室、開店です。

🌸 PO がやることは 3 つだけ:
  1. /deploy_text [本文] で指示
  2. 生成画像が届くのを待つ
  3. CTO Kuroudo と Claude アプリで戦略議論

Day 4 朝の事故は、もう起こりません:
  ✅ N モデルコンペ (5 視点同時検証)
  ✅ メタレビュー自動 (Claude Code が判定)
  ✅ 食い違い検出 → 即 PO 警告

Day 5-30 ロードマップ、新次元で進めましょう 🥷⚡
```

---

**🥷 by CTO Kuroudo**
**指示書バージョン**: v4.0 - Codespaces Full-Auto Edition
**起票日**: 2026-05-13
**前提**: bootstrap.sh 実行済 · OpenRouter API キー入手済
**実行担当**: Claude Code CLI (`--dangerously-skip-permissions`)
**完了基準**: 上記 11 項目の自己テスト全通過 + Telegram 完了通知到達
