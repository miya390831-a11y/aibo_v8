"""
RunPod fullstack: Colab と同じ Phase A–F を実行し FastAPI に CharacterOrchestrator を接続する。

環境変数:
  AIBO_RUNTIME=runpod (Dockerfile で設定)
  AIBO_DATA_ROOT (既定 /workspace/aibo)
  AIBO_AUTO_ORCHESTRATOR=1 で 09_fastapi_server の lifespan から本モジュールが起動される
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from importlib import import_module

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("aibo.fastapi.runpod_bootstrap")


def bootstrap_and_attach() -> None:
    os.environ.setdefault("AIBO_RUNTIME", "runpod")
    os.environ.setdefault("AIBO_DATA_ROOT", "/workspace/aibo")
    root = os.environ["AIBO_DATA_ROOT"]
    os.environ.setdefault("HF_HOME", f"{root}/hf")
    os.environ.setdefault("TRANSFORMERS_CACHE", f"{root}/hf/transformers")
    os.environ.setdefault("DIFFUSERS_CACHE", f"{root}/hf/diffusers")
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", f"{root}/hf/hub")

    hf = os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HF_TOKEN")
    if hf:
        os.environ["HUGGINGFACE_HUB_TOKEN"] = hf
        logger.info("Hugging Face トークンは環境変数から設定済み")
    else:
        logger.warning(
            "HUGGINGFACE_HUB_TOKEN 未設定 · FLUX.1-dev 等のゲート済みモデルで失敗する場合があります"
        )

    logger.info(
        "RunPod orchestrator bootstrap: Phase A–F 開始 (初回はモデル DL で数分〜数十分钟かかります)"
    )

    main_mod = import_module("07_main")
    m = main_mod.AiboMain()

    if not m.phase_a_bootstrap(skip_if_done=False):
        raise RuntimeError("Phase A (bootstrap) に失敗しました")
    if not m.phase_b_resolve_strategy():
        raise RuntimeError("Phase B (strategy) に失敗しました")

    logger.info(
        "Phase C 直前 · HF 認証: HF_TOKEN=%s · HUGGINGFACE_HUB_TOKEN=%s（ゲート済みモデルには SET が必要）",
        "SET" if (os.environ.get("HF_TOKEN") or "").strip() else "NOT SET",
        "SET" if (os.environ.get("HUGGINGFACE_HUB_TOKEN") or "").strip() else "NOT SET",
    )
    try:
        ok_c = m.phase_c_build_pipeline()
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("Phase C で未捕捉例外（07_main 外）:\n%s", tb)
        raise RuntimeError(
            f"Phase C (pipeline build) で例外が発生しました: {type(e).__name__}: {e}\n"
            f"--- トレースバック ---\n{tb}"
        ) from e

    if not ok_c:
        detail = ""
        pm = getattr(m, "pipeline_mgr", None)
        if pm is not None and hasattr(pm, "status"):
            try:
                detail = f" pipeline_mgr.status()={pm.status()!r}"
            except Exception as st_e:
                detail = f" pipeline_mgr.status() 取得失敗: {st_e!r}"
        last_msg = getattr(pm, "last_build_error_message", None) if pm else None
        last_tb = getattr(pm, "last_build_traceback", None) if pm else None
        if last_msg:
            logger.error("PipelineManager.last_build_error_message: %s", last_msg)
        if last_tb:
            logger.error("PipelineManager.last_build_traceback:\n%s", last_tb)
        logger.error(
            "Phase C が False（FluxA100PipelineManager.build 失敗）。%s · 403/認証・容量不足の可能性があります。",
            detail or "status 取得不可",
        )
        extra = ""
        if last_msg:
            extra += f"\n\n[last_build_error_message]\n{last_msg}"
        if last_tb:
            extra += f"\n\n[last_build_traceback]\n{last_tb}"
        raise RuntimeError(
            "Phase C (pipeline build) に失敗しました（build() が False）。\n"
            "Hugging Face のゲート済みモデル（例: FLUX.1-dev）を使う場合は、デプロイ元のシェルで "
            "HUGGINGFACE_HUB_TOKEN または HF_TOKEN を設定してから runpod_deploy_fullstack.py を実行し、"
            "Pod ログ先頭の HF_TOKEN / HUGGINGFACE_HUB_TOKEN が SET か確認してください。\n"
            f"追加情報:{detail}{extra}"
        )
    if not m.phase_d_identity():
        logger.warning("Phase D (identity) 一部失敗 · PuLID/ControlNet 等が制限される可能性があります")
    if not m.phase_e_assets():
        raise RuntimeError("Phase E (assets) に失敗しました")
    if not m.phase_f_orchestrator():
        raise RuntimeError("Phase F (orchestrator) に失敗しました")

    srv = import_module("09_fastapi_server")
    srv.attach_orchestrator(m.orchestrator, m.pipeline_mgr)
    logger.info("RunPod orchestrator bootstrap: attach 完了 · /api/portrait/generate 利用可能")
