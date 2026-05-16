"""
17_neutralize_engine.py — v8.0 Layer X · 素体化 (PuLID + Hyper-FLUX 再生成)

顔保持・体型保持は既存 PORTRAIT パイプライン（CharacterOrchestrator.generate）で実行する。
第1引数名は歴史的に pipeline_manager だが、実際には Orchestrator を渡す（09 と同一）。
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import torch

logger = logging.getLogger("AIBO_v7.NeutralizeEngine")

NEUTRALIZE_BASE_PROMPT = (
    "natural standing pose, "
    "feet shoulder-width apart, "
    "hands relaxed at sides, "
    "looking straight at camera, "
    "wearing simple plain white sporty separate swimwear, "
    "minimal swimwear design, "
    "athletic two-piece swimsuit, "
    "clean and modest cut, "
    "plain white seamless background, "
    "studio mannequin-style presentation, "
    "even neutral studio lighting, "
    "soft shadows, "
    "neutral calm expression, "
    "no smile, "
    "full body visible head to toe, "
    "1024x1536 portrait orientation, "
    "photorealistic, "
    "sharp focus on face, "
    "clear body silhouette"
)

NEUTRALIZE_NEGATIVE_PROMPT = (
    "dynamic pose, action pose, sitting, lying, "
    "crossed arms, hands on hips, twisted body, "
    "casual clothes, dress, t-shirt, jeans, suit, uniform, "
    "complex outfit, fashion clothing, accessories, "
    "revealing swimwear, sexy bikini, lingerie, "
    "sheer fabric, transparent clothing, nude, "
    "outdoor, beach, pool, scenery, complex background, "
    "indoor room, furniture, "
    "smiling, frowning, dramatic expression, exaggerated emotion, "
    "close-up, cropped, partial body, head only, "
    "cropped legs, cropped feet, "
    "blurry, low quality, artifacts, deformed body, "
    "unrealistic proportions, anime style, illustration, "
    "doll-like, plastic"
)


@dataclass
class NeutralizeResult:
    image: Optional[Any]
    success: bool
    elapsed: float
    body_shape_addendum: str
    seed_used: int
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


def neutralize_image_with_pipeline_manager(
    orchestrator: Any,
    face_refs: list,
    body_shape: Optional[dict],
    seed: Optional[int] = None,
) -> NeutralizeResult:
    """
    素体化: PuLID 再生成（09_fastapi_server._run_portrait_generation と同じ経路）。

    Args:
        orchestrator: CharacterOrchestrator（attach_orchestrator で注入されたインスタンス）
        face_refs: PIL.Image のリスト（先頭が本人）
        body_shape: 5 チャート辞書（None ならデフォルト体型）
        seed: 乱数シード（None でオーケストレータ側ランダム）

    Note:
        引数名は仕様書どおり pipeline_manager 相当スロットだが、
        AIBO 実装では orchestrator のみ使用する。
    """
    start = time.time()
    if not face_refs:
        return NeutralizeResult(
            image=None,
            success=False,
            elapsed=0.0,
            body_shape_addendum="",
            seed_used=0,
            error="no_face_refs",
        )

    fs = importlib.import_module("09_fastapi_server")
    if body_shape:
        bs_model = fs.BodyShape(**body_shape)
    else:
        bs_model = None
    addendum = fs.body_shape_to_addendum(bs_model)

    full_prompt = NEUTRALIZE_BASE_PROMPT
    if addendum:
        full_prompt = f"{NEUTRALIZE_BASE_PROMPT}, {addendum}"

    logger.info(
        "[NeutralizeEngine] 開始 addendum_len=%d seed=%s",
        len(addendum),
        seed,
    )

    try:
        gen_cfg, id_cfg = fs._build_configs(
            face_imgs=face_refs,
            prompt=full_prompt,
            negative_prompt=NEUTRALIZE_NEGATIVE_PROMPT,
            num_inference_steps=8,
            guidance_scale=3.5,
            seed=seed,
            width=1024,
            height=1536,
        )
        StudioMode = fs._resolve_studio_mode()
        result = orchestrator.generate(
            gen_cfg,
            id_cfg,
            mode=StudioMode.PORTRAIT,
        )
        elapsed = time.time() - start

        if getattr(result, "error", None):
            return NeutralizeResult(
                image=None,
                success=False,
                elapsed=elapsed,
                body_shape_addendum=addendum,
                seed_used=int(getattr(result, "seed", 0) or 0),
                error=str(result.error),
            )
        if result.final_image is None:
            return NeutralizeResult(
                image=None,
                success=False,
                elapsed=elapsed,
                body_shape_addendum=addendum,
                seed_used=int(getattr(result, "seed", 0) or 0),
                error="no_image",
            )

        seed_used = int(result.seed) if getattr(result, "seed", None) is not None else 0
        logger.info("[NeutralizeEngine] 完了 %.2fs seed=%s", elapsed, seed_used)
        return NeutralizeResult(
            image=result.final_image,
            success=True,
            elapsed=elapsed,
            body_shape_addendum=addendum,
            seed_used=seed_used,
        )

    except torch.cuda.OutOfMemoryError as oom:
        torch.cuda.empty_cache()
        logger.error("[NeutralizeEngine] OOM: %s", oom)
        return NeutralizeResult(
            image=None,
            success=False,
            elapsed=time.time() - start,
            body_shape_addendum=addendum,
            seed_used=0,
            error=f"oom: {oom}",
        )
    except Exception as exc:
        logger.exception("[NeutralizeEngine] エラー: %s", exc)
        return NeutralizeResult(
            image=None,
            success=False,
            elapsed=time.time() - start,
            body_shape_addendum=addendum,
            seed_used=0,
            error=f"inference_error: {exc}",
        )
