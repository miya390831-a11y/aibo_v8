"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2.1 · Section 8 · Face Refiner
================================================================================

📌 ファイル名: 08_face_refiner.py

📌 このファイルの責務:
    Pass 2 の顔リファイン処理 (v6 v5.8.4 から移植):
      1. 顔領域を YOLO で検出
      2. 顔だけ crop して 512×512 に拡大 (ピクセル密度 25倍)
      3. Pass 2 専用 prompt で Img2Img 再描画
      4. Feathering mask で元画像にブレンド合成

依存:
    - 01_config.py
    - cv2, PIL.ImageFilter, numpy

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2.1
================================================================================
"""

from __future__ import annotations

import logging
import sys
import time
from importlib import import_module
from dataclasses import dataclass
from typing import Literal, Optional, Tuple

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFilter

# ─── 01_config から型を import ───
_cfg_mod = import_module("01_config")
logger = _cfg_mod.logger

# ============================================================
# torchvision functional_tensor 互換 shim
# ------------------------------------------------------------
# 背景:
#   torchvision 0.17+ で torchvision.transforms.functional_tensor が削除された。
#   BasicSR (GFPGAN の依存ライブラリ) が古い import を使用する場合があり、
#   GFPGAN 起動時に ModuleNotFoundError になることがある。
#
# 対処:
#   functional を functional_tensor として alias 登録して互換性を担保する。
# ============================================================
try:
    import torchvision.transforms.functional as _tvf

    if "torchvision.transforms.functional_tensor" not in sys.modules:
        sys.modules["torchvision.transforms.functional_tensor"] = _tvf
        logger.debug("[FaceRestoreEngine] torchvision functional_tensor alias 登録")
except ImportError:
    # torchvision 非導入環境では何もしない
    pass

# GFPGAN / insightface lazy singleton
_GFPGANER = None
_INSIGHTFACE_APP = None


@dataclass
class FaceRestoreResult:
    """Phase 3 ハイブリッド γ の処理結果"""

    final_image: Image.Image
    pre_phase3_image: Optional[Image.Image] = None
    phase3a_image: Optional[Image.Image] = None
    phase3b_image: Optional[Image.Image] = None
    face_mask: Optional[Image.Image] = None
    face_bbox: Optional[Tuple[int, int, int, int]] = None
    yaw_deg: float = 0.0
    pitch_deg: float = 0.0
    roll_deg: float = 0.0
    bypass_triggered: bool = False
    bypass_reason: str = ""
    phase3a_applied: bool = False
    phase3b_applied: bool = False
    elapsed_phase3a_sec: float = 0.0
    elapsed_phase3b_sec: float = 0.0
    elapsed_total_sec: float = 0.0


class FaceRestoreEngine:
    """
    Phase 3 ハイブリッド γ ポストプロセスエンジン。

    GFPGAN (低周波構造補正) + FLUX.1-Fill INT4 (高周波テクスチャ補完)
    + 角度動的バイパス + insightface 顔マスク生成。
    """

    def __init__(
        self,
        pipeline_manager,
        sys_cfg,
        gfpgan_strength: float = 0.35,
        fill_denoising: float = 0.25,
        angle_bypass_yaw_deg: float = 35.0,
        face_mask_feather_px: int = 21,
        face_mask_margin_ratio: float = 0.20,
    ):
        self.pm = pipeline_manager
        self.sys_cfg = sys_cfg
        self.gfpgan_strength = gfpgan_strength
        self.fill_denoising = fill_denoising
        self.angle_bypass_yaw_deg = angle_bypass_yaw_deg
        self.face_mask_feather_px = face_mask_feather_px
        self.face_mask_margin_ratio = face_mask_margin_ratio
        self._gfpganer = None
        self._last_insightface_face = None
        logger.info(
            f"[FaceRestoreEngine] 初期化: gfpgan_strength={gfpgan_strength}, "
            f"fill_denoising={fill_denoising}, angle_bypass_yaw={angle_bypass_yaw_deg}°"
        )

    def process(
        self,
        image: Image.Image,
        prompt: Optional[str] = None,
        debug_keep_intermediates: bool = False,
    ) -> FaceRestoreResult:
        """Phase 3 ハイブリッド γ のメイン処理。"""
        t_start = time.perf_counter()
        result = FaceRestoreResult(final_image=image)
        if debug_keep_intermediates:
            result.pre_phase3_image = image

        face_bbox, face_mask = self._detect_face_and_make_mask(image)
        if face_bbox is None or face_mask is None:
            logger.warning("[Phase 3] 顔検出失敗 · Phase 3 全体スキップ (元画像返却)")
            result.bypass_triggered = True
            result.bypass_reason = "顔検出失敗"
            result.elapsed_total_sec = time.perf_counter() - t_start
            return result

        result.face_bbox = face_bbox
        if debug_keep_intermediates:
            result.face_mask = face_mask

        yaw, pitch, roll = self._estimate_face_angle(image, face_bbox)
        result.yaw_deg = yaw
        result.pitch_deg = pitch
        result.roll_deg = roll
        logger.info(f"[Phase 3] 角度計測: yaw={yaw:.1f}°, pitch={pitch:.1f}°, roll={roll:.1f}°")

        if abs(yaw) > self.angle_bypass_yaw_deg:
            logger.info(
                f"[Phase 3] 角度バイパス発動: |yaw|={abs(yaw):.1f}° > {self.angle_bypass_yaw_deg}° "
                "→ Phase 3 全体スキップ"
            )
            result.bypass_triggered = True
            result.bypass_reason = f"yaw {yaw:.1f}° (閾値 {self.angle_bypass_yaw_deg}°)"
            result.elapsed_total_sec = time.perf_counter() - t_start
            return result

        if getattr(_cfg_mod, "PHASE3A_ENABLED", True):
            t_3a = time.perf_counter()
            try:
                phase3a_image = self._apply_gfpgan(image, face_bbox)
                result.phase3a_applied = True
                result.elapsed_phase3a_sec = time.perf_counter() - t_3a
                if debug_keep_intermediates:
                    result.phase3a_image = phase3a_image
                logger.info(f"[Phase 3a] GFPGAN 完了 ({result.elapsed_phase3a_sec:.2f} 秒)")
            except Exception as e:
                logger.warning(f"[Phase 3a] GFPGAN 失敗 · 元画像で続行: {e}")
                phase3a_image = image
        else:
            logger.info("[Phase 3a] PHASE3A_ENABLED=False · スキップ")
            phase3a_image = image

        if getattr(_cfg_mod, "PHASE3B_ENABLED", True):
            t_3b = time.perf_counter()
            try:
                phase3b_image = self._apply_fill_inpaint(
                    phase3a_image, face_mask, prompt=prompt
                )
                result.phase3b_applied = True
                result.elapsed_phase3b_sec = time.perf_counter() - t_3b
                if debug_keep_intermediates:
                    result.phase3b_image = phase3b_image
                logger.info(f"[Phase 3b] Fill INT4 完了 ({result.elapsed_phase3b_sec:.2f} 秒)")
            except Exception as e:
                logger.warning(f"[Phase 3b] Fill 失敗 · Phase 3a 結果で続行: {e}")
                phase3b_image = phase3a_image
        else:
            logger.info("[Phase 3b] PHASE3B_ENABLED=False · スキップ")
            phase3b_image = phase3a_image

        result.final_image = self._alpha_blend(image, phase3b_image, face_mask)
        result.elapsed_total_sec = time.perf_counter() - t_start
        logger.info(
            f"[Phase 3] 完了: 総時間 {result.elapsed_total_sec:.2f} 秒 "
            f"(3a: {result.elapsed_phase3a_sec:.2f}s + 3b: {result.elapsed_phase3b_sec:.2f}s)"
        )
        return result

    def _detect_face_and_make_mask(
        self, image: Image.Image
    ) -> Tuple[Optional[Tuple[int, int, int, int]], Optional[Image.Image]]:
        """
        insightface antelopev2 で顔検出してマスクを生成。
        """
        global _INSIGHTFACE_APP
        if _INSIGHTFACE_APP is None:
            from insightface.app import FaceAnalysis

            insightface_root = "/root/.cache/huggingface/hub/insightface"
            _INSIGHTFACE_APP = FaceAnalysis(
                name="antelopev2",
                root=insightface_root,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            _INSIGHTFACE_APP.prepare(ctx_id=0, det_size=(640, 640))
            logger.info("[FaceRestoreEngine] insightface FaceAnalysis 初期化完了 (antelopev2)")

        img_rgb = np.array(image.convert("RGB"))
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        h, w = img_bgr.shape[:2]

        faces = _INSIGHTFACE_APP.get(img_bgr)
        if not faces:
            return None, None

        face = faces[0]
        x1, y1, x2, y2 = face.bbox.astype(int)
        face_w = x2 - x1
        face_h = y2 - y1

        margin_x = int(face_w * self.face_mask_margin_ratio)
        margin_y = int(face_h * self.face_mask_margin_ratio)
        x1 = max(0, x1 - margin_x)
        y1 = max(0, y1 - margin_y)
        x2 = min(w, x2 + margin_x)
        y2 = min(h, y2 + margin_y)

        face_bbox = (x1, y1, x2 - x1, y2 - y1)
        mask_np = np.zeros((h, w), dtype=np.uint8)
        mask_np[y1:y2, x1:x2] = 255
        kernel = max(3, self.face_mask_feather_px | 1)
        mask_np = cv2.GaussianBlur(mask_np, (kernel, kernel), 0)
        self._last_insightface_face = face
        return face_bbox, Image.fromarray(mask_np)

    def _estimate_face_angle(
        self, image: Image.Image, face_bbox: Tuple[int, int, int, int]
    ) -> Tuple[float, float, float]:
        """insightface pose([pitch, yaw, roll]) から角度を取得。"""
        _ = face_bbox  # v8.0 では将来拡張用に引数保持
        face = getattr(self, "_last_insightface_face", None)
        if face is None:
            global _INSIGHTFACE_APP
            if _INSIGHTFACE_APP is None:
                return 0.0, 0.0, 0.0

            img_bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
            faces = _INSIGHTFACE_APP.get(img_bgr)
            if not faces:
                return 0.0, 0.0, 0.0
            face = faces[0]

        if hasattr(face, "pose") and face.pose is not None:
            pose = face.pose
            pitch_deg = float(pose[0])
            yaw_deg = float(pose[1])
            roll_deg = float(pose[2])
            return yaw_deg, pitch_deg, roll_deg
        return 0.0, 0.0, 0.0

    def _apply_gfpgan(
        self, image: Image.Image, face_bbox: Tuple[int, int, int, int]
    ) -> Image.Image:
        """GFPGAN v1.4 で顔構造を低強度補正 (URL 自動DL)。"""
        _ = face_bbox
        if self._gfpganer is None:
            from gfpgan import GFPGANer

            self._gfpganer = GFPGANer(
                model_path="https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
                upscale=1,
                arch="clean",
                channel_multiplier=2,
                bg_upsampler=None,
            )
            logger.info("[Phase 3a] GFPGAN v1.4 初回ロード完了 (URL 経由 auto DL)")

        img_bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        _, _, restored_img = self._gfpganer.enhance(
            img_bgr,
            has_aligned=False,
            only_center_face=True,
            paste_back=True,
            weight=self.gfpgan_strength,
        )
        restored_rgb = cv2.cvtColor(restored_img, cv2.COLOR_BGR2RGB)
        return Image.fromarray(restored_rgb)

    def _apply_fill_inpaint(
        self,
        image: Image.Image,
        face_mask: Image.Image,
        prompt: Optional[str] = None,
        mode: Literal["texture", "custom"] = "texture",
    ) -> Image.Image:
        """
        FLUX.1-Fill で顔領域に低 denoising inpaint を適用。

        Note:
            FluxFillPipeline は CFG=1.0 設計のため negative_prompt 非対応。
        """
        _ = mode  # シグネチャ後方互換のため保持
        if prompt is None:
            positive = _cfg_mod.POSITIVE_PROMPT_TEXTURE
        else:
            positive = prompt

        try:
            pipe_fill = self.pm.ensure_fill_pipeline()
            generator = torch.Generator(device=self.pm.device).manual_seed(
                int(torch.randint(0, 2**31 - 1, (1,)).item())
            )
            result = pipe_fill(
                prompt=positive,
                image=image,
                mask_image=face_mask,
                strength=self.fill_denoising,
                guidance_scale=4.0,
                num_inference_steps=20,
                generator=generator,
            )
            return result.images[0]
        finally:
            self.pm.restore_after_fill()

    def _alpha_blend(self, original: Image.Image, refined: Image.Image, mask: Image.Image) -> Image.Image:
        """フェザーマスクで original と refined を合成。"""
        if refined.size != original.size:
            refined = refined.resize(original.size, Image.LANCZOS)
        if mask.size != original.size:
            mask = mask.resize(original.size, Image.LANCZOS)
        return Image.composite(refined, original, mask)


# ============================================================================
# 🎯 Section 8.1 · Pass 2 専用プロンプト生成
# ============================================================================

def build_pass2_face_prompts(brightness: str = "natural") -> tuple[str, str]:
    """
    Pass 2 顔リファイン専用の T5 / CLIP プロンプトを生成。
    Pass 1 の全身 prompt をそのまま流用すると「顔の中にミニチュアの全身」
    が生成される問題への対策。
    """
    if brightness == "bright":
        light_hint = ", soft natural daylight illumination on the face"
    elif brightness == "dark":
        light_hint = ", low-key dramatic lighting on the face"
    else:
        light_hint = ", balanced natural lighting on the face"

    t5_face = (
        "A raw unretouched close-up portrait preserving the exact facial identity "
        "of the reference person, visible skin pores, natural asymmetrical facial features, "
        "photographic realism, catchlight in the eyes, authentic identity, "
        "looking directly into the camera with clear eye contact"
        + light_hint
    )
    clip_face = (
        "raw unretouched close-up portrait, exact identity preserved, "
        "visible skin pores, natural asymmetrical features, photorealistic, "
        "looking at viewer, front facing"
    )
    return t5_face, clip_face


# ============================================================================
# 🎯 Section 8.2 · 顔検出 (OpenCV Haar Cascade フォールバック付き)
# ============================================================================

def detect_face_bbox_cv(
    image_pil: Image.Image,
    margin_ratio: float = 0.5,
    yolo_detector=None,
) -> Optional[tuple[int, int, int, int]]:
    """
    画像から顔のバウンディングボックスを検出。
    YOLO → OpenCV Haar Cascade の順にフォールバック。

    Args:
        image_pil: 入力画像
        margin_ratio: bbox 周辺のマージン (0.5 = 50% 拡張)
        yolo_detector: ultralytics YOLO インスタンス (省略可)

    Returns:
        (x1, y1, x2, y2) または None (検出失敗時)
    """
    import cv2
    import os

    img_cv = cv2.cvtColor(np.array(image_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    h_img, w_img = img_cv.shape[:2]

    found = False
    x = y = w = h = 0
    detected_by = ""

    # ─── 1. YOLO 試行 ───
    if yolo_detector is not None:
        try:
            results = yolo_detector(image_pil, verbose=False)
            best = None
            best_area = 0.0
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes.xyxy.cpu().numpy():
                    x1, y1, x2, y2 = [float(v) for v in box]
                    area = (x2 - x1) * (y2 - y1)
                    if area > best_area:
                        best_area = area
                        best = (x1, y1, x2, y2)
            if best is not None:
                x1, y1, x2, y2 = best
                x = int(x1); y = int(y1)
                w = int(x2 - x1); h = int(y2 - y1)
                detected_by = "YOLO"
                found = True
        except Exception as e:
            logger.debug(f"[FaceDetect] YOLO 失敗: {e}")

    # ─── 2. Haar Cascade フォールバック ───
    if not found:
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        if os.path.exists(cascade_path):
            face_cascade = cv2.CascadeClassifier(cascade_path)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48),
            )
            if len(faces) > 0:
                faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
                x, y, w, h = faces[0]
                detected_by = "Haar"
                found = True

    if not found:
        logger.info("ℹ️ [FaceDetect] 顔検出失敗")
        return None

    # ─── マージン拡張 ───
    mw = int(w * margin_ratio)
    mh = int(h * margin_ratio)
    x1 = max(0, x - mw)
    y1 = max(0, y - int(mh * 1.5))  # 上方向にやや多めにマージン (髪を含める)
    x2 = min(w_img, x + w + mw)
    y2 = min(h_img, y + h + mh)

    logger.info(
        f"🎯 [FaceDetect/{detected_by}] bbox=({x1},{y1},{x2},{y2}) "
        f"size={x2-x1}×{y2-y1}"
    )
    return (x1, y1, x2, y2)


# ============================================================================
# 🎯 Section 8.3 · Feathering ブレンド合成
# ============================================================================

def blend_face(
    base_image: Image.Image,
    face_image: Image.Image,
    bbox: tuple[int, int, int, int],
    feather_ratio: float = 0.15,
) -> Image.Image:
    """
    リファインした顔画像を元画像にブレンド合成 (背景・服装を壊さない)。

    Args:
        base_image: ベース画像 (Pass 1 出力)
        face_image: リファイン後の顔画像 (リサイズ前)
        bbox: 元画像での顔領域 (x1, y1, x2, y2)
        feather_ratio: Feathering の割合 (0.15 = 15%)

    Returns:
        合成後の画像
    """
    sz = (bbox[2] - bbox[0], bbox[3] - bbox[1])
    face_resized = face_image.resize(sz, Image.LANCZOS)

    # Feathering mask 生成
    mask = Image.new("L", sz, 0)
    draw = ImageDraw.Draw(mask)
    feather = max(4, int(min(sz) * feather_ratio))
    draw.rectangle(
        [feather, feather, sz[0] - feather, sz[1] - feather],
        fill=255,
    )
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    # 合成
    out = base_image.copy()
    out.paste(face_resized, (bbox[0], bbox[1]), mask)
    return out


# ============================================================================
# 🎯 Section 8.4 · Face Refiner (Pass 2 司令塔)
# ============================================================================

class FaceRefiner:
    """
    Pass 2 顔リファインの司令塔。
    v6 v5.8.4 の純粋 I2I 方式を v7.2 に移植。
    """

    def __init__(self, sys_cfg, pipeline_mgr):
        self.sys_cfg = sys_cfg
        self.pm = pipeline_mgr
        self._yolo_detector = None  # lazy load

    # ─────────────────────────────────────────────────
    # YOLO lazy init
    # ─────────────────────────────────────────────────
    def _ensure_yolo(self):
        if self._yolo_detector is not None:
            return self._yolo_detector
        try:
            from ultralytics import YOLO
            # 軽量な汎用 YOLOv8n でも顔検出に使える (オプション)
            self._yolo_detector = YOLO("yolov8n.pt")
            logger.info("✅ [FaceRefiner] YOLOv8n 初期化")
        except Exception as e:
            logger.warning(f"⚠️ [FaceRefiner] YOLO 初期化失敗 (Haar Cascade で続行): {e}")
            self._yolo_detector = None
        return self._yolo_detector

    # ─────────────────────────────────────────────────
    # メイン: refine
    # ─────────────────────────────────────────────────
    def refine(
        self,
        base_image: Image.Image,
        prompt: str,
        seed: int,
        steps: int = 28,
        guidance_scale: float = 3.5,
        strength: float = 0.45,
        target_size: int = 512,
    ) -> Image.Image:
        """
        Pass 1 出力に対して Pass 2 顔リファインを適用。

        Args:
            base_image: Pass 1 出力画像
            prompt: 元の生成 prompt (環境光のヒント抽出用)
            seed: Pass 2 seed (Pass 1 + 1 推奨)
            steps: Pass 2 ステップ数
            guidance_scale: Pass 2 CFG
            strength: Img2Img strength (0.45 推奨)
            target_size: 顔 crop の拡大先サイズ

        Returns:
            リファイン後の画像 (顔だけ更新、背景は元のまま)
            検出失敗時は base_image をそのまま返す
        """
        if self.pm.pipe_i2i is None:
            logger.warning("⚠️ [FaceRefiner] pipe_i2i 未構築 · refine スキップ")
            return base_image

        # ─── 1. 顔検出 ───
        yolo = self._ensure_yolo()
        bbox = detect_face_bbox_cv(base_image, margin_ratio=0.5, yolo_detector=yolo)
        if bbox is None:
            logger.info("ℹ️ [FaceRefiner] 顔検出失敗 · Pass 1 採用")
            return base_image

        cx1, cy1, cx2, cy2 = bbox
        cw, ch = cx2 - cx1, cy2 - cy1

        # ─── 2. 顔 crop + 拡大 ───
        face_crop = base_image.crop(bbox).resize(
            (target_size, target_size), Image.Resampling.LANCZOS
        )

        # ─── 3. Pass 2 専用 prompt ───
        p2_t5, p2_clip = build_pass2_face_prompts(brightness="natural")

        logger.info(
            f"🎨 [FaceRefiner] Pass 2 顔拡大 I2I 開始 "
            f"crop=({cx1},{cy1},{cx2},{cy2}) {cw}×{ch} → {target_size}×{target_size} "
            f"strength={strength}"
        )

        # ─── 4. Img2Img 実行 ───
        try:
            generator = torch.Generator(device=self.pm.device).manual_seed(seed)
            with torch.no_grad():
                result = self.pm.pipe_i2i(
                    prompt=p2_t5,
                    image=face_crop,
                    strength=strength,
                    width=target_size,
                    height=target_size,
                    num_inference_steps=steps,
                    guidance_scale=guidance_scale,
                    generator=generator,
                )
            refined_face = result.images[0]
        except Exception as e:
            logger.warning(f"⚠️ [FaceRefiner] I2I 失敗 · Pass 1 採用: {e}")
            return base_image

        # ─── 5. Feathering 合成 ───
        composed = blend_face(base_image, refined_face, bbox)
        logger.info("✅ [FaceRefiner] Pass 2 リファイン + Feathering 合成完了")

        # ─── クリーンアップ ───
        import gc
        del face_crop, refined_face, result
        gc.collect()
        torch.cuda.empty_cache()

        return composed


# ============================================================================
# 🔧 Section 8.5 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    import sys
    sys.dont_write_bytecode = True

    print("=" * 60)
    print("🌌 AIBO v7.2.1 · Section 8 (Face Refiner) 動作確認")
    print("=" * 60)

    print()
    print("🧪 関数定義確認:")
    print(f"  build_pass2_face_prompts: {build_pass2_face_prompts.__name__}")
    print(f"  detect_face_bbox_cv:      {detect_face_bbox_cv.__name__}")
    print(f"  blend_face:               {blend_face.__name__}")
    print(f"  FaceRefiner:              {FaceRefiner.__name__}")

    # ─── prompt 生成テスト ───
    print()
    print("🧪 Pass 2 prompt 生成:")
    p2_t5, p2_clip = build_pass2_face_prompts()
    print(f"  T5  ({len(p2_t5)} chars): {p2_t5[:80]}...")
    print(f"  CLIP ({len(p2_clip)} chars): {p2_clip[:80]}...")

    print()
    print("✅ Section 8 動作確認完了")
