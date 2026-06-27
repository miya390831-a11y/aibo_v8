"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 5 · Character Orchestrator
================================================================================

📌 ファイル名: 05_orchestrator.py

📌 このファイルの責務:
    1. CharacterOrchestrator: Pipeline + Identity + Asset を束ねて 1 枚生成
       - Phase 0: 顔参照画像のタイトクロップ (Phase0Sniper)
       - Phase 1: txt2img (Pass 1) · PuLID + IP-Adapter + ControlNet 注入
       - Phase 2: 顔リファイン (Pass 2 · Img2Img)
       - Phase 3: アップスケール (オプション)
       - Phase 4: 後始末 (Identity detach + VRAM 解放 + 自動保存)
    2. ModeManager: 3 モード (Portrait/Coordinate/Situation) のデフォルト適用
    3. Phase0Sniper: YOLO 顔検出 → タイトクロップ (ベレー帽幻覚抑止)
    4. GenerationResult: 戻り値データクラス + 自動保存

依存:
    - 01_config.py
    - 03_identity_engine.py (IdentityEngine, PuLIDExtractor)
    - 04_pipeline_manager.py (FluxA100PipelineManager, AssetManager)
    - torch / diffusers / PIL / ultralytics

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch
from PIL import Image

# ─── 01_config から型を import ───
_cfg_mod = import_module("01_config")
SystemConfig     = _cfg_mod.SystemConfig
GenerationConfig = _cfg_mod.GenerationConfig
IdentityConfig   = _cfg_mod.IdentityConfig
ModeConfig       = _cfg_mod.ModeConfig
StudioMode       = _cfg_mod.StudioMode
logger           = _cfg_mod.logger

# ─── 03_identity_engine ───
_id_mod = import_module("03_identity_engine")
IdentityEngine = _id_mod.IdentityEngine

# ─── 04_pipeline_manager ───
_pm_mod = import_module("04_pipeline_manager")
FluxA100PipelineManager = _pm_mod.FluxA100PipelineManager
AssetManager            = _pm_mod.AssetManager
_flush_vram             = _pm_mod._flush_vram


# ============================================================================
# 🎯 Section 5.1 · Phase0Sniper (YOLO 顔タイトクロップ)
# ============================================================================

