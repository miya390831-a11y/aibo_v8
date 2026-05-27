"""
================================================================================
09_fastapi_server.py — AIBO Studio v8.0 FastAPI バックエンド

V0 Next.js UI 統合用の HTTP REST + SSE 層。既存 CharacterOrchestrator をラップする。
06_ui.py (Gradio) と並行運用 · 既存オーケストレータは無改造で import のみ。

依存 (Colab / ローカルで事前インストール):
    pip install fastapi==0.115.0 "uvicorn[standard]==0.32.0" python-multipart==0.0.12

履歴:
    2026-05-09: Cursor #3a 新設 (PORTRAIT MVP)
================================================================================
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from PIL import Image

import importlib

# ─── AIBO 既存モジュール (無改造 · import のみ) ───
cfg_mod = importlib.import_module("01_config")

logger = logging.getLogger("aibo.fastapi")
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)

# ============================================================
# Module-level state
# ============================================================

_orchestrator_ref: Any = None
_pipeline_manager_ref: Any = None


def attach_orchestrator(orch: Any, pm: Any = None) -> None:
    """起動済み CharacterOrchestrator を FastAPI に注入する。"""
    global _orchestrator_ref, _pipeline_manager_ref
    _orchestrator_ref = orch
    _pipeline_manager_ref = pm
    logger.info("Orchestrator attached: %s", type(orch).__name__)


def get_orchestrator() -> Any:
    if _orchestrator_ref is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not attached. Call attach_orchestrator() first.",
        )
    return _orchestrator_ref


# ============================================================
# Job registry
# ============================================================


@dataclass
class JobProgress:
    job_id: str
    status: str = "queued"
    progress: float = 0.0
    stage: str = ""
    elapsed_sec: float = 0.0
    eta_sec: float = 0.0
    message: str = ""
    result_image_b64: Optional[str] = None
    result_meta: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    _event_queue: Optional[asyncio.Queue] = field(default=None, repr=False)
    _started_at: float = field(default_factory=time.time)
    _completed_at: float = 0.0


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, JobProgress] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> str:
        job_id = str(uuid.uuid4())
        async with self._lock:
            self._jobs[job_id] = JobProgress(
                job_id=job_id,
                _event_queue=asyncio.Queue(),
            )
        return job_id

    def get(self, job_id: str) -> JobProgress:
        if job_id not in self._jobs:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return self._jobs[job_id]

    async def update(self, job_id: str, **kwargs: Any) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            for k, v in kwargs.items():
                if hasattr(job, k):
                    setattr(job, k, v)
            job.elapsed_sec = time.time() - job._started_at
            if kwargs.get("status") in ("completed", "failed"):
                job._completed_at = time.time()

            if job._event_queue is not None:
                event_data = {
                    "status": job.status,
                    "progress": job.progress,
                    "stage": job.stage,
                    "elapsed_sec": job.elapsed_sec,
                    "eta_sec": job.eta_sec,
                    "message": job.message,
                    "error": job.error,
                }
                try:
                    job._event_queue.put_nowait(event_data)
                except asyncio.QueueFull:
                    pass

    async def cleanup_old(self, max_age_sec: int = 3600) -> None:
        now = time.time()
        async with self._lock:
            to_remove = [
                jid
                for jid, j in self._jobs.items()
                if j.status in ("completed", "failed")
                and j._completed_at > 0
                and (now - j._completed_at) > max_age_sec
            ]
            for jid in to_remove:
                del self._jobs[jid]


_jobs = JobRegistry()


# ============================================================
# Pydantic models
# ============================================================


class BodyShapeAxis(BaseModel):
    x: float = Field(0.0, ge=-1.0, le=1.0)
    y: float = Field(0.0, ge=-1.0, le=1.0)


class BodyShape(BaseModel):
    base: BodyShapeAxis = BodyShapeAxis()
    proportion: BodyShapeAxis = BodyShapeAxis()
    silhouette: BodyShapeAxis = BodyShapeAxis()
    curves: BodyShapeAxis = BodyShapeAxis()
    posture: BodyShapeAxis = BodyShapeAxis()


class GenerateRequest(BaseModel):
    face_references: list[str]
    prompt: str = ""
    negative_prompt: Optional[str] = None
    body_shape: Optional[BodyShape] = None
    num_inference_steps: int = Field(8, ge=1, le=50)
    guidance_scale: float = Field(4.0, ge=1.0, le=10.0)
    seed: Optional[int] = None
    width: int = Field(1024, ge=512, le=2048)
    height: int = Field(1024, ge=512, le=2048)


class NeutralizeRequest(BaseModel):
    """素体化 API (#3d-neutralize): 顔参照 + 体型チャート"""

    face_refs: list[str]
    body_shape: Optional[BodyShape] = None
    seed: Optional[int] = None


class NeutralizeResponse(BaseModel):
    image: str
    body_shape_addendum: str
    seed_used: int
    elapsed: float
    meta: Optional[dict[str, Any]] = None


class LibrarySaveRequest(BaseModel):
    neutral_job_id: str
    name: str = "私の素体001"
    memo: str = ""
    tags: list[str] = []


class ExtractBodyShapeRequest(BaseModel):
    image: str


class ExtractBodyShapeResponse(BaseModel):
    body_shape: BodyShape
    confidence: float


class ApplyMakeupRequest(BaseModel):
    base_image: str
    makeup_style: str
    intensity: str


class ApplyMakeupResponse(BaseModel):
    image: str
    meta: dict[str, Any]


# ============================================================
# Body shape → prompt (v7.5.0 系 · 5 段階量子化)
# ============================================================

_BODY_SHAPE_PHRASES: dict[str, dict[str, dict[float, str]]] = {
    "base": {
        "x": {
            -1.0: "very slim build, slender frame",
            -0.5: "slim build",
            0.0: "",
            0.5: "athletic build, toned physique",
            1.0: "muscular build, broad frame",
        },
        "y": {
            -1.0: "very petite, 150cm range",
            -0.5: "petite stature",
            0.0: "",
            0.5: "tall stature, 170cm+ range",
            1.0: "very tall, model-height",
        },
    },
    "proportion": {
        "x": {
            -1.0: "shorter legs, traditional proportions",
            -0.5: "slightly shorter legs",
            0.0: "",
            0.5: "long legs, model proportions",
            1.0: "extremely long legs, fashion-model proportions",
        },
        "y": {
            -1.0: "youthful round face, 6-head proportions",
            -0.5: "youthful features",
            0.0: "",
            0.5: "mature features, 7.5-head proportions",
            1.0: "mature elegant features, 8-head proportions",
        },
    },
    "silhouette": {
        "x": {
            -1.0: "straight athletic silhouette",
            -0.5: "athletic silhouette",
            0.0: "",
            0.5: "feminine curves",
            1.0: "hourglass figure, pronounced curves",
        },
        "y": {
            -1.0: "delicate frame, slender",
            -0.5: "delicate frame",
            0.0: "",
            0.5: "voluptuous figure",
            1.0: "very voluptuous figure",
        },
    },
    "curves": {
        "x": {
            -1.0: "very slender, athletic curves",
            -0.5: "slender figure",
            0.0: "",
            0.5: "fuller curves",
            1.0: "voluptuous curves, glamorous figure",
        },
        "y": {
            -1.0: "straight body shape, athletic build",
            -0.5: "slight curve definition",
            0.0: "",
            0.5: "defined waistline",
            1.0: "hourglass figure, defined waist",
        },
    },
    "posture": {
        "x": {
            -1.0: "slightly slouched posture",
            -0.5: "relaxed posture",
            0.0: "",
            0.5: "upright posture",
            1.0: "perfectly upright, model-like posture",
        },
        "y": {
            -1.0: "very relaxed stance",
            -0.5: "casual stance",
            0.0: "",
            0.5: "confident stance",
            1.0: "sharp confident stance, athletic poise",
        },
    },
}

_MAKEUP_PRESETS: dict[str, dict[str, Any]] = {
    "natural": {
        "addendum": {
            "light": "subtle natural makeup, light foundation, neutral lip",
            "medium": "natural makeup, even skin tone, soft lip color",
            "heavy": "polished natural makeup, defined features, rosy lip",
        }
    },
    "pink": {
        "addendum": {
            "light": "soft pink blush, light pink lip tint",
            "medium": "pink blush, pink lipstick, soft feminine makeup",
            "heavy": "vibrant pink blush, glossy pink lipstick, feminine glam",
        }
    },
    "glam": {
        "addendum": {
            "light": "soft red lip, light contouring",
            "medium": "red lipstick, smoky eyes, dramatic makeup",
            "heavy": "bold red lipstick, intense smoky eyes, full glam makeup",
        }
    },
    "kbeauty": {
        "addendum": {
            "light": "subtle K-beauty makeup, dewy skin, glossy lips",
            "medium": "natural K-beauty makeup, glass skin, glossy peach lips",
            "heavy": "full K-beauty makeup, dewy glass skin, glossy gradient lips",
        }
    },
    "romantic": {
        "addendum": {
            "light": "soft peach blush, light romantic makeup",
            "medium": "peach blush, romantic soft makeup, dewy finish",
            "heavy": "intense peach blush, romantic glam, dewy luminous finish",
        }
    },
    "cool": {
        "addendum": {
            "light": "subtle cool tone makeup, neutral lip",
            "medium": "sharp eye makeup, matte lips, cool tone",
            "heavy": "intense sharp eye makeup, bold matte lips, cool dramatic look",
        }
    },
    "mode": {
        "addendum": {
            "light": "subtle mode makeup, neutral eye, nude lip",
            "medium": "dark eye makeup, nude lips, fashion makeup",
            "heavy": "intense dark eye makeup, bold fashion look, editorial style",
        }
    },
    "night": {
        "addendum": {
            "light": "shimmery eyes, soft party makeup",
            "medium": "shimmery eyes, deep colors, party makeup",
            "heavy": "intense shimmery eyes, deep dramatic colors, full party glam",
        }
    },
    "nomakeup": {
        "addendum": {
            "light": "barely there makeup, skin tint only",
            "medium": "barely there makeup, skin tint only, natural lips",
            "heavy": "no-makeup makeup look, perfected skin, hint of color",
        }
    },
    "retro": {
        "addendum": {
            "light": "soft red lip, classic vibe",
            "medium": "old Hollywood glamour, red lips, winged eyeliner",
            "heavy": "full old Hollywood glamour, bold red lips, dramatic winged eyeliner",
        }
    },
}

_INTENSITY_DENOISING = {"light": 0.15, "medium": 0.225, "heavy": 0.30}


def _quantize_to_5_levels(value: float) -> float:
    if value <= -0.75:
        return -1.0
    if value <= -0.25:
        return -0.5
    if value < 0.25:
        return 0.0
    if value < 0.75:
        return 0.5
    return 1.0


def body_shape_to_addendum(shape: Optional[BodyShape]) -> str:
    if shape is None:
        return ""
    parts: list[str] = []
    dumped = shape.model_dump()
    for chart, axes in dumped.items():
        for axis_name, val in axes.items():
            q = _quantize_to_5_levels(float(val))
            phrase = (
                _BODY_SHAPE_PHRASES.get(chart, {})
                .get(axis_name, {})
                .get(q, "")
            )
            if phrase:
                parts.append(phrase)
    return ", ".join(parts)


def b64_to_pil(b64_str: str) -> Image.Image:
    if "," in b64_str:
        _, b64_str = b64_str.split(",", 1)
    raw = base64.b64decode(b64_str)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def pil_to_b64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    ext = fmt.lower()
    return f"data:image/{ext};base64,{b64}"


# ============================================================
# Config builders (01_config.py)
# ============================================================


def _build_configs(
    *,
    face_imgs: list[Image.Image],
    prompt: str,
    negative_prompt: Optional[str],
    num_inference_steps: int,
    guidance_scale: float,
    seed: Optional[int],
    width: int,
    height: int,
) -> tuple[Any, Any]:
    GenerationConfig = cfg_mod.GenerationConfig
    IdentityConfig = cfg_mod.IdentityConfig

    gen_cfg = GenerationConfig()
    gen_cfg.prompt = prompt
    if negative_prompt is not None:
        gen_cfg.negative_prompt = negative_prompt
    gen_cfg.num_inference_steps = num_inference_steps
    gen_cfg.guidance_scale = guidance_scale
    gen_cfg.seed = -1 if seed is None else int(seed)
    gen_cfg.width = width
    gen_cfg.height = height
    gen_cfg.enable_pass2 = False

    id_cfg = IdentityConfig()
    id_cfg.reference_image = face_imgs[0]
    if len(face_imgs) > 1:
        id_cfg.reference_images = face_imgs
    else:
        id_cfg.reference_images = None

    return gen_cfg, id_cfg


def _resolve_studio_mode():
    return cfg_mod.StudioMode


# ============================================================
# Portrait generation worker
# ============================================================


async def _fake_progress_updates(job_id: str, total_estimate_sec: float = 25.0) -> None:
    start = time.time()
    try:
        while True:
            await asyncio.sleep(0.5)
            elapsed = time.time() - start
            pct = min(15.0 + (elapsed / total_estimate_sec) * 75.0, 90.0)
            eta = max(total_estimate_sec - elapsed, 0.0)
            if pct < 30:
                stage = "PHASE 1 (HYPER-FLUX)"
            elif pct < 70:
                stage = "PuLID FUSION"
            elif pct < 90:
                stage = "PHASE 3A (GFPGAN)"
            else:
                stage = "FINALIZING"
            await _jobs.update(job_id, progress=pct, stage=stage, eta_sec=eta)
    except asyncio.CancelledError:
        return


async def _run_portrait_generation(job_id: str, req: GenerateRequest) -> None:
    try:
        await _jobs.update(job_id, status="running", stage="VALIDATING", progress=2.0)

        if not req.face_references:
            raise ValueError("face_references is empty (slot 0 is required)")

        await _jobs.update(job_id, stage="DECODING_REFS", progress=5.0)
        face_imgs = [b64_to_pil(b64) for b64 in req.face_references if b64]
        if not face_imgs:
            raise ValueError("No valid face reference images decoded")

        addendum = body_shape_to_addendum(req.body_shape)
        final_prompt = req.prompt
        if addendum:
            final_prompt = f"{req.prompt}, {addendum}" if req.prompt else addendum

        await _jobs.update(job_id, stage="BUILDING_CONFIG", progress=8.0)
        gen_cfg, id_cfg = _build_configs(
            face_imgs=face_imgs,
            prompt=final_prompt,
            negative_prompt=req.negative_prompt,
            num_inference_steps=req.num_inference_steps,
            guidance_scale=req.guidance_scale,
            seed=req.seed,
            width=req.width,
            height=req.height,
        )

        await _jobs.update(job_id, stage="PHASE 1 (HYPER-FLUX)", progress=15.0)
        loop = asyncio.get_running_loop()
        orch = _orchestrator_ref
        if orch is None:
            raise RuntimeError("Orchestrator not attached")

        StudioMode = _resolve_studio_mode()
        progress_task = asyncio.create_task(_fake_progress_updates(job_id))

        def _sync_gen():
            return orch.generate(gen_cfg, id_cfg, mode=StudioMode.PORTRAIT)

        result = await loop.run_in_executor(None, _sync_gen)

        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        if getattr(result, "error", None):
            raise RuntimeError(result.error)
        if result.final_image is None:
            fail_reason = getattr(result, "pass1_fail_reason", None) or "unknown"
            retry_count = getattr(result, "pass1_retry_count", 0)
            raise RuntimeError(
                f"Generation produced no image (retries={retry_count}, reason={fail_reason})"
            )

        await _jobs.update(job_id, stage="ENCODING_RESULT", progress=95.0)
        result_b64 = pil_to_b64(result.final_image)

        meta = {
            "seed": result.seed,
            "phase3_applied": result.phase3_applied,
            "phase3_yaw_deg": result.phase3_yaw_deg,
            "phase3_elapsed_sec": result.phase3_elapsed_sec,
            "elapsed_pass1_sec": result.elapsed_pass1_sec,
            "pulid_used": result.pulid_used,
            "elapsed_total_sec": result.elapsed_total_sec,
            "prompt_used": final_prompt,
            "body_shape_addendum": addendum,
        }

        await _jobs.update(
            job_id,
            status="completed",
            stage="COMPLETED",
            progress=100.0,
            eta_sec=0.0,
            result_image_b64=result_b64,
            result_meta=meta,
            message="ok",
        )
    except Exception as exc:
        logger.error("Job %s failed: %s\n%s", job_id, exc, traceback.format_exc())
        # Drive へエラー自動記録
        try:
            from error_reporter import save_error_report
            save_error_report(
                error=exc,
                context={"endpoint": "/api/portrait/generate", "job_id": job_id},
                request_data={
                    "prompt": req.prompt,
                    "seed": req.seed,
                    "width": req.width,
                    "height": req.height,
                    "num_inference_steps": req.num_inference_steps,
                    "guidance_scale": req.guidance_scale,
                    "face_references_count": len(req.face_references) if req.face_references else 0,
                },
                request_id=job_id,
                phase="portrait_generation",
            )
        except Exception as report_err:
            logger.warning("error_reporter failed (ignored): %s", report_err)
        await _jobs.update(
            job_id,
            status="failed",
            error=str(exc),
            message=f"生成失敗: {exc}",
            progress=100.0,
        )


# ============================================================
# FastAPI lifespan
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(_cleanup_loop())
    logger.info("AIBO FastAPI server started · CORS open · orchestrator attach で生成可能")
    yield
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("AIBO FastAPI server stopped")


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(300)
        await _jobs.cleanup_old(max_age_sec=3600)


app = FastAPI(
    title="AIBO Studio v8.0 API",
    description="V0 Next.js UI 統合用 FastAPI (Cursor #3a)",
    version="8.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.middleware("http")
async def force_cors_headers(request: Request, call_next):
    """
    全レスポンスに CORS ヘッダーを確実に付与する保険 middleware。
    StreamingResponse/SSE で CORS ヘッダーが欠落するケースを回避する。
    """
    response = await call_next(request)
    origin = request.headers.get("origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin if origin != "null" else "*"
    response.headers["Access-Control-Allow-Credentials"] = "false"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, DELETE, PUT, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response

_LIBRARY_MOCK: list[dict[str, Any]] = []


@app.get("/api/system/status")
async def system_status():
    try:
        import torch

        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory / 1e9
            allocated = torch.cuda.memory_allocated(0) / 1e9
            gpu_name = torch.cuda.get_device_name(0)
            return {
                "gpu_available": True,
                "gpu_name": gpu_name,
                "vram_total_gb": round(total, 2),
                "vram_used_gb": round(allocated, 2),
                "vram_pct": round(allocated / total * 100, 1) if total > 0 else 0.0,
                "orchestrator_attached": _orchestrator_ref is not None,
            }
        return {
            "gpu_available": False,
            "orchestrator_attached": _orchestrator_ref is not None,
        }
    except Exception as exc:
        return JSONResponse(
            {"error": str(exc), "gpu_available": False, "orchestrator_attached": _orchestrator_ref is not None},
            status_code=200,
        )


@app.post("/api/portrait/generate")
async def portrait_generate(req: GenerateRequest):
    if _orchestrator_ref is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not attached. Call attach_orchestrator() before generate.",
        )
    job_id = await _jobs.create()
    asyncio.create_task(_run_portrait_generation(job_id, req))
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/portrait/status/{job_id}")
async def portrait_status_sse(job_id: str, request: Request):
    job = _jobs.get(job_id)

    async def event_generator():
        if job.status in ("completed", "failed"):
            payload = {
                "status": job.status,
                "progress": job.progress,
                "stage": job.stage,
                "elapsed_sec": job.elapsed_sec,
                "eta_sec": 0.0,
                "message": job.message,
                "error": job.error,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        queue = job._event_queue
        if queue is None:
            yield f"data: {json.dumps({'error': 'no event queue'})}\n\n"
            return

        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("completed", "failed"):
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

    # SSE は CORSMiddleware の自動付与が効かないケースがあるため手動で付与する
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Credentials": "false",
            "Access-Control-Expose-Headers": "*",
        },
    )


@app.get("/api/portrait/poll/{job_id}")
async def portrait_poll(job_id: str):
    """
    Portrait job の現在進捗を JSON で 1 回返す (polling 用)。
    """
    job = _jobs.get(job_id)
    return {
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "elapsed_sec": job.elapsed_sec,
        "eta_sec": job.eta_sec,
        "message": getattr(job, "message", None),
        "error": getattr(job, "error", None),
    }


@app.post("/api/portrait/extract_body_shape")
async def extract_body_shape(req: ExtractBodyShapeRequest) -> ExtractBodyShapeResponse:
    start_time = time.time()

    try:
        image_data = req.image
        if image_data.startswith("data:"):
            image_data = image_data.split(",", 1)[1]
        image_bytes = base64.b64decode(image_data)
        image = Image.open(io.BytesIO(image_bytes))
        if image.mode != "RGB":
            image = image.convert("RGB")
    except Exception as e:
        logger.error("[extract_body_shape] image decode error: %s", e)
        raise HTTPException(status_code=400, detail=f"画像デコード失敗: {e}")

    try:
        pose_extractor = importlib.import_module("16_pose_extractor")
    except Exception as e:
        logger.error("[extract_body_shape] import 16_pose_extractor failed: %s", e)
        raise HTTPException(status_code=500, detail=f"DWPose モジュール読込失敗: {e}")

    try:
        result = pose_extractor.extract_body_shape_from_image(image)
    except Exception as e:
        logger.error("[extract_body_shape] inference error: %s", e)
        raise HTTPException(status_code=500, detail=f"推論エラー: {e}")

    elapsed = time.time() - start_time

    if "dwpose_unavailable" in result.errors:
        raise HTTPException(
            status_code=500,
            detail="DWPose が利用できません。controlnet_aux をインストールしてください。",
        )
    if "invalid_image" in result.errors:
        raise HTTPException(status_code=400, detail="画像が小さすぎます")
    if "person_not_detected" in result.errors:
        raise HTTPException(
            status_code=422,
            detail="人物が検出できませんでした。全身が写った画像をご使用ください。",
        )
    if "insufficient_keypoints" in result.errors:
        raise HTTPException(
            status_code=422,
            detail=(
                f"検出された keypoints が不足しています ({result.keypoints_count} 点)。"
                "全身が写った画像をご使用ください。"
            ),
        )
    if "pose_runtime_error" in result.errors:
        raise HTTPException(status_code=500, detail="姿勢推論に失敗しました")

    if "low_confidence" in result.warnings:
        logger.warning("[extract_body_shape] low confidence: %.2f", result.confidence)

    body_shape = BodyShape(
        base=BodyShapeAxis(**result.body_shape["base"]),
        proportion=BodyShapeAxis(**result.body_shape["proportion"]),
        silhouette=BodyShapeAxis(**result.body_shape["silhouette"]),
        curves=BodyShapeAxis(**result.body_shape["curves"]),
        posture=BodyShapeAxis(**result.body_shape["posture"]),
    )

    logger.info(
        "[extract_body_shape] done %.2fs keypoints=%d confidence=%.2f",
        elapsed,
        result.keypoints_count,
        result.confidence,
    )
    return ExtractBodyShapeResponse(body_shape=body_shape, confidence=result.confidence)


@app.post("/api/portrait/apply_makeup")
async def apply_makeup(req: ApplyMakeupRequest) -> ApplyMakeupResponse:
    """
    メイクパレット本実装: 顔マスク + FLUX.1-Fill (pipeline_manager.ensure_fill_pipeline)。
    マスク失敗時は仕様どおり元画像を返し meta.warnings に記録。
    """
    t0 = time.time()
    if req.makeup_style not in _MAKEUP_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown makeup style: {req.makeup_style}")
    if req.intensity not in _INTENSITY_DENOISING:
        raise HTTPException(status_code=400, detail=f"Unknown intensity: {req.intensity}")

    try:
        img_data = req.base_image
        if img_data.startswith("data:"):
            img_data = img_data.split(",", 1)[1]
        raw = base64.b64decode(img_data)
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        logger.error("[apply_makeup] image decode error: %s", e)
        raise HTTPException(status_code=400, detail=f"画像デコード失敗: {e}")

    if _pipeline_manager_ref is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Pipeline manager not attached. "
                "Colab で orchestrator + pipeline を attach した起動セルを実行してください。"
            ),
        )

    loop = asyncio.get_running_loop()
    mask_mod = importlib.import_module("10_mask_engine")
    face_mask = await loop.run_in_executor(None, mask_mod.generate_face_mask_simple, image)

    denoise_val = _INTENSITY_DENOISING[req.intensity]

    if face_mask is None:
        logger.warning("[apply_makeup] face mask failed — fallback original image")
        return ApplyMakeupResponse(
            image=req.base_image,
            meta={
                "makeup_style": req.makeup_style,
                "intensity": req.intensity,
                "denoising": denoise_val,
                "elapsed_sec": time.time() - t0,
                "warnings": ["face_mask_failed"],
                "note": "fallback_original_image_no_fill",
            },
        )

    makeup_mod = importlib.import_module("15_makeup_engine")

    def _run_fill():
        return makeup_mod.apply_makeup_with_pipeline_manager(
            _pipeline_manager_ref,
            image,
            face_mask,
            req.makeup_style,
            req.intensity,
            None,
        )

    result = await loop.run_in_executor(None, _run_fill)

    if not result.success:
        err = (result.error or "").lower()
        if "fill_pipeline_not_initialized" in err:
            raise HTTPException(
                status_code=500,
                detail="Fill パイプライン未初期化。Colab を再起動するかパイプライン構築を確認してください。",
            )
        if "oom" in err:
            raise HTTPException(
                status_code=503,
                detail="VRAM 不足。しばらく待ってから再試行してください。",
            )
        if "unknown_makeup_type" in err:
            raise HTTPException(status_code=400, detail=result.error or "Unknown makeup type")
        if "unknown_intensity" in err:
            raise HTTPException(status_code=400, detail=result.error or "Unknown intensity")
        raise HTTPException(status_code=500, detail=f"メイク適用失敗: {result.error}")

    if result.image is None:
        raise HTTPException(status_code=500, detail="メイク結果画像が空です")

    out_b64 = pil_to_b64(result.image, fmt="PNG")
    elapsed = time.time() - t0
    logger.info(
        "[apply_makeup] done %.2fs style=%s intensity=%s denoising=%.3f",
        elapsed,
        req.makeup_style,
        req.intensity,
        result.denoising,
    )
    return ApplyMakeupResponse(
        image=out_b64,
        meta={
            "makeup_style": req.makeup_style,
            "intensity": req.intensity,
            "denoising": result.denoising,
            "elapsed_sec": elapsed,
            "makeup_infer_sec": result.elapsed,
            "note": "flux_fill_applied",
        },
    )


