"""
10_mask_engine.py (簡易版 · v8.0 Layer 4)

顔マスク生成。MediaPipe Face Mesh → Tasks FaceLandmarker → OpenCV Haar の順でフォールバック。
SAM 2 本格統合は Week 5 予定。
"""

from __future__ import annotations

import logging
import os
import urllib.request
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("AIBO_v7.MaskEngine")

FEATHER_RADIUS_PX = 15

_mediapipe_face_mesh = None
_mediapipe_face_landmarker: Any = None


def _lazy_init_face_mesh():
    """mp.solutions.face_mesh（利用可能な環境のみ）。"""
    global _mediapipe_face_mesh
    if _mediapipe_face_mesh is False:
        return None
    if _mediapipe_face_mesh is not None:
        return _mediapipe_face_mesh
    try:
        import mediapipe as mp

        if not hasattr(mp, "solutions"):
            return None
        mp_fm = mp.solutions.face_mesh
        _mediapipe_face_mesh = mp_fm.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=0.5,
        )
        logger.info("[MaskEngine] MediaPipe Face Mesh (solutions) 初期化完了")
    except Exception as exc:
        logger.warning("[MaskEngine] Face Mesh solutions 利用不可: %s", exc)
        _mediapipe_face_mesh = False
    return _mediapipe_face_mesh


def _lazy_init_face_landmarker_tasks() -> Any:
    """MediaPipe Tasks FaceLandmarker（0.10+）。"""
    global _mediapipe_face_landmarker
    if _mediapipe_face_landmarker is False:
        return None
    if _mediapipe_face_landmarker is not None:
        return _mediapipe_face_landmarker
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        model_url = (
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/latest/face_landmarker.task"
        )
        cache_dir = os.path.expanduser("~/.cache/mediapipe_face")
        os.makedirs(cache_dir, exist_ok=True)
        model_path = os.path.join(cache_dir, "face_landmarker.task")
        if not os.path.isfile(model_path):
            logger.info("[MaskEngine] Face Landmarker モデル DL 中...")
            urllib.request.urlretrieve(model_url, model_path)

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = mp_vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.5,
        )
        _mediapipe_face_landmarker = mp_vision.FaceLandmarker.create_from_options(options)
        logger.info("[MaskEngine] MediaPipe FaceLandmarker (Tasks) 初期化完了")
        return _mediapipe_face_landmarker
    except Exception as exc:
        logger.warning("[MaskEngine] FaceLandmarker Tasks 初期化失敗: %s", exc)
        _mediapipe_face_landmarker = False
        return None


def _convex_hull_points(points: np.ndarray) -> np.ndarray:
    if len(points) < 3:
        return points
    try:
        from scipy.spatial import ConvexHull

        hull = ConvexHull(points)
        return points[hull.vertices]
    except Exception:
        pass
    try:
        import cv2

        hull = cv2.convexHull(points.astype(np.float32))
        return hull.reshape(-1, 2)
    except Exception:
        x_min, y_min = points.min(axis=0)
        x_max, y_max = points.max(axis=0)
        return np.array(
            [[x_min, y_min], [x_max, y_min], [x_max, y_max], [x_min, y_max]],
            dtype=np.int32,
        )


def _rasterize_hull(w: int, h: int, hull_points: np.ndarray) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    poly = [(int(p[0]), int(p[1])) for p in hull_points]
    if len(poly) >= 3:
        draw.polygon(poly, fill=255)
    return mask


def _mask_from_face_mesh(image: Image.Image, img_np: np.ndarray) -> Optional[Image.Image]:
    mesh = _lazy_init_face_mesh()
    if mesh is None or mesh is False:
        return None
    h, w = img_np.shape[:2]
    try:
        import mediapipe as mp

        res = mesh.process(img_np)
        if not res.multi_face_landmarks:
            return None
        lm = res.multi_face_landmarks[0].landmark
        points = np.array([[int(p.x * w), int(p.y * h)] for p in lm], dtype=np.int32)
        hull = _convex_hull_points(points)
        mask = _rasterize_hull(w, h, hull)
        return mask.filter(ImageFilter.GaussianBlur(radius=FEATHER_RADIUS_PX))
    except Exception as exc:
        logger.warning("[MaskEngine] Face Mesh 推論失敗: %s", exc)
        return None


def _mask_from_face_landmarker_tasks(image: Image.Image, img_np: np.ndarray) -> Optional[Image.Image]:
    landmarker = _lazy_init_face_landmarker_tasks()
    if landmarker is None:
        return None
    h, w = img_np.shape[:2]
    try:
        import mediapipe as mp

        contig = np.ascontiguousarray(img_np)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=contig)
        result = landmarker.detect(mp_image)
        if not result.face_landmarks:
            return None
        lm = result.face_landmarks[0]
        points = np.array([[int(p.x * w), int(p.y * h)] for p in lm], dtype=np.int32)
        hull = _convex_hull_points(points)
        mask = _rasterize_hull(w, h, hull)
        return mask.filter(ImageFilter.GaussianBlur(radius=FEATHER_RADIUS_PX))
    except Exception as exc:
        logger.warning("[MaskEngine] FaceLandmarker 推論失敗: %s", exc)
        return None


def _mask_from_haar(image: Image.Image, img_np: np.ndarray) -> Optional[Image.Image]:
    try:
        import cv2

        h, w = img_np.shape[:2]
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        face_cascade = cv2.CascadeClassifier(cascade_path)
        faces = face_cascade.detectMultiScale(gray, 1.1, 4)
        if len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        pad_x = int(fw * 0.15)
        pad_y = int(fh * 0.2)
        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(w, x + fw + pad_x)
        y2 = min(h, y + fh + pad_y)
        draw.ellipse([x1, y1, x2, y2], fill=255)
        return mask.filter(ImageFilter.GaussianBlur(radius=FEATHER_RADIUS_PX))
    except Exception as exc:
        logger.warning("[MaskEngine] Haar フォールバック失敗: %s", exc)
        return None


def generate_face_mask_simple(image: Image.Image) -> Optional[Image.Image]:
    """
    顔マスク (mode L) を生成。失敗時 None。
    """
    if image is None or image.size[0] < 64 or image.size[1] < 64:
        logger.warning("[MaskEngine] 画像が小さすぎる")
        return None

    rgb = image.convert("RGB")
    img_np = np.asarray(rgb, dtype=np.uint8)

    for fn in (_mask_from_face_mesh, _mask_from_face_landmarker_tasks, _mask_from_haar):
        mask = fn(rgb, img_np)
        if mask is not None and mask.size == rgb.size:
            ok, issues = validate_face_mask(mask, rgb.size)
            if issues:
                logger.info("[MaskEngine] マスク検証: ok=%s %s", ok, issues)
            logger.info("[MaskEngine] 顔マスク生成 OK (%s)", fn.__name__)
            return mask
    logger.warning("[MaskEngine] 全経路で顔マスク生成失敗")
    return None


def validate_face_mask(mask: Image.Image, image_size: tuple[int, int]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if mask is None:
        return False, ["mask_none"]
    img_w, img_h = image_size
    if mask.size != (img_w, img_h):
        issues.append(f"size_mismatch: mask={mask.size} image={image_size}")
        return False, issues
    arr = np.array(mask)
    total = arr.size
    white = (arr > 128).sum()
    ratio = float(white) / float(total) if total else 0.0
    if ratio < 0.02:
        issues.append(f"face_too_small: ratio={ratio:.4f}")
    elif ratio > 0.45:
        issues.append(f"face_too_large: ratio={ratio:.4f}")
    return len(issues) == 0, issues
