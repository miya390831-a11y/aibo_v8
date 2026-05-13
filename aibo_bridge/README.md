# 🥷 AIBO Remote Command Bridge - クイックスタート

**PO ミヤチン専用 · 全自動セットアップガイド**

---

## 🌟 PO がやること (合計 5 分)

### Step 1: スマホで Token を 2 つ取得 (3 分)

#### Telegram Bot Token
1. スマホ Telegram で **@BotFather** に話しかける
2. `/newbot` と送信
3. Bot 名: `AIBO Studio Bridge` と入力
4. ユーザー名: `aibo_bridge_<your_unique_name>_bot` と入力 (末尾 `_bot` 必須)
5. 表示される **Token (`1234567890:ABC-DEF...`)** をコピー

#### あなたの Telegram User ID
1. スマホ Telegram で **@userinfobot** に話しかける
2. `/start` と送信
3. 表示される **ID (数字)** をコピー

### Step 2: 自分の Bot に話しかける (30 秒)

⚠️ **重要**: 取得した Bot に **必ず一度メッセージを送ってください**
(Bot が後で PO に話しかけられるようにするため)

例: `Hello` とだけ送信

### Step 3: Cursor ターミナルで 1 行実行 (1 分)

PC で Cursor を開いて、ターミナル (`Ctrl+\``) で:

```bash
curl -fsSL https://raw.githubusercontent.com/miya390831-a11y/aibo_v8/main/aibo_bridge/bootstrap.sh | bash
```

または、bootstrap.sh をローカルに保存している場合:

```bash
bash bootstrap.sh
```

### Step 4: ターミナルの指示に従う (1 分)

ターミナルが以下を聞いてくるので入力:

```
📲 Telegram Bot Token を貼り付けて Enter: [Step 1 で取得した Token]
🆔 あなたの Telegram User ID (数字のみ): [Step 1 で取得した ID]
🔑 OpenRouter API Key [Enter でスキップ]: [既に持っている OpenRouter Key]
🔑 OpenAI API Key [Enter でスキップ]: [既に持っている OpenAI Key]
```

### Step 5: 終了 → スマホ放置 (60-90 分)

```
ターミナル: 🎉 Bootstrap 完了 · Claude Code 起動中

PO はここで:
  ☕ カフェ移動
  🌸 散歩
  ♨️ サウナ
  💤 昼寝
  
スマホ Telegram を Pin 留めしておくだけ
```

60-90 分後、スマホ Telegram に通知:

```
🎉 AIBO Studio v8.0 Remote Command Bridge 完成 ⚡

/help でコマンド一覧確認
```

---

## 🎯 完成後の使い方

### スマホ 1 台で AIBO 開発

```
☕ 朝、カフェで:

[Claude アプリ (CTO Kuroudo) と戦略議論]
ミヤチン: "今日は SITUATION モードを進めたい"
CTO Kuroudo: [指示書ドラフト返却]

[指示書本文をコピー → Telegram Bot にペースト]
ミヤチン: /deploy_text
         (指示書本文を貼り付け)

[Bot が自動実行]
Bot: 🚀 実行開始
     ⏳ 実行中... (60 秒ごとに進捗)
     ✅ 完了
     [生成画像が自動配信]

[スマホで結果確認]
ミヤチン: → Claude アプリで CTO に相談
         → 修正指示書 → /deploy_text → 繰り返し
```

---

## 💎 重要コマンド (覚えるのはこれだけ)

```
/start              Bot に挨拶
/help               全コマンド一覧
/status             環境状態
/deploy_text [本文]  指示書を即実行
/compete_n [file]   N モデルコンペ ★ Day 4 朝の事故防止
/halt               緊急停止
```

---

## 🚨 トラブル時

### Bot が応答しない
```
スマホで:
  /status
→ 返答がなければ Codespace が止まっている

Cursor ターミナルで:
  gh codespace list
→ 該当 Codespace を確認

  gh codespace start -c <CODESPACE_NAME>
→ 起動
```

### 認証エラーが出る
```
".env が間違っているか、ALLOWED_USER_ID が違う"

Cursor ターミナルで:
  gh codespace ssh -c <CODESPACE_NAME>
  cat /workspaces/aibo_v8/aibo_bridge/config/.env
→ TELEGRAM_ALLOWED_USER_ID を確認
```

### 緊急ロールバック
```
Cursor ターミナルで:
  gh codespace stop -c <CODESPACE_NAME>
→ 全停止

git で:
  git reset --hard HEAD~1
→ 直前状態に戻す
```

---

## 🛡 セキュリティ

```
✅ Telegram User ID 認証 (PO ミヤチンのみ操作可能)
✅ API キーは .env (chmod 600) で保護
✅ Codespace は使わない時 /codespace_stop で停止 (課金停止)
✅ git に .env / config/*.json は除外
```

---

## 💰 コスト目安

```
GitHub Codespaces:
  ・無料枠 60h/月 (Free)
  ・180h/月 (Pro $4/月)
  ・超過時: $0.18/h (Standard 2-core)
  
OpenRouter:
  ・従量課金 (DeepSeek なら超安・月 $5-10 で N モデルコンペ可能)

Anthropic Max プラン:
  ・既存のため追加コストなし (Claude Code は Max 経由認証)

合計: 月 $5-30 程度
```

---

🥷 これで **「スマホ 1 台で AIBO Studio v8.0 開発完結」** が実現。
Day 4 朝の 9 時間連戦の集大成、ここに完成だ。

PO ミヤチン、よい遠隔開発を 🌸☕⚡

— CTO Kuroudo