@app.get("/api/portrait/result/{job_id}")
async def portrait_result(job_id: str):
    job = _jobs.get(job_id)
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Job not completed (status={job.status})",
        )
    return {
        "job_id": job_id,
        "image": job.result_image_b64,
        "meta": job.result_meta,
    }


@app.post("/api/portrait/neutralize")
async def portrait_neutralize(req: NeutralizeRequest) -> NeutralizeResponse:
    """素体化: 白スタジオ・立ちポーズ・白セパレート水着 + PuLID + 体型プロンプト"""
    if _orchestrator_ref is None:
        raise HTTPException(
            status_code=503,
            detail="Orchestrator not attached. Call attach_orchestrator() before neutralize.",
        )
    if not req.face_refs:
        raise HTTPException(status_code=400, detail="face_refs が空です")

    t0 = time.time()
    try:
        face_pil_list = [b64_to_pil(b64) for b64 in req.face_refs if b64]
    except Exception as e:
        logger.error("[neutralize] face_refs decode: %s", e)
        raise HTTPException(status_code=400, detail=f"face_refs デコード失敗: {e}") from e

    if not face_pil_list:
        raise HTTPException(status_code=400, detail="有効な顔画像がありません")

    body_dict = req.body_shape.model_dump() if req.body_shape else None

    try:
        ne = importlib.import_module("17_neutralize_engine")
    except Exception as e:
        logger.error("[neutralize] import 17_neutralize_engine: %s", e)
        raise HTTPException(status_code=500, detail=f"NeutralizeEngine 読込失敗: {e}") from e

    loop = asyncio.get_running_loop()

    def _run_sync():
        return ne.neutralize_image_with_pipeline_manager(
            _orchestrator_ref,
            face_pil_list,
            body_dict,
            req.seed,
        )

    result = await loop.run_in_executor(None, _run_sync)

    if not result.success:
        err = result.error or ""
        if "oom" in err.lower():
            raise HTTPException(status_code=503, detail="VRAM 不足です")
        if "no_face_refs" in err:
            raise HTTPException(status_code=400, detail="顔参照画像がありません")
        raise HTTPException(status_code=500, detail=f"素体化失敗: {err}")

    if result.image is None:
        raise HTTPException(status_code=500, detail="素体化結果画像が空です")

    img_b64 = pil_to_b64(result.image, fmt="PNG")
    elapsed_wall = time.time() - t0
    logger.info(
        "[neutralize] ok %.2fs seed=%s addendum=%s",
        elapsed_wall,
        result.seed_used,
        result.body_shape_addendum[:80] if result.body_shape_addendum else "",
    )
    return NeutralizeResponse(
        image=img_b64,
        body_shape_addendum=result.body_shape_addendum,
        seed_used=result.seed_used,
        elapsed=elapsed_wall,
        meta={
            "neutralize_infer_sec": result.elapsed,
            "note": "pulid_neutralize_v8",
        },
    )


