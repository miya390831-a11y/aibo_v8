# AIBO Cyber Studio v8.0 — Frontend

V0 由来の Next.js 15 + React 19 + TypeScript + Tailwind 4 UI。バックエンドはリポジトリ直下の `09_fastapi_server.py`（#3a）。

## セットアップ

```bash
cd frontend
npm install
cp .env.local.example .env.local   # Windows: copy .env.local.example .env.local
# .env.local の NEXT_PUBLIC_API_URL を ngrok または http://localhost:8000 に設定
npm run dev
```

→ http://localhost:3000

## Google Drive 同期について

**`node_modules/` と `.next/` は Drive 同期から除外してください。**（数百 MB〜1 GB、同期地獄・容量圧迫の原因）

## 開発状況

- [x] #3a FastAPI
- [x] #3b 本 frontend 統合
- [ ] #3c Portrait 実 API 接続
- [ ] #3d 素体化・ライブラリ本実装

## Python 側の依存（#3a）

リポジトリ直下の `requirements-fastapi.txt` を参照（Gradio 6.x と整合するバージョン下限あり）。
