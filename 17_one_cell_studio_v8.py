"""
================================================================================
17_one_cell_studio_v8.py — AIBO Studio v8.0 · ワンセル起動 (Colab)

Colab の「起動セル」と同等の 7 ステップを 1 回の関数呼び出しで実行する。

前提:
  - cwd が aibo_v7 (Drive マウント済み /content/drive/MyDrive/aibo_v7 など)
  - Phase まで進んだ AiboMain があり orchestrator / pipeline_mgr が取得できること

使い方 (Colab):
    from importlib import import_module
    oc = import_module("17_one_cell_studio_v8")
    url = oc.run_one_cell_v8(m.orchestrator, m.pipeline_mgr)

================================================================================
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from importlib import import_module
from pathlib import Path
from typing import Any, Optional


def _print_banner(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _pip_install_quiet(packages: list[str]) -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", *packages],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️ pip install 失敗: {e.stderr or e}")
        return False


def _colab_userdata_token() -> Optional[str]:
    try:
        from google.colab import userdata  # type: ignore

        t = userdata.get("NGROK_AUTHTOKEN")
        return str(t).strip() if t else None
    except Exception:
        return None


def _ensure_packages(skip_pip: bool) -> None:
    print("\n[2/7] 必要パッケージ確認")

    def _missing(names: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for mod in names:
            try:
                __import__(mod)
            except ImportError:
                out.append(mod)
        return out

    miss0 = _missing(("fastapi", "uvicorn", "pyngrok"))
    if "fastapi" not in miss0:
        print("  ✅ fastapi")

    if miss0 and not skip_pip:
        print("  📦 pyngrok install 中...")
        pkgs = ["fastapi>=0.115", "uvicorn[standard]>=0.32", "python-multipart>=0.0.12", "pyngrok"]
        if _pip_install_quiet(pkgs):
            print("  ✅ pyngrok install 完了")
        else:
            print("  ⚠️ pip が部分的に失敗した可能性あり")

    miss1 = _missing(("fastapi", "uvicorn", "pyngrok"))
    if miss1:
        print(f"  ⚠️ 不足モジュール: {miss1}")
    elif not miss0:
        print("  ✅ pyngrok (確認済み)")


def _resolve_orchestrator(
    orchestrator: Any | None,
    pipeline_manager: Any | None,
) -> tuple[Any, Any]:
    if orchestrator is not None:
        return orchestrator, pipeline_manager

    main = import_module("07_main")
    inst = main.get_instance()
    if inst is None:
        raise RuntimeError(
            "orchestrator が渡されていません。Colab では AiboMain().run() 相当まで進めてから "
            "run_one_cell_v8(m.orchestrator, m.pipeline_mgr) を呼ぶか、m を明示渡ししてください。"
        )
    orch = getattr(inst, "orchestrator", None)
    pm = getattr(inst, "pipeline_mgr", None)
    if orch is None:
        raise RuntimeError("07_main.get_instance() に orchestrator がありません (Phase F 未完了?)")
    return orch, pm


def _write_env_latest(public_url: str) -> Path | None:
    lines = (
        "NEXT_PUBLIC_API_URL=" + public_url.rstrip("/") + "\n"
        "NEXT_PUBLIC_NGROK_SKIP_WARNING=true\n"
    )
    candidates = [
        Path("/content/drive/MyDrive/aibo_v7/.env.local.latest.txt"),
        Path.cwd() / ".env.local.latest.txt",
    ]
    for p in candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(lines, encoding="utf-8")
            return p
        except Exception:
            continue
    return None


def run_one_cell_v8(
    orchestrator: Any | None = None,
    pipeline_manager: Any | None = None,
    *,
    port: int = 8000,
    ngrok_auth_token: Optional[str] = None,
    skip_pip: bool = False,
    skip_ngrok: bool = False,
) -> Optional[str]:
    """
    ワンセル起動の主処理。成功時は公開 URL (https://....ngrok-free.dev) を返す。

    Args:
        orchestrator: CharacterOrchestrator (省略時は 07_main.get_instance() から取得を試みる)
        pipeline_manager: FluxA100PipelineManager (省略可)
        port: FastAPI ポート
        ngrok_auth_token: Ngrok auth token (省略時は環境変数 NGROK_AUTHTOKEN → Colab Secret)
        skip_pip: True で pip インストールをスキップ
        skip_ngrok: True で ngrok を使わず FastAPI のみ (ローカル検証向け)

    Returns:
        公開 HTTPS URL、または ngrok 無効時は None
    """
    _print_banner("🚀 AIBO Studio v8.0 · ワンセル起動")

    # [1/7] path
    cwd = Path.cwd()
    print(f"\n[1/7] パス設定 OK · cwd: {cwd}")

    _ensure_packages(skip_pip)

    # [3/7] orchestrator
    print("\n[3/7] orchestrator / pipeline_manager 検出")
    orch, pm = _resolve_orchestrator(orchestrator, pipeline_manager)
    print(f"  ✅ orchestrator: {type(orch).__name__}")
    print(f"  ✅ pipeline_manager: {type(pm).__name__ if pm is not None else 'None'}")

    # [4/7] FastAPI
    print("\n[4/7] FastAPI 起動")
    main = import_module("07_main")
    main.launch_fastapi_in_background(orch, pm, port=port)
    time.sleep(1.5)

    local_status = f"http://127.0.0.1:{port}/api/system/status"
    try:
        with urllib.request.urlopen(local_status, timeout=8) as r:
            _ = r.read()
        print("  ✅ /api/system/status 疎通確認 (local)")
    except Exception as e:
        print(f"  ⚠️ local 疎通失敗 (続行): {e}")

    public_url: Optional[str] = None

    # [5/7] ngrok
    if skip_ngrok:
        print("\n[5/7] ngrok 公開")
        print("  ⏭ skip_ngrok=True のためスキップ")
    else:
        print("\n[5/7] ngrok 公開")
        token = (ngrok_auth_token or os.environ.get("NGROK_AUTHTOKEN") or "").strip() or _colab_userdata_token()
        if not token:
            print("  ⚠️ NGROK_AUTHTOKEN がありません (環境変数または Colab Secret NGROK_AUTHTOKEN)")
            print("     → ngrok をスキップします。ローカルフロントは以下で接続可能:")
            print(f"        NEXT_PUBLIC_API_URL=http://127.0.0.1:{port}")
        else:
            try:
                from pyngrok import conf, ngrok

                conf.get_default().auth_token = token
                # 既存トンネルがあれば切断
                try:
                    ngrok.kill()
                except Exception:
                    pass
                tunnel = ngrok.connect(addr=port, proto="http")
                public_url = tunnel.public_url
                if public_url.startswith("http://"):
                    public_url = "https://" + public_url[len("http://") :]
                print(f"  ✅ ngrok 公開完了")
                print(f"     URL: {public_url}")
            except Exception as e:
                print(f"  ❌ ngrok 失敗: {e}")
                print(f"     ローカル API のみ: http://127.0.0.1:{port}")

    # [6/7] ngrok 経由疎通
    if public_url:
        print("\n[6/7] ngrok 経由疎通確認")
        probe = public_url.rstrip("/") + "/api/system/status"
        try:
            req = urllib.request.Request(probe, headers={"ngrok-skip-browser-warning": "true"})
            with urllib.request.urlopen(req, timeout=15) as r:
                _ = r.read()
            print(f"  ✅ Status: {r.status} OK")
        except Exception as e:
            print(f"  ⚠️ ngrok 疎通: {e} (ブラウザ警告ページの場合は PO 側 SKIP_WARNING で対処)")
    else:
        print("\n[6/7] ngrok 経由疎通確認")
        print("  ⏭ スキップ (公開 URL なし)")

    # [7/7] PO 向け案内
    base = public_url.rstrip("/") if public_url else f"http://127.0.0.1:{port}"
    env_path = _write_env_latest(base)

    print("\n[7/7] ローカル PC 向け案内")
    print()
    print("=" * 60)
    print("📋 PO 向けクイックスタート")
    print("=" * 60)
    print()
    print("【1】 ローカル PC で以下を実行:")
    print()
    print("  cd C:\\Users\\yuuki\\aibo_v7\\frontend")
    print()
    print("【2】 .env.local の中身を以下に書き換え:")
    print()
    print("  ─────────────────────────────────────────")
    print(f"NEXT_PUBLIC_API_URL={base}")
    print("NEXT_PUBLIC_NGROK_SKIP_WARNING=true")
    print("  ─────────────────────────────────────────")
    print()
    print("【3】 Cursor のターミナルで:")
    print()
    print("  npm run dev")
    print("  (既に動いてたら Ctrl+C で停止 → 再起動)")
    print()
    print("【4】 ブラウザで:")
    print()
    print("  http://localhost:3000")
    print()
    if env_path:
        print("💾 .env.local のテンプレを保存しました:")
        print(f"     {env_path}")
        print("   (コピペ用)")
    print()
    print("=" * 60)
    print("⚠️ 注意:")
    print("=" * 60)
    print("  - ngrok URL は Colab 再起動 / セッション切れで変わります")
    print("  - 変わったらこのセルを再実行 → 新 URL を .env.local に再貼付")
    print("  - npm run dev は環境変数キャッシュのため再起動が必要")
    print()
    print("✅ 起動完了 · AIBO Studio v8.0 全層稼働中")
    return public_url


if __name__ == "__main__":
    print("このモジュールは Colab から import して使います。")
    print()
    print("例:")
    print("  from importlib import import_module")
    print("  oc = import_module('17_one_cell_studio_v8')")
    print("  oc.run_one_cell_v8(m.orchestrator, m.pipeline_mgr)")
    print()
