"""
RunPod 用エントリ: 同一プロセスで Phase A–F（同期）→ Uvicorn 起動。

バックグラウンドスレッドだと初期化失敗が見えにくい・デーモンスレッドの問題を避ける。
初回はモデル DL で(port 8000 はしばらく閉じたまま)。
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    # RunPod Logs で HF が Pod に届いたか即確認できるようにする（値は出さない）
    print(
        "HF_TOKEN:",
        "SET" if (os.environ.get("HF_TOKEN") or "").strip() else "NOT SET",
        flush=True,
    )
    print(
        "HUGGINGFACE_HUB_TOKEN:",
        "SET" if (os.environ.get("HUGGINGFACE_HUB_TOKEN") or "").strip() else "NOT SET",
        flush=True,
    )

    os.environ.setdefault("AIBO_RUNTIME", "runpod")
    os.environ.setdefault("AIBO_DATA_ROOT", "/workspace/aibo")
    os.environ.setdefault("AIBO_AUTO_ORCHESTRATOR", "1")

    print("[19_runpod_combined_entry] 同期オーケストレータ初期化を開始…", flush=True)
    from importlib import import_module

    import_module("18_runpod_fastapi_bootstrap").bootstrap_and_attach()
    print("[19_runpod_combined_entry] attach 完了 · Uvicorn 起動", flush=True)

    # lifespan 内の二重ブートストラップを抑止
    os.environ["AIBO_SKIP_BACKGROUND_ORCHESTRATOR"] = "1"

    import_module("09_fastapi_server").run_server()


if __name__ == "__main__":
    main()
    sys.exit(0)