class Phase0Sniper:
    """
    顔参照画像のタイトクロップ。

    v6 知見:
        EVA-CLIP が背景・髪・装飾品 (帽子等) を「ID の一部」として誤認すると
        FLUX が「スナップ写真っぽいアイテム (ベレー帽など)」を幻覚生成する。

        対策:
            YOLO で顔を検出し、40% マージンの正方形でタイトクロップ。
            「Phase 0 SNIPER 純度 100% 抽出」と呼ぶ。

    使い方:
        sniper = Phase0Sniper(sys_cfg)
        sniper.lazy_init()
        cropped = sniper.snipe(face_image)  # PIL Image · 失敗時は元画像
    """

    YOLO_MODEL_PATH = Path("/content/yolov8n-face.pt")
    # akanametov/yolov8-face は 404 化したため、HuggingFace 経由に変更
    YOLO_DOWNLOAD_URL = (
        "https://huggingface.co/arnabdhar/YOLOv8-Face-Detection/"
        "resolve/main/model.pt"
    )

    def __init__(self, sys_cfg: SystemConfig, *, margin_ratio: float = 0.4):
        self.sys_cfg = sys_cfg
        self.margin_ratio = margin_ratio
        self._detector = None
        self._initialized = False

    def lazy_init(self) -> bool:
        """YOLO モデルの DL + ロード"""
        if self._initialized:
            return True

        try:
            from ultralytics import YOLO
        except ImportError as e:
            logger.warning(f"⚠️ [Phase0Sniper] ultralytics 未インストール: {e}")
            logger.warning("   pip install ultralytics で導入できます · タイトクロップは skip")
            return False

        # モデル DL
        if not self.YOLO_MODEL_PATH.exists():
            logger.info(f"📥 [Phase0Sniper] YOLOv8-face モデル DL: {self.YOLO_DOWNLOAD_URL}")
            try:
                import urllib.request
                urllib.request.urlretrieve(
                    self.YOLO_DOWNLOAD_URL,
                    str(self.YOLO_MODEL_PATH),
                )
            except Exception as e:
                logger.warning(f"⚠️ [Phase0Sniper] DL 失敗: {e}")
                return False

        try:
            self._detector = YOLO(str(self.YOLO_MODEL_PATH))
            self._initialized = True
            logger.info("✅ [Phase0Sniper] YOLOv8-face ロード完了")
            return True
        except Exception as e:
            logger.warning(f"⚠️ [Phase0Sniper] ロード失敗: {e}")
            return False

    @torch.no_grad()
    def snipe(self, face_image: Image.Image) -> Image.Image:
        """
        顔をタイトクロップ。

        Returns:
            クロップ済 PIL Image · 失敗時は元画像をそのまま返す
        """
        if not self.lazy_init():
            return face_image

        try:
            img_np_rgb = np.array(face_image.convert("RGB"))
            results = self._detector(img_np_rgb, verbose=False)

            boxes = []
            for r in results:
                if r.boxes is not None:
                    for b in r.boxes.xyxy.cpu().numpy():
                        boxes.append(b[:4].tolist())

            if not boxes:
                logger.info("ℹ️ [Phase0Sniper] 顔未検出 · 元画像をそのまま使用")
                return face_image

            # 最大の顔領域を採用
            x1, y1, x2, y2 = map(
                int,
                max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            )
            fw, fh = x2 - x1, y2 - y1

            margin = int(max(fw, fh) * self.margin_ratio)
            cx, cy = x1 + fw // 2, y1 + fh // 2
            crop_size = max(fw, fh) + margin * 2

            nx1 = max(0, cx - crop_size // 2)
            ny1 = max(0, cy - crop_size // 2)
            nx2 = min(face_image.width, cx + crop_size // 2)
            ny2 = min(face_image.height, cy + crop_size // 2)

            cropped = face_image.crop((nx1, ny1, nx2, ny2))
            logger.info(
                f"🎯 [Phase0Sniper] タイトクロップ完了: "
                f"{cropped.width}×{cropped.height} (margin={int(self.margin_ratio*100)}%)"
            )
            return cropped

        except Exception as e:
            logger.warning(f"⚠️ [Phase0Sniper] クロップ失敗 (元画像で続行): {e}")
            return face_image


# ============================================================================
# 🎨 Section 5.2 · ModeManager (3 モード切替)
# ============================================================================

class ModeManager:
    """
    3 モード (Portrait / Coordinate / Situation) のデフォルト適用。

    UI からは StudioMode enum を受け取り、対応する prompt/aspect/controlnet を
    GenerationConfig + IdentityConfig に「事前充填」する。
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg

    def apply(
        self,
        mode: StudioMode,
        gen_cfg: GenerationConfig,
        id_cfg: IdentityConfig,
    ) -> tuple[GenerationConfig, IdentityConfig, ModeConfig]:
        """
        モードに応じてデフォルト値を補完。

        ⚠️ ユーザが明示的に設定した値 (空でない prompt 等) は上書きしない。
        """
        mode_cfg = ModeConfig.get(mode)

        # ─── prompt が空ならデフォルト適用 ───
        if not gen_cfg.prompt or gen_cfg.prompt.strip() == "":
            gen_cfg.prompt = mode_cfg.default_prompt

        if not gen_cfg.negative_prompt or gen_cfg.negative_prompt.strip() == "":
            gen_cfg.negative_prompt = mode_cfg.default_negative

        # ─── aspect ratio (width/height が 1024×1024 のままなら mode 値) ───
        if gen_cfg.width == 1024 and gen_cfg.height == 1024:
            w, h = mode_cfg.aspect_ratio
            gen_cfg.width = w
            gen_cfg.height = h

        # ─── controlnet_type のデフォルト ───
        if not id_cfg.controlnet_type or id_cfg.controlnet_type == "pose":
            # "pose" は IdentityConfig のデフォルト · ModeConfig 側を優先
            id_cfg.controlnet_type = mode_cfg.default_controlnet_type

        # 🎭 v7.2.2 Patch C Stage 1.5: Multi-CN 既定値を id_cfg に反映
        # IdentityConfig() の工場出荷デフォルトと同じ値のときだけ上書き
        # (= ユーザーがフィールドを変えたなら尊重)
        _id_cfg_default = type(id_cfg)()
        if id_cfg.enable_multi_cn == _id_cfg_default.enable_multi_cn:
            id_cfg.enable_multi_cn = mode_cfg.default_enable_multi_cn
        if id_cfg.cn_use_pose == _id_cfg_default.cn_use_pose:
            id_cfg.cn_use_pose = mode_cfg.default_cn_use_pose
        if id_cfg.cn_use_depth == _id_cfg_default.cn_use_depth:
            id_cfg.cn_use_depth = mode_cfg.default_cn_use_depth

        return gen_cfg, id_cfg, mode_cfg


# ============================================================================
# 📊 Section 5.3 · GenerationResult
# ============================================================================

@dataclass
class GenerationResult:
    """1 枚分の生成結果データ"""

    final_image: Optional[Image.Image] = None
    pass1_image: Optional[Image.Image] = None
    pass2_image: Optional[Image.Image] = None
    upscaled_image: Optional[Image.Image] = None

    # メタデータ
    seed: int = -1
    mode: str = ""
    steps_pass1: int = 0
    steps_pass2: int = 0
    pulid_weight: float = 0.0
    ip_adapter_weight: float = 0.0
    controlnet_weight: float = 0.0
    pulid_used: bool = False
    pulid_degraded: bool = False   # 観測性(RECON-019): PuLID→素Flux 縮退の検出(挙動不変・ログ/フラグのみ)
    upscale_used: bool = False
    phase3_applied: bool = False
    phase3_bypass_triggered: bool = False
    phase3_bypass_reason: str = ""
    phase3_yaw_deg: float = 0.0
    phase3_elapsed_sec: float = 0.0
    pass1_retry_count: int = 0
    pass1_fail_reason: Optional[str] = None

    # 計測
    elapsed_total_sec: float = 0.0
    elapsed_pass1_sec: float = 0.0
    elapsed_pass2_sec: float = 0.0
    elapsed_upscale_sec: float = 0.0

    # 保存
    saved_path: Optional[Path] = None
    error: Optional[str] = None

    def to_metadata_dict(self) -> dict:
        """JSON 保存用 (画像フィールドは除外)"""
        d = {
            "seed": self.seed,
            "mode": self.mode,
            "steps_pass1": self.steps_pass1,
            "steps_pass2": self.steps_pass2,
            "pulid_weight": self.pulid_weight,
            "ip_adapter_weight": self.ip_adapter_weight,
            "controlnet_weight": self.controlnet_weight,
            "pulid_used": self.pulid_used,
            "pulid_degraded": self.pulid_degraded,
            "upscale_used": self.upscale_used,
            "phase3_applied": self.phase3_applied,
            "phase3_bypass_triggered": self.phase3_bypass_triggered,
            "phase3_bypass_reason": self.phase3_bypass_reason,
            "phase3_yaw_deg": self.phase3_yaw_deg,
            "phase3_elapsed_sec": round(self.phase3_elapsed_sec, 2),
            "elapsed_total_sec": round(self.elapsed_total_sec, 2),
            "elapsed_pass1_sec": round(self.elapsed_pass1_sec, 2),
            "elapsed_pass2_sec": round(self.elapsed_pass2_sec, 2),
            "elapsed_upscale_sec": round(self.elapsed_upscale_sec, 2),
            "saved_path": str(self.saved_path) if self.saved_path else None,
            "error": self.error,
            "pass1_retry_count": self.pass1_retry_count,
            "pass1_fail_reason": self.pass1_fail_reason,
        }
        return d


# ============================================================================
# 🎬 Section 5.4 · CharacterOrchestrator (司令塔)
# ============================================================================

class CharacterOrchestrator:
    """
    1 枚の画像生成を統括する司令塔。

    生成フロー:
        Phase 0: Phase0Sniper で顔参照画像をタイトクロップ
        Phase 1: txt2img (Pass 1) · IdentityEngine で PuLID/IP-Adapter/ControlNet 注入
        Phase 2: 顔 crop + リファイン + 合成 (Pass 2)
        Phase 3: UpscalerHub でアップスケール (オプション)
        Phase 4: detach + 自動保存 + メモリ解放

    使い方:
        orch = CharacterOrchestrator(sys_cfg, pipeline_mgr, identity_engine, asset_mgr)
        result = orch.generate(gen_cfg, id_cfg, mode=StudioMode.PORTRAIT)
        if result.final_image:
            display(result.final_image)
    """

    def __init__(
        self,
        sys_cfg: SystemConfig,
        pipeline_mgr: FluxA100PipelineManager,
        identity_engine: IdentityEngine,
        asset_mgr: AssetManager,
    ):
        self.sys_cfg = sys_cfg
        self.pm = pipeline_mgr
        self.ie = identity_engine
        self.am = asset_mgr
        self.strategy = sys_cfg.resolve_strategy()
        self._current_id_cfg: Optional[IdentityConfig] = None

        self.mode_manager = ModeManager(sys_cfg)
        self.sniper = Phase0Sniper(sys_cfg)
        # v7.2.1: Face Refiner (v6 移植版 Pass 2)
        try:
            _refiner_mod = import_module("08_face_refiner")
            self.face_refiner = _refiner_mod.FaceRefiner(sys_cfg, pipeline_mgr)
            logger.info("✅ [Orchestrator] FaceRefiner 初期化")
        except Exception as e:
            logger.warning(f"⚠️ [Orchestrator] FaceRefiner 初期化失敗: {e}")
            self.face_refiner = None

        # v8.0 Week 2-3: Phase 3 ハイブリッド γ
        self.face_restore_engine = None
        try:
            fr_mod = import_module("08_face_refiner")
            cfg_mod = import_module("01_config")
            self.face_restore_engine = fr_mod.FaceRestoreEngine(
                pipeline_manager=self.pm,
                sys_cfg=self.sys_cfg,
                gfpgan_strength=getattr(cfg_mod, "GFPGAN_STRENGTH", 0.35),
                gfpgan_blend=getattr(cfg_mod, "GFPGAN_BLEND", 1.0),  # 立体感 Step1: 既定 1.0=後退ゼロ
                fill_denoising=getattr(cfg_mod, "FILL_DENOISING", 0.25),
                angle_bypass_yaw_deg=getattr(cfg_mod, "ANGLE_BYPASS_YAW_DEG", 35.0),
                face_mask_feather_px=getattr(cfg_mod, "FACE_MASK_FEATHER_PX", 21),
                face_mask_margin_ratio=getattr(cfg_mod, "FACE_MASK_MARGIN_RATIO", 0.20),
            )
            logger.info("✅ [Orchestrator] FaceRestoreEngine 初期化")
        except Exception as e:
            logger.warning(f"⚠️ [Orchestrator] FaceRestoreEngine 初期化失敗: {e}")

        # 自動保存先
        self.save_dir = sys_cfg.output_dir / "generated"
        self.save_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("🎬 CharacterOrchestrator 初期化完了")
        logger.info(f"   save_dir: {self.save_dir}")
        logger.info("=" * 60)

    # ─────────────────────────────────────────────────
    # 公開 API: generate
    # ─────────────────────────────────────────────────

    @torch.no_grad()
    def generate(
        self,
        gen_cfg: GenerationConfig,
        id_cfg: IdentityConfig,
        mode: StudioMode = StudioMode.PORTRAIT,
        *,
        save: bool = True,
    ) -> GenerationResult:
        """
        1 枚の画像を生成。

        Args:
            gen_cfg: 生成パラメータ (prompt/steps/cfg/seed 等)
            id_cfg: Identity 設定 (reference_image/pulid_weight 等)
            mode: 3 モードのいずれか
            save: True なら自動保存

        Returns:
            GenerationResult (final_image + Pass1/Pass2/upscale + メタデータ)
        """

        # 起動チェック
        if not self.pm.is_ready():
            logger.error("❌ [Orchestrator] PipelineManager が build されていない")
            return GenerationResult(error="PipelineManager not built")

        result = GenerationResult(mode=mode.value)
        t0_total = time.perf_counter()

        try:
            # ─── 0. モード適用 ───
            gen_cfg, id_cfg, mode_cfg = self.mode_manager.apply(mode, gen_cfg, id_cfg)
            logger.info("=" * 60)
            logger.info(f"🎬 GENERATION START · mode={mode.value}")
            logger.info(f"   prompt: {gen_cfg.prompt[:80]}")
            logger.info(
                f"   {gen_cfg.width}×{gen_cfg.height} · "
                f"steps={gen_cfg.resolved_steps(self.strategy, hyper_flux_enabled=self.sys_cfg.enable_hyper_flux)}"
            )
            logger.info(f"[OBS-B] enable_hyper_flux={self.sys_cfg.enable_hyper_flux} / _hyper_flux_loaded={getattr(self.pm, '_hyper_flux_loaded', None)} / steps={gen_cfg.resolved_steps(self.strategy, hyper_flux_enabled=self.sys_cfg.enable_hyper_flux)}")
            logger.info("=" * 60)

            # ─── Phase 2 v2 NEW: ACE++ LoRA 動的 scale 切替 (2026-05-06) ──
            # StudioMode に応じて Portrait / Subject の scale を切替
            # Stage 1 (PORTRAIT): Portrait active, Subject inactive
            # Stage 2 (COORDINATE 他): Portrait inactive, Subject active
            if hasattr(self.pm, "switch_ace_plus_lora_for_stage"):
                stage_str = "PORTRAIT" if mode == StudioMode.PORTRAIT else "COORDINATE"

                # Portrait weight は ace_plus_weight (Phase 1 の 0.6)
                portrait_w = getattr(id_cfg, "ace_plus_weight", 0.6)

                # Subject weight は ace_plus_subject_weight (新設)
                subject_w = getattr(id_cfg, "ace_plus_subject_weight", 0.6)

                # Subject の有効性チェック
                if not getattr(id_cfg, "enable_ace_plus_subject", True):
                    subject_w = 0.0

                self.pm.switch_ace_plus_lora_for_stage(
                    stage_mode=stage_str,
                    portrait_weight=portrait_w,
                    subject_weight=subject_w,
                )

            # ★ Patch C Stage 3c NEW: id_cfg を保存 (Pass 1 CN で参照するため)
            self._current_id_cfg = id_cfg

            # ─── 1. seed 確定 ───
            if gen_cfg.seed < 0:
                seed = int(torch.randint(0, 2**31 - 1, (1,)).item())
            else:
                seed = gen_cfg.seed
            result.seed = seed

            # ─── 2. Phase 0: 顔参照のタイトクロップ ───
            sniped_image = None
            sniped_images = None
            if id_cfg.reference_images and len(id_cfg.reference_images) > 0:
                sniped_images = []
                for idx, ref_img in enumerate(id_cfg.reference_images):
                    if ref_img is None:
                        continue
                    sniped_images.append(self.sniper.snipe(ref_img))
                    logger.info(
                        f"[Orchestrator] multi reference snipe {idx + 1}/{len(id_cfg.reference_images)} 完了"
                    )

                id_cfg_for_extraction = IdentityConfig(**asdict(id_cfg))
                id_cfg_for_extraction.reference_images = sniped_images
                if sniped_images:
                    id_cfg_for_extraction.reference_image = sniped_images[0]
                logger.info(f"[Orchestrator] 多枚 ID パス選択 ({len(sniped_images)} 枚)")
            elif id_cfg.reference_image is not None:
                sniped_image = self.sniper.snipe(id_cfg.reference_image)
                # IdentityConfig を破壊しないようコピー
                id_cfg_for_extraction = IdentityConfig(**asdict(id_cfg))
                id_cfg_for_extraction.reference_image = sniped_image
            else:
                id_cfg_for_extraction = id_cfg

            # ─── 観測リセット (IMPL-005 · RECON-006c 案1) ───
            # 共有 extractor に残る前回痕跡を生成の頭で消す。手動 extract の成功が
            # UI 生成の失敗痕跡を上書きする順序汚染を断ち、[OBS-SUMMARY] が
            # その生成の真値だけを反映するようにする(観測性のみ・核非接触)。
            _ext_reset = getattr(self.ie, "pulid_extractor", None)
            if _ext_reset is not None:
                _ext_reset._last_extract_error = None
                _ext_reset._last_face_count = None

            # ─── 3. Identity データ準備 ───
            identity_data = self.ie.prepare(id_cfg_for_extraction)

            # ─── 原画リトライ (IMPL-007 · RECON-006 本命A) ───
            # snipe 後画像で顔未検出(id_embeds 無)の時、snipe 前の余白あり原画像で
            # 1回だけ再 prepare。UI のドアップ + snipe 二重クロップで顔が画面いっぱいになり
            # antelopev2(SCRFD)がマージン不足で未検出になる事故への保険(UI/API 両方を守る)。
            # PuLID 核・prepare/extract のロジックは不変。どの画像で呼ぶかだけを変える。
            if "id_embeds" not in identity_data and id_cfg.reference_image is not None:
                logger.warning("[IMPL-007] extract が None。snipe 前の原画像でリトライします")
                id_cfg_retry = IdentityConfig(**asdict(id_cfg))   # 既存のコピー作法(487/495)を踏襲
                id_cfg_retry.reference_image = id_cfg.reference_image   # snipe していない原画(余白あり)
                identity_data_retry = self.ie.prepare(id_cfg_retry)
                if "id_embeds" in identity_data_retry:
                    identity_data = identity_data_retry
                    logger.info("[IMPL-007] ✅ 原画リトライで id_embeds 取得成功")
                else:
                    logger.warning("[IMPL-007] 原画リトライでも顔未検出。PuLID 無しで継続")

            result.pulid_used = "id_embeds" in identity_data
            result.pulid_weight = identity_data.get("pulid_weight", 0.0)
            result.ip_adapter_weight = identity_data.get("ip_weight", 0.0)
            result.controlnet_weight = identity_data.get("controlnet_weight", 0.0)

            # ─── 4. Identity を pipeline に注入 ───
            if identity_data:
                self.ie.attach_to_pipeline(self.pm.pipe_base, identity_data)
                # ─── Phase 2 v2 NEW: post-attach wrap 再設置 (2026-05-06) ──
                # binder.bind_forward が attach 内で forward を pulid_forward に
                # 上書きするため、auto_pulid_forward を強制再設置する。
                # これがないと IP-Adapter (Stage 4-D-2) 注入経路が死亡する。
                if hasattr(self.pm, "_wrap_transformer_forward_for_cn"):
                    self.pm._wrap_transformer_forward_for_cn(force_reset=True)
                    logger.info("🔧 [Phase 2 v2] post-attach wrap 再設置完了")

            logger.info(f"[OBS-C] pulid_used={result.pulid_used} / id_embeds={'有' if 'id_embeds' in identity_data else '無'} / faces_detected={getattr(getattr(self.ie, 'pulid_extractor', None), '_last_face_count', 'n/a')}")

            # ─── 動的 VAE tiling ガード(Step1.6 / RECON-020・必須A)───
            #   フラグ VAE_TILING_GUARD=True 時のみ・env 明示が無い時だけ、解像度で自動切替:
            #   max(W,H) > 1536 → ON(whole-frame decode の OOM 回避)/ ≤1536 → OFF(高周波=立体感)。
            #   素朴グローバル False フリップは共有 VAE + 最大2048 で OOM(本番500)→ 禁止(RECON-020 §4)。
            #   env を書かない _apply_vae_tiling_live で live vae 直叩き(env 明示 > 自動 を保つ)。
            _cfgm = import_module("01_config")
            if getattr(_cfgm, "VAE_TILING_GUARD", False):
                if os.environ.get("AIBO_VAE_TILING") is None:
                    _pmm = import_module("04_pipeline_manager")
                    _long = max(int(gen_cfg.width), int(gen_cfg.height))
                    _tiling_on = _long > 1536
                    _applied = _pmm._apply_vae_tiling_live(_tiling_on)
                    logger.info(
                        f"[VAE][guard] long={_long} → tiling="
                        f"{'ON(>1536·OOM回避)' if _tiling_on else 'OFF(≤1536·品質)'} "
                        f"(live反映={_applied})"
                    )
                else:
                    logger.info("[VAE][guard] env AIBO_VAE_TILING 明示あり → 自動ガード skip(明示優先)")

            # ─── 5. Pass 1: txt2img ───
            t0_p1 = time.perf_counter()
            use_cn = id_cfg.enable_multi_cn and (id_cfg.cn_use_pose or id_cfg.cn_use_depth)
            max_retries = 2
            last_error_msg = ""
            pass1 = None
            for attempt in range(1 + max_retries):
                attempt_seed = seed if attempt == 0 else int(torch.randint(0, 2**31 - 1, (1,)).item())
                try:
                    if use_cn:
                        if attempt == 0:
                            logger.info(f"🎭 [generate] Multi-CN 経路 (mode={mode.value})")
                        pass1 = self._run_pass1_with_cn(gen_cfg, identity_data, attempt_seed)
                    else:
                        if attempt == 0:
                            logger.info(f"🎭 [generate] PORTRAIT 経路 (mode={mode.value})")
                        pass1 = self._run_pass1(gen_cfg, identity_data, attempt_seed)
                    break
                except Exception as e:
                    last_error_msg = str(e)
                    result.pass1_retry_count = attempt + 1
                    if attempt < max_retries:
                        logger.warning(
                            "⚠️ [generate] Pass 1 失敗 (attempt %d/%d): %s · seed=%d でリトライ",
                            attempt + 1, 1 + max_retries, e, attempt_seed,
                        )
                        _flush_vram()
                        time.sleep(1)
                    else:
                        logger.error(
                            "❌ [generate] Pass 1 全リトライ失敗 (%d 回): %s",
                            1 + max_retries, e,
                        )
                        result.pass1_fail_reason = last_error_msg

            result.pass1_image = pass1
            result.steps_pass1 = gen_cfg.resolved_steps(
                self.strategy,
                hyper_flux_enabled=self.sys_cfg.enable_hyper_flux,
            )
            result.elapsed_pass1_sec = time.perf_counter() - t0_p1
            logger.info(f"⏱ Pass 1 完了: {result.elapsed_pass1_sec:.1f}s")

            # ─── 6. Pass 2: 顔リファイン (オプション) ───
            current_image = pass1
            if gen_cfg.enable_pass2 and pass1 is not None and self.pm.pipe_i2i is not None:
                t0_p2 = time.perf_counter()
                pass2 = self._run_pass2(pass1, gen_cfg, identity_data, seed + 1)
                if pass2 is not None:
                    result.pass2_image = pass2
                    current_image = pass2
                    result.steps_pass2 = max(8, int(result.steps_pass1 * gen_cfg.pass2_strength * 2))
                    result.elapsed_pass2_sec = time.perf_counter() - t0_p2
                    logger.info(f"⏱ Pass 2 完了: {result.elapsed_pass2_sec:.1f}s")

            # ─── 7. Phase 3: アップスケール (オプション) ───
            if gen_cfg.enable_upscale and current_image is not None:
                t0_up = time.perf_counter()
                upscaled = self.am.upscaler.upscale(
                    current_image,
                    method=gen_cfg.upscale_method,
                    scale=gen_cfg.upscale_factor,
                )
                if upscaled is not None and upscaled is not current_image:
                    result.upscaled_image = upscaled
                    result.upscale_used = True
                    current_image = upscaled
                    result.elapsed_upscale_sec = time.perf_counter() - t0_up
                    logger.info(f"⏱ Upscale 完了: {result.elapsed_upscale_sec:.1f}s")

            result.final_image = current_image
            if result.final_image is None:
                reason = result.pass1_fail_reason or "不明"
                result.error = f"Pass 1 が画像を生成できなかった (リトライ {result.pass1_retry_count} 回後も失敗: {reason})"
                logger.error("❌ [generate] final_image が None のまま終了 · %s", result.error)

            # ─── 7.5. Phase 3: ハイブリッド γ (オプション) ───
            cfg_mod = import_module("01_config")
            phase3_enabled = getattr(cfg_mod, "PHASE3_ENABLED", True)
            if (
                phase3_enabled
                and mode != StudioMode.COORDINATE
                and result.final_image is not None
                and self.face_restore_engine is not None
            ):
                logger.info("[Orchestrator] Phase 3 ハイブリッド γ 開始")
                try:
                    phase3_result = self.face_restore_engine.process(
                        image=result.final_image,
                        debug_keep_intermediates=False,
                    )
                    result.final_image = phase3_result.final_image
                    result.phase3_applied = True
                    result.phase3_bypass_triggered = phase3_result.bypass_triggered
                    result.phase3_bypass_reason = phase3_result.bypass_reason
                    result.phase3_yaw_deg = phase3_result.yaw_deg
                    result.phase3_elapsed_sec = phase3_result.elapsed_total_sec
                    logger.info(
                        f"[Orchestrator] Phase 3 完了: "
                        f"バイパス={phase3_result.bypass_triggered}, "
                        f"yaw={phase3_result.yaw_deg:.1f}°, "
                        f"時間={phase3_result.elapsed_total_sec:.2f}s"
                    )
                except Exception as e:
                    logger.error(f"[Orchestrator] Phase 3 例外 · 現在画像で続行: {e}")
                    result.phase3_applied = False
            else:
                result.phase3_applied = False
                if mode == StudioMode.COORDINATE:
                    logger.info("[Orchestrator] COORDINATE モード · Phase 3 スキップ (設計通り)")
                elif not phase3_enabled:
                    logger.info("[Orchestrator] PHASE3_ENABLED=False · Phase 3 スキップ")
                elif self.face_restore_engine is None:
                    logger.info("[Orchestrator] FaceRestoreEngine 未初期化 · Phase 3 スキップ")

            # ─── 8. 自動保存 ───
            if save and result.final_image is not None:
                result.saved_path = self._save_result(result)

        except Exception as e:
            logger.error(f"❌ [Orchestrator] 生成失敗: {e}")
            logger.error(traceback.format_exc())
            result.error = str(e)
        finally:
            # ─── 9. Phase 4: 後始末 ───
            try:
                self.ie.detach_from_pipeline(self.pm.pipe_base)
            except Exception as _detach_err:
                # RECON-019: 空ハンドラ(厳守違反)をやめ、何が落ちたかを観測可能に(挙動は不変)
                logger.warning(
                    f"⚠️ [Orchestrator] detach_from_pipeline 失敗(後始末・生成は完了済): "
                    f"{type(_detach_err).__name__}: {_detach_err}"
                )
            self._flush_vram()

            result.elapsed_total_sec = time.perf_counter() - t0_total
            logger.info(f"⏱ TOTAL: {result.elapsed_total_sec:.1f}s")

        # ─── OBS 自動サマリ (IMPL-004 · 点検くろうど段階1) ───
        # 生成のたびに観測値を1ブロック出力。show_obs() 手打ち不要・UI 生成でも見える。
        # 観測性のみ(核不変)。getattr ベースでこのブロック自身は生成を壊さない。
        _ext = getattr(self.ie, "pulid_extractor", None)
        _extract_err = getattr(_ext, "_last_extract_error", None)
        _init_err = getattr(_ext, "_last_init_error", None)
        _pipe_cls = (
            self.pm.status().get("pipe_base_class")
            if hasattr(self.pm, "status")
            else type(getattr(self.pm, "pipe_base", None)).__name__
        )
        logger.info("─" * 60)
        logger.info("[OBS-SUMMARY] 生成時 自動観測サマリ")
        logger.info(f"  pipe_base_class : {_pipe_cls}")
        # RECON-019: PuLID→素Flux 縮退(外国人化の再発口)を観測可能に(挙動は変えない)
        result.pulid_degraded = bool(getattr(self.pm, "_pulid_degraded", False))
        logger.info(
            f"  pulid_degraded  : "
            f"{'⚠️ True(素Flux縮退=外国人化の口)' if result.pulid_degraded else 'False'}"
        )
        logger.info(
            f"  hyper_flux      : enable={self.sys_cfg.enable_hyper_flux}"
            f" / loaded={getattr(self.pm, '_hyper_flux_loaded', None)}"
            f" / steps_pass1={result.steps_pass1}"
        )
        logger.info(f"  id_embeds       : {'有✅' if result.pulid_used else '無⚠️'}")
        if not result.pulid_used:
            # RECON-005 FIX-1: 「無」だけでなく「なぜ無か」を併記
            logger.info(f"    ↳ 失敗理由    : extract={_extract_err or 'なし'} / init={_init_err or 'なし'}")
        # RECON-005 FIX-2: faces_detected は single-ref では無意味 · 判断に使わせない
        logger.info(f"  faces_detected  : n/a(single-ref)")
        # ─── Step1-pre OBS②③: CN 経路 identity 診断(logging only · 挙動不変)─
        #   共有 transformer の注入カウンタ/属性を getattr で読むだけ(値は変えない)。
        #   経路は上の [OBS-ROUTE] 行を参照(最後の1行が実効経路)。
        #   注意: inject_count は forward ラッパーが「初回のみ」加算(最大1で頭打ち)。
        #         よって >0 = この実行(=直近の wrap 以降)で CN 自動注入が発火した、の意。
        _tf = getattr(self.pm, "_shared_transformer", None)
        _pulid_inject_n = getattr(_tf, "_auto_pulid_inject_count", 0)
        _ip_inject_n = getattr(_tf, "_auto_ip_inject_count", 0)
        _ip_embeds = getattr(_tf, "_pulid_ip_embeds", None)
        logger.info(
            f"  pulid_used(CN)  : inject_count={_pulid_inject_n} "
            f"({'発火✅' if _pulid_inject_n else '未発火⚠️'})"
        )
        logger.info(
            f"  ip_restored     : {_ip_embeds is not None} "
            f"(_pulid_ip_embeds={'有' if _ip_embeds is not None else 'None⚠️休眠'}"
            f" / ip_inject_count={_ip_inject_n})"
        )
        logger.info("─" * 60)

        return result

    # ─────────────────────────────────────────────────
    # Phase 1: txt2img
    # ─────────────────────────────────────────────────

    def _run_pass1(
        self,
        gen_cfg: GenerationConfig,
        identity_data: dict,
        seed: int,
    ) -> Optional[Image.Image]:
        """Pass 1 = メイン txt2img (PuLID 注入済み pipeline で生成)"""
        try:
            steps = gen_cfg.resolved_steps(
                self.strategy,
                hyper_flux_enabled=self.sys_cfg.enable_hyper_flux,
            )

            generator = torch.Generator(device=self.pm.device).manual_seed(seed)

            kwargs: dict[str, Any] = {
                "prompt": gen_cfg.prompt,
                "negative_prompt": gen_cfg.negative_prompt,
                "width": gen_cfg.width,
                "height": gen_cfg.height,
                "num_inference_steps": steps,
                "guidance_scale": gen_cfg.guidance_scale,
                "generator": generator,
                # ⚠️ PuLIDFluxPipeline が encoder_hid_proj を要求するエラー回避:
                #    IP-Adapter 系を明示的に None にする
                "ip_adapter_image": None,
                "ip_adapter_image_embeds": None,
                "negative_ip_adapter_image": None,
                "negative_ip_adapter_image_embeds": None,
            }

            # ─── PuLID (Nunchaku 公式 PuLIDFluxPipeline 経由) ───
            # PuLIDFluxPipeline の __call__ が id_image / id_weight を受ける
            # → identity_data に reference_image があれば直接渡す
            if "id_embeds" in identity_data:
                # reference_image は IdentityEngine.prepare 内で破棄されている可能性あり
                # → id_cfg のオリジナル参照を使うため、prepare 側で identity_data に
                #    reference_image を残すように合わせる必要あり
                ref_for_pulid = identity_data.get("reference_image")
                if ref_for_pulid is not None:
                    kwargs["id_image"] = ref_for_pulid
                    kwargs["id_weight"] = identity_data.get("pulid_weight", 1.0)
                    kwargs["start_step"] = 0
                    logger.info(
                        f"💉 [Pass 1] PuLID id_image 直接渡し "
                        f"(weight={kwargs['id_weight']})"
                    )

            # ─── IP-Adapter (画像参照) ───
            ip_weight = identity_data.get("ip_weight", 0.0)
            if "ip_image" in identity_data and self.ie.ip_adapter and ip_weight > 0:
                # IP-Adapter は load_ip_adapter() を呼んでから使う想定
                self.ie.ip_adapter.set_scale(self.pm.pipe_base, ip_weight)
                kwargs["ip_adapter_image"] = identity_data["ip_image"]

            # ─── ControlNet ───
            # ⚠️ FluxPipeline (素) は control_image を受け付けない。
            # ControlNet を使う場合は FluxControlNetPipeline を使う必要がある。
            # 現状 v7.2 では ControlNet 統合が未完成のため、weight > 0 でも skip。
            # v7.3 で FluxControlNetPipeline ベースに移行予定。
            ctrl_weight = identity_data.get("controlnet_weight", 0.0)
            if "controlnet_image" in identity_data and self.ie.controlnet and ctrl_weight > 0:
                logger.info(f"ℹ️ [Pass 1] ControlNet weight={ctrl_weight} 指定だが v7.2 では未統合 · skip")
                # TODO v7.3: FluxControlNetPipeline 経由で渡す
                # kwargs["control_image"] = identity_data["controlnet_image"]
                # kwargs["controlnet_mode"] = None
                # kwargs["controlnet_conditioning_scale"] = ctrl_weight

            # Step1-pre OBS①: 実効経路マーカー(logging only · 挙動不変)
            #   _run_pass1_with_cn からのフォールバック時もこの行が出るため、
            #   最後に出た [OBS-ROUTE] 行 = 実際に画像を生成した経路。
            logger.info("🧭 [OBS-ROUTE] 経路=_run_pass1 (plain pipe_base / CN未統合・CN-skip 枝)")
            logger.info(f"🚀 [Pass 1] generate (steps={steps}, seed={seed})")

            # 🥷 v7.2.1 Patch A.3: AIBO_FORCE_OFFLOAD=1 のときのみ GPU 復帰
            # 通常 (A100 40GB) は構築時から GPU 常駐なので何もしない
            if os.environ.get("AIBO_FORCE_OFFLOAD", "0") == "1":
                if self.sys_cfg.enable_pulid and hasattr(self.pm.pipe_base, "pulid_model"):
                    try:
                        self.pm.pipe_base.pulid_model.to(self.pm.device)
                    except Exception as e:
                        logger.info(f"  ℹ️ pulid_model GPU 復帰スキップ: {e}")

            # ─── OSS sigma 注入(portrait pass1・案①恒久化・EXP-033 確定)───
            # [DIAG] inject-point 到達証跡(logging only・生成非改変)。
            #   この行が本番ログに出ない = 実行中の 05 が OSS ブロック未搭載
            #   (04/05 desync・stale module)を意味する=GATE① ❌(OSS='None')の真因判定。
            #   hook_on_live_sched= は「これから叩く scheduler に wrap が乗ってるか」
            #   = 仮説(a) stale-wrap の即時判定材料。
            _sched_dbg = getattr(getattr(self.pm, "pipe_base", None), "scheduler", None)
            logger.info(
                f"🧩 [OSS] inject-point reached: route=_run_pass1 steps={steps} "
                f"hook_on_live_sched={getattr(_sched_dbg, '_oss_hook_installed', False)}"
            )
            _oss = None
            try:
                _pm04 = import_module("04_pipeline_manager")
                _oss = _pm04.oss_sigmas(steps)
                self.pm._oss_force_sigmas = _oss
            except Exception as _e:
                logger.warning(f"[OSS] sigma 準備失敗・既定scheduleで続行: {_e}")
                self.pm._oss_force_sigmas = None
            try:
                output = self.pm.pipe_base(**kwargs)
            finally:
                self.pm._oss_force_sigmas = None   # pass1 専用に即時 disarm
            # 適用検証(軽量・常駐): 注入値 vs 実使用 scheduler.sigmas
            if _oss is not None:
                try:
                    _used = [float(x) for x in
                             self.pm.pipe_base.scheduler.sigmas.detach().float().cpu().tolist()][:-1]
                    if len(_used) == len(_oss):
                        _maxd = max(abs(a - b) for a, b in zip(_used, _oss))
                        (logger.info if _maxd < 1e-3 else logger.warning)(
                            f"[OSS] APPLIED n={len(_oss)} maxΔ={_maxd:.5f} "
                            f"{'✓' if _maxd < 1e-3 else '⚠️ FALLBACK/二重シフト疑い'}")
                    else:
                        logger.warning(f"[OSS] step 不一致 inj={len(_oss)} used={len(_used)} → 既定fallback疑い")
                except Exception as _e:
                    logger.warning(f"[OSS] 適用検証スキップ: {_e}")

            # 🥷 v7.2.1 Patch A.3: AIBO_FORCE_OFFLOAD=1 のときのみ CPU 退避
            if os.environ.get("AIBO_FORCE_OFFLOAD", "0") == "1":
                if self.sys_cfg.enable_pulid and hasattr(self.pm.pipe_base, "pulid_model"):
                    try:
                        self.pm.pipe_base.pulid_model.to(torch.device("cpu"))
                    except Exception:
                        pass
            _flush_vram()

            if hasattr(output, "images") and output.images:
                return output.images[0]
            msg = (
                f"pipeline 出力に画像なし (has_images={hasattr(output, 'images')}, "
                f"len={len(output.images) if hasattr(output, 'images') and output.images is not None else 'N/A'})"
            )
            logger.warning("⚠️ [Pass 1] %s", msg)
            raise RuntimeError(msg)

        except Exception as e:
            logger.error(f"❌ [Pass 1] 失敗: {e}")
            logger.error(traceback.format_exc())
            raise

    def _run_pass1_with_cn(
        self,
        gen_cfg: GenerationConfig,
        identity_data: dict,
        seed: int,
    ) -> Optional[Image.Image]:
        """
        Pass 1 with Multi-ControlNet (Stage 3 · アプローチ X)。
        Pose + Depth 制御 + PuLID 顔ロジックの統合パス。

        設計参照: docs/Patch_C_Stage_3_Implementation_Design_v2.md セクション 7

        使用シーン:
            - StudioMode.COORDINATE (服装提案 · 全身構図)
            - StudioMode.SITUATION (シーン埋め込み · 立体感)

        入力データ (identity_data):
            - id_embeds, pulid_ca, pulid_weight (PuLID 必須)
            - pose_image (Optional · prepare で抽出済 or 抽出失敗時 None)
            - depth_image (Optional · prepare で抽出済 or 抽出失敗時 None)

        フォールバック:
            - CN 画像なし → _run_pass1 にフォールバック
            - 推論例外 → _run_pass1 にフォールバック
        """
        try:
            # ─── 1. ControlNet パイプライン構築確認 ───────────────
            if not self.pm._controlnet_loaded:
                logger.info("🔧 [Pass 1 CN] ControlNet pipeline 初回構築...")
                self.pm.ensure_controlnet()

            # transformer.forward ラップ確認 (念のため)
            if not getattr(self.pm, "_cn_forward_wrapped", False):
                logger.warning("⚠️ [Pass 1 CN] forward ラップ未動作 · 手動ラップ実行")
                self.pm._wrap_transformer_forward_for_cn()

            # ─── 1.5 CN 専用 IP-Adapter 配線(初回 CN 生成で1回だけ・起動 eager を後ろ倒し)──
            #   旧 notebook Cell-run が起動時 eager にやっていた CN 専用 setup をここへ移植。
            #   portrait(_run_pass1 / pipe_base)経路は一切触らないため byte 不変。idempotent。
            pm = self.pm
            if pm.pipe_cnet is not None and not getattr(pm, "_cnet_ipadapter_wired", False):
                ipa = self.ie.ip_adapter            # identity_engine の IP-Adapter
                if getattr(pm.pipe_cnet, "image_encoder", None) is None and ipa is not None:
                    pm.pipe_cnet.image_encoder = ipa._image_encoder
                    pm.pipe_cnet.feature_extractor = ipa._feature_extractor
                # IP-Adapter scale を pipe_cnet にも(Setting A の ip_adapter_weight=IdentityConfig 既定)
                if ipa is not None:
                    ipa.set_scale(pm.pipe_cnet, IdentityConfig().ip_adapter_weight)
                pm._cnet_ipadapter_wired = True
                logger.info("🔧 [Pass 1 CN] pipe_cnet に CN 専用 IP-Adapter 配線完了(初回1回)")

            # ─── 2. CN 入力リスト構築 ─────────────────────────────
            id_cfg_local = self._current_id_cfg
            if id_cfg_local is None:
                logger.warning("⚠️ [Pass 1 CN] _current_id_cfg が None → 通常 _run_pass1 にフォールバック")
                return self._run_pass1(gen_cfg, identity_data, seed)

            control_images = []
            control_scales = []
            control_guidance_ends = []
            control_modes = []

            if id_cfg_local.cn_use_pose and "pose_image" in identity_data:
                control_images.append(identity_data["pose_image"])
                control_scales.append(id_cfg_local.cn_pose_weight)
                control_guidance_ends.append(id_cfg_local.cn_pose_guidance_end)
                control_modes.append(None)  # Pro 2.0 は mode 不要
                logger.info(
                    f"  🦴 Pose: scale={id_cfg_local.cn_pose_weight}, "
                    f"end={id_cfg_local.cn_pose_guidance_end}"
                )

            if id_cfg_local.cn_use_depth and "depth_image" in identity_data:
                control_images.append(identity_data["depth_image"])
                control_scales.append(id_cfg_local.cn_depth_weight)
                control_guidance_ends.append(id_cfg_local.cn_depth_guidance_end)
                control_modes.append(None)
                logger.info(
                    f"  🌊 Depth: scale={id_cfg_local.cn_depth_weight}, "
                    f"end={id_cfg_local.cn_depth_guidance_end}"
                )

            if not control_images:
                logger.warning("⚠️ [Pass 1 CN] CN 画像なし → 通常 _run_pass1 にフォールバック")
                return self._run_pass1(gen_cfg, identity_data, seed)

            # ─── 3. 推論パラメータ ────────────────────────────────
            steps = gen_cfg.resolved_steps(
                self.strategy,
                hyper_flux_enabled=self.sys_cfg.enable_hyper_flux,
            )
            generator = torch.Generator(device=self.pm.device).manual_seed(seed)

            kwargs: dict[str, Any] = {
                "prompt": gen_cfg.prompt,
                "negative_prompt": gen_cfg.negative_prompt,
                "width": gen_cfg.width,
                "height": gen_cfg.height,
                "num_inference_steps": steps,
                "guidance_scale": gen_cfg.guidance_scale,
                "generator": generator,
                "control_image": control_images,
                "controlnet_conditioning_scale": control_scales,
                "control_guidance_end": control_guidance_ends,
                "control_mode": control_modes,
            }

            # ─── 3.5 RECON-028 案B: native pipeline へ PuLID 素材を明示渡し ───
            #   id_embeddings を明示 kwarg で渡す → 共有 transformer の wrapper
            #   (04:889-891)が素通し分岐で raw pulid_forward へ直行 = clean native pass。
            #   旧 FluxControlNetPipeline(AIBO_PULID_CN_NATIVE=0)は4 kwargs 非対応のため
            #   pipeline クラス名で gate する(旧経路はこのブロックを素通し=退行ゼロ)。
            if type(self.pm.pipe_cnet).__name__ == "PuLIDFluxControlNetPipeline":
                pm_pulid = getattr(self.pm.pipe_base, "pulid_model", None)
                ref = identity_data.get("reference_image")  # snipe 済み1枚目
                id_emb = None
                if pm_pulid is not None and ref is not None:
                    _resize_fn = None
                    _resize_errs = []
                    for _modpath in ("pulid.utils", "nunchaku.models.pulid.utils",
                                     "nunchaku.utils", "pulid.pipeline_flux"):
                        try:
                            _cand = getattr(import_module(_modpath), "resize_numpy_image_long", None)
                            if _cand is not None:
                                _resize_fn = _cand
                                break
                            _resize_errs.append(f"{_modpath}: 属性なし")
                        except Exception as _re_imp:
                            _resize_errs.append(f"{_modpath}: {type(_re_imp).__name__}: {_re_imp}")
                    try:
                        if _resize_fn is None:
                            raise RuntimeError(f"resize_numpy_image_long import 不可: {_resize_errs}")
                        # native 単写 v0.9.1 抽出(案A/ipoff と同一素材)
                        id_np = _resize_fn(np.array(ref.convert("RGB")), 1024)
                        id_emb, _ = pm_pulid.get_id_embedding(id_np)  # facexlib align 失敗=RuntimeError
                        logger.info(
                            f"💉 [Pass 1 CN] native単写 emb 抽出 OK (shape={tuple(id_emb.shape)})"
                        )
                    except Exception as _e_emb:
                        logger.warning(
                            "⚠️ [Pass 1 CN] native embed 抽出失敗 → "
                            f"extractor 集約 id_embeds で続行(黙らない): {_e_emb}"
                        )
                        id_emb = identity_data.get("id_embeds")
                else:
                    logger.warning(
                        "⚠️ [Pass 1 CN] pulid_model/reference_image 欠落 → "
                        "extractor 集約 id_embeds で続行"
                    )
                    id_emb = identity_data.get("id_embeds")
                # Step 4 (B-0): IP-Adapter は完全遮断。ip_adapter_image_embeds は渡さない。
                kwargs["id_embeddings"] = id_emb
                kwargs["id_weight"] = identity_data.get("pulid_weight", 0.7)
                kwargs["pulid_start_timestep"] = None   # 第1弾: base 同等(全 step ON)
                kwargs["pulid_end_timestep"] = None
                logger.info(
                    "🧭 [OBS-ROUTE] 案B native PuLID-CN 素材渡し: "
                    f"id_weight={kwargs['id_weight']} / gating=None(全step) / IP=off(B-0)"
                )

            # ─── 4. 推論実行 ──────────────────────────────────────
            logger.info(
                f"🚀 [Pass 1 CN] 推論開始 "
                f"({len(control_images)} CN, {steps} steps)"
            )

            # Step1-pre OBS①: 実効経路マーカー(logging only · 挙動不変)
            #   この行が出て直後にフォールバック [OBS-ROUTE]=_run_pass1 が無ければ
            #   pipe_cnet が実際に走った = CN 経路確定。
            logger.info("🧭 [OBS-ROUTE] 経路=_run_pass1_with_cn (pipe_cnet)")
            t_start = time.perf_counter()
            output = self.pm.pipe_cnet(**kwargs)
            elapsed = time.perf_counter() - t_start

            logger.info(f"✅ [Pass 1 CN] 完了: {elapsed:.2f} 秒")

            if hasattr(output, "images") and output.images:
                return output.images[0]
            msg = (
                f"[Pass 1 CN] pipeline 出力に画像なし (has_images={hasattr(output, 'images')}, "
                f"len={len(output.images) if hasattr(output, 'images') and output.images is not None else 'N/A'})"
            )
            logger.warning("⚠️ %s", msg)
            raise RuntimeError(msg)

        except Exception as e:
            logger.error(f"❌ [Pass 1 CN] 失敗: {e}")
            logger.error(traceback.format_exc())
            logger.warning("→ 通常 _run_pass1 にフォールバック")
            return self._run_pass1(gen_cfg, identity_data, seed)

    # ─────────────────────────────────────────────────
    # Phase 2: 顔リファイン (Img2Img)
    # ─────────────────────────────────────────────────

    def _run_pass2(
        self,
        pass1_image: Image.Image,
        gen_cfg: GenerationConfig,
        identity_data: dict,
        seed: int,
    ) -> Optional[Image.Image]:
        """
        Pass 2: 顔リファイン (v6 v5.8.4 移植版)

        - 顔領域を YOLO/Haar で検出
        - 顔だけ 512×512 に拡大 (ピクセル密度 25倍)
        - Pass 2 専用 prompt で Img2Img 再描画
        - Feathering mask で元画像にブレンド合成 (背景・服装は壊さない)
        """
        if not gen_cfg.enable_pass2:
            return pass1_image
        if self.face_refiner is None:
            logger.info("ℹ️ [Pass 2] FaceRefiner 未初期化 · Pass 1 採用")
            return pass1_image
        if pass1_image is None:
            return None

        try:
            steps = gen_cfg.num_inference_steps if gen_cfg.num_inference_steps > 0 else 28
            refined = self.face_refiner.refine(
                base_image=pass1_image,
                prompt=gen_cfg.prompt,
                seed=seed + 1,
                steps=steps,
                guidance_scale=gen_cfg.guidance_scale,
                strength=gen_cfg.pass2_strength,
                target_size=512,
            )
            return refined

        except Exception as e:
            import traceback
            logger.error(f"❌ [Pass 2] 失敗 · Pass 1 採用: {e}")
            logger.error(traceback.format_exc())
            return pass1_image

    # ─────────────────────────────────────────────────
    # 自動保存
    # ─────────────────────────────────────────────────

    def _save_result(self, result: GenerationResult) -> Optional[Path]:
        """生成結果を outputs/generated/ に保存"""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            base = f"{timestamp}_seed{result.seed}_{result.mode}"

            img_path = self.save_dir / f"{base}.png"
            result.final_image.save(img_path)

            # メタデータも保存
            meta_path = self.save_dir / f"{base}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(result.to_metadata_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"💾 保存完了: {img_path.name}")
            return img_path

        except Exception as e:
            logger.warning(f"⚠️ 自動保存失敗: {e}")
            return None

    # ─────────────────────────────────────────────────
    # メモリクリーンアップ
    # ─────────────────────────────────────────────────

    def _flush_vram(self):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()


# ============================================================================
# 🔧 Section 5.5 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    sys.dont_write_bytecode = True  # __pycache__ 作らない (キャッシュ問題回避)

    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 5 (Orchestrator) 動作確認")
    print("=" * 60)

    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()

    print()
    print(f"🔍 戦略: {sys_cfg.strategy.kind.value}")

    # ─── クラス定義確認 ───
    print()
    print("🧪 クラス定義確認:")
    print(f"  Phase0Sniper:           {Phase0Sniper.__name__}")
    print(f"  ModeManager:            {ModeManager.__name__}")
    print(f"  GenerationResult:       {GenerationResult.__name__}")
    print(f"  CharacterOrchestrator:  {CharacterOrchestrator.__name__}")

    # ─── ModeManager の動作確認 (軽量) ───
    print()
    print("🧪 ModeManager 動作確認:")
    mm = ModeManager(sys_cfg)
    for mode in StudioMode:
        gen_cfg = GenerationConfig()  # 全デフォルト
        id_cfg  = IdentityConfig()
        gen_cfg, id_cfg, mode_cfg = mm.apply(mode, gen_cfg, id_cfg)
        print(f"  {mode_cfg.icon} {mode.value}:")
        print(f"     prompt:      {gen_cfg.prompt[:60]}...")
        print(f"     aspect:      {gen_cfg.width}×{gen_cfg.height}")
        print(f"     ctrl_type:   {id_cfg.controlnet_type}")

    # ─── GenerationResult の動作確認 ───
    print()
    print("🧪 GenerationResult メタデータ:")
    res = GenerationResult(seed=42, mode="portrait", pulid_used=True)
    res.elapsed_total_sec = 12.34
    print(f"  to_metadata_dict: {res.to_metadata_dict()}")

    # ─── Phase0Sniper の lazy_init は呼ばない (YOLO DL で重い) ───
    print()
    print("🧪 Phase0Sniper (lazy_init は skip):")
    sniper = Phase0Sniper(sys_cfg)
    print(f"  margin_ratio: {sniper.margin_ratio}")
    print(f"  YOLO_MODEL_PATH: {sniper.YOLO_MODEL_PATH}")

    # ─── CharacterOrchestrator の初期化 (依存クラスを揃える必要あり) ───
    print()
    print("🧪 CharacterOrchestrator は build 済みパイプライン必須")
    print("  実動作確認は Section 7 (main) で:")
    print("    pm = FluxA100PipelineManager(sys_cfg); pm.build()")
    print("    ie = IdentityEngine(sys_cfg)")
    print("    am = AssetManager(sys_cfg, pm)")
    print("    orch = CharacterOrchestrator(sys_cfg, pm, ie, am)")
    print("    result = orch.generate(gen_cfg, id_cfg, mode=StudioMode.PORTRAIT)")

    print()
    print("✅ Section 5 動作確認完了")