@app.post("/api/upload/image")
async def upload_image(file: UploadFile = File(...)):
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    thumb = img.copy()
    thumb.thumbnail((512, 512))
    return {
        "filename": file.filename,
        "thumbnail_b64": pil_to_b64(thumb),
        "full_b64": pil_to_b64(img),
        "size": [img.width, img.height],
    }


@app.get("/api/library")
async def library_list():
    return {"items": _LIBRARY_MOCK}


@app.post("/api/library/save")
async def library_save(req: LibrarySaveRequest):
    """v8.0 mock: 完了済みジョブ (PORTRAIT quick 等) の ID を neutral_job_id に渡して保存テスト可。"""
    job = _jobs.get(req.neutral_job_id)
    if job.status != "completed" or not job.result_image_b64:
        raise HTTPException(status_code=409, detail="Job not completed or no image")

    item = {
        "id": str(uuid.uuid4()),
        "name": req.name,
        "memo": req.memo,
        "tags": req.tags,
        "thumbnail_b64": job.result_image_b64,
        "created_at": time.time(),
    }
    _LIBRARY_MOCK.append(item)
    if len(_LIBRARY_MOCK) > 3:
        _LIBRARY_MOCK.pop(0)

    return {"saved": item, "capacity": f"{len(_LIBRARY_MOCK)}/3 (Free mock)"}


# ============================================================
# Diagnostic endpoints
# ============================================================


@app.get("/api/diagnostics/last_error")
async def diagnostics_last_error():
    try:
        from error_reporter import get_latest_error
        error = get_latest_error()
        if not error:
            return {"status": "no_errors"}
        return error
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/diagnostics/recent_errors")
async def diagnostics_recent_errors(limit: int = 10):
    try:
        from error_reporter import list_recent_errors
        return {"errors": list_recent_errors(limit=min(limit, 20))}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/diagnostics/system")
async def diagnostics_system():
    try:
        from error_reporter import _get_system_state, _get_aibo_config
        return {"system": _get_system_state(), "config": _get_aibo_config()}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def run_server(host: str = "0.0.0.0", port: int = 8000, log_level: str = "info") -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    run_server()
