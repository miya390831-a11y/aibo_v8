"""
16_pose_extractor.py

DWPose ベースの 10 軸体型推論エンジン。

機能:
  - DWPose (controlnet_aux) で body keypoints 抽出
  - keypoints から 10 軸 (5 チャート × 2 軸) 推論
  - 信頼度算出
  - エラーハンドリング (invalid_image / person_not_detected / insufficient_keypoints / runtime)

環境差分:
  - controlnet_aux のトップレベル __init__ が mediapipe_face 経由で失敗する場合 (例: mediapipe 0.10.x で
    classic solutions API 非対応)、site-packages 上のサブパッケージのみを読む shim を張る。
  - DWposeDetector はバージョンにより JSON を返さず skeleton 画像のみ返すため、pose_estimation を直接呼び
    Wholebody の (keypoints, scores) をパースする経路を優先する。
  - mm 系 (mmdet/mmpose) 未導入で DWPose が失敗する環境では MediaPipe Pose Landmarker (Tasks API) にフォールバック。
"""

from __future__ import annotations

import importlib
import logging
import math
import os
import sys
import types
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image
import torch

logger = logging.getLogger("AIBO_v7.PoseExtractor")

# MediaPipe フォールバック用 (DWPose が動かない環境向け · Tasks API)
try:
    import mediapipe as mp

    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    _MEDIAPIPE_AVAILABLE = True
except ImportError:
    mp = None  # type: ignore[assignment]
    mp_python = None  # type: ignore[assignment]
    mp_vision = None  # type: ignore[assignment]
    _MEDIAPIPE_AVAILABLE = False
    logger.warning("[PoseExtractor] mediapipe Tasks API 未利用可能 (フォールバック無効)")


@dataclass
class BodyShapeResult:
    body_shape: dict[str, dict[str, float]]
    confidence: float
    keypoints_count: int
    person_detected: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    backend: str = "none"  # "openpose" | "dwpose" | "mediapipe" | "none"


_dwpose_detector: Any = None
_openpose_detector: Any = None  # RECON-029 Fix A: 生成側と同一 OpenposeDetector
_mediapipe_landmarker: Any = None
_last_used_backend: str = "none"


def _bootstrap_controlnet_aux_shim() -> None:
    """controlnet_aux/__init__.py が依存不全で落ちる環境向けに namespace を登録する。"""
    if "controlnet_aux" in sys.modules:
        return
    try:
        importlib.import_module("controlnet_aux")
        return
    except Exception:
        pass

    try:
        import site

        roots = [Path(p) for p in site.getsitepackages()]
        try:
            roots.append(Path(site.getusersitepackages()))
        except Exception:
            pass
        for base in roots:
            root = base / "controlnet_aux"
            if (root / "dwpose" / "__init__.py").is_file():
                pkg = types.ModuleType("controlnet_aux")
                pkg.__path__ = [str(root)]
                sys.modules["controlnet_aux"] = pkg
                logger.info("[PoseExtractor] controlnet_aux shim registered (%s)", root)
                return
    except Exception as exc:
        logger.warning("[PoseExtractor] shim setup failed: %s", exc)

    raise ImportError("controlnet_aux を読み込めません (site-packages にパッケージがありません)")


def _get_dwpose_detector_class():
    _bootstrap_controlnet_aux_shim()
    mod = importlib.import_module("controlnet_aux.dwpose")
    return mod.DWposeDetector


def _instantiate_dwpose():
    cls = _get_dwpose_detector_class()
    fn = getattr(cls, "from_pretrained", None)
    if callable(fn):
        try:
            return fn("yzd-v/DWPose")
        except Exception as exc:
            logger.warning("[PoseExtractor] from_pretrained 失敗、既定コンストラクタへ: %s", exc)
    return cls()


def _lazy_init_dwpose():
    global _dwpose_detector
    if _dwpose_detector is None:
        logger.info("[PoseExtractor] DWPose 初期化中...")
        detector = _instantiate_dwpose()
        if torch.cuda.is_available() and hasattr(detector, "to"):
            detector = detector.to("cuda")
        _dwpose_detector = detector
        logger.info("[PoseExtractor] DWPose 初期化完了")
    return _dwpose_detector


def _lazy_init_mediapipe_landmarker() -> Any:
    """MediaPipe Pose Landmarker (Tasks API) の遅延初期化。失敗時は None。"""
    global _mediapipe_landmarker

    if not _MEDIAPIPE_AVAILABLE or mp is None or mp_python is None or mp_vision is None:
        logger.error("[PoseExtractor] mediapipe 未インストール")
        return None

    if _mediapipe_landmarker is None:
        try:
            logger.info("[PoseExtractor] MediaPipe Pose Landmarker 初期化中...")
            model_url = (
                "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
            )
            cache_dir = os.path.expanduser("~/.cache/mediapipe_pose")
            os.makedirs(cache_dir, exist_ok=True)
            model_path = os.path.join(cache_dir, "pose_landmarker_full.task")
            if not os.path.isfile(model_path):
                logger.info("[PoseExtractor] MediaPipe モデル DL 中: %s", model_url)
                urllib.request.urlretrieve(model_url, model_path)
                logger.info("[PoseExtractor] DL 完了: %s", model_path)

            base_options = mp_python.BaseOptions(model_asset_path=model_path)
            options = mp_vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_poses=1,
                min_pose_detection_confidence=0.5,
                min_pose_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_segmentation_masks=False,
            )
            _mediapipe_landmarker = mp_vision.PoseLandmarker.create_from_options(options)
            logger.info("[PoseExtractor] MediaPipe Pose Landmarker 初期化完了")
        except Exception as exc:
            logger.error("[PoseExtractor] MediaPipe 初期化失敗: %s", exc)
            return None

    return _mediapipe_landmarker


# MediaPipe BlazePose 33 landmarks → 名前付き (DWPose 18 点辞書と合わせる)
_MP_POSE_INDEX = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
    "left_hip": 23,
    "right_hip": 24,
    "left_knee": 25,
    "right_knee": 26,
    "left_ankle": 27,
    "right_ankle": 28,
}


def _mediapipe_to_dwpose_keypoints(landmarks: Any, image_width: int, image_height: int) -> dict[str, tuple[float, float, float]]:
    """
    MediaPipe 33 点を DWPose 互換の名前付き dict に変換。
    座標は正規化 0〜1 (既存 DWPose 経路の _extract_via_pose_estimation と同じスケール)。
    image_width / image_height は API 互換のため保持 (将来ピクセル化する場合に使用)。
    """
    _ = image_width, image_height
    keypoints: dict[str, tuple[float, float, float]] = {}

    for name, mp_idx in _MP_POSE_INDEX.items():
        if mp_idx >= len(landmarks):
            continue
        lm = landmarks[mp_idx]
        x_n = float(lm.x)
        y_n = float(lm.y)
        vis = getattr(lm, "visibility", None)
        pres = getattr(lm, "presence", None)
        if vis is not None:
            conf = float(vis)
        elif pres is not None:
            conf = float(pres)
        else:
            conf = 1.0
        keypoints[name] = (x_n, y_n, conf)

    if "left_shoulder" in keypoints and "right_shoulder" in keypoints:
        ls = keypoints["left_shoulder"]
        rs = keypoints["right_shoulder"]
        neck_x = (ls[0] + rs[0]) / 2.0
        neck_y = (ls[1] + rs[1]) / 2.0
        neck_conf = (ls[2] + rs[2]) / 2.0
        keypoints["neck"] = (neck_x, neck_y, neck_conf)

    return keypoints


def _extract_keypoints_via_mediapipe(image: Image.Image) -> Optional[dict[str, tuple[float, float, float]]]:
    landmarker = _lazy_init_mediapipe_landmarker()
    if landmarker is None:
        return None

    try:
        img_np = np.asarray(image.convert("RGB"), dtype=np.uint8)
        if img_np.ndim != 3 or img_np.shape[2] != 3:
            return None
        img_np = np.ascontiguousarray(img_np)
        h, w = img_np.shape[0], img_np.shape[1]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_np)
        result = landmarker.detect(mp_image)
        if not result.pose_landmarks:
            logger.warning("[PoseExtractor/MediaPipe] 人物未検出")
            return None
        landmarks = result.pose_landmarks[0]
        keypoints = _mediapipe_to_dwpose_keypoints(landmarks, w, h)
        logger.info("[PoseExtractor/MediaPipe] keypoints=%d", len(keypoints))
        return keypoints if keypoints else None
    except Exception as exc:
        logger.error("[PoseExtractor/MediaPipe] 推論エラー: %s", exc)
        return None


def _normalize_to_range(value: float, low: float, high: float) -> float:
    if high == low:
        return 0.0
    normalized = (value - low) / (high - low) * 2.0 - 1.0
    return max(-1.0, min(1.0, normalized))


def _safe_dist(p1: Optional[tuple], p2: Optional[tuple]) -> Optional[float]:
    if p1 is None or p2 is None:
        return None
    return ((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2) ** 0.5


def _angle_deg(p1: Optional[tuple], p2: Optional[tuple], p3: Optional[tuple]) -> Optional[float]:
    if p1 is None or p2 is None or p3 is None:
        return None
    v1 = (p1[0] - p2[0], p1[1] - p2[1])
    v2 = (p3[0] - p2[0], p3[1] - p2[1])
    mag1 = (v1[0] ** 2 + v1[1] ** 2) ** 0.5
    mag2 = (v2[0] ** 2 + v2[1] ** 2) ** 0.5
    if mag1 == 0 or mag2 == 0:
        return None
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def _to_named_keypoints(body_keypoints: list[Any]) -> dict[str, tuple[float, float, float]]:
    kp_names = [
        "nose",
        "neck",
        "right_shoulder",
        "right_elbow",
        "right_wrist",
        "left_shoulder",
        "left_elbow",
        "left_wrist",
        "right_hip",
        "right_knee",
        "right_ankle",
        "left_hip",
        "left_knee",
        "left_ankle",
        "right_eye",
        "left_eye",
        "right_ear",
        "left_ear",
    ]
    out: dict[str, tuple[float, float, float]] = {}
    for idx, name in enumerate(kp_names):
        if idx >= len(body_keypoints):
            continue
        pt = body_keypoints[idx]
        if not pt or len(pt) < 2:
            continue
        x = float(pt[0])
        y = float(pt[1])
        conf = float(pt[2]) if len(pt) > 2 else 1.0
        out[name] = (x, y, conf)
    return out


def _to_numpy(x: Any) -> np.ndarray:
    if hasattr(x, "detach"):
        x = x.detach().cpu().numpy()
    return np.asarray(x)


def _extract_via_pose_estimation(detector: Any, image: Image.Image) -> Optional[dict[str, tuple[float, float, float]]]:
    """Wholebody / 旧 openpose いずれかの生出力から 18 点を組み立てる。"""
    import cv2

    util = importlib.import_module("controlnet_aux.util")
    HWC3 = util.HWC3
    resize_image = util.resize_image

    rgb = image.convert("RGB")
    arr = np.array(rgb, dtype=np.uint8)
    input_image = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    input_image = HWC3(input_image)
    input_image = resize_image(input_image, 512)
    height, width = input_image.shape[0], input_image.shape[1]

    raw = detector.pose_estimation(input_image)
    if isinstance(raw, tuple) and len(raw) == 2:
        a, b = raw
        ak = _to_numpy(a)
        bk = _to_numpy(b)

        # Wholebody: (persons, joints, 2) + scores — 最終次元が xy のみ
        if ak.ndim == 3 and ak.shape[0] > 0 and ak.shape[-1] == 2:
            j_all = ak[0]
            n_j = min(18, j_all.shape[0])
            if bk.ndim >= 2 and bk.shape[0] > 0:
                s_all = bk[0]
            elif bk.ndim == 1:
                s_all = bk
            else:
                s_all = np.ones(max(n_j, 18), dtype=np.float64)
            pts: list[list[float]] = []
            for i in range(n_j):
                conf = float(s_all[i]) if i < len(s_all) else 1.0
                pts.append(
                    [
                        float(j_all[i, 0]) / float(width),
                        float(j_all[i, 1]) / float(height),
                        conf,
                    ]
                )
            named = _to_named_keypoints(pts)
            return named if named else None

        # 旧 OpenPose candidate / subset (DWposeDetector.__call__ と同じ正規化)
        if ak.ndim == 3 and bk.ndim >= 2:
            try:
                candidate = ak.copy().astype(np.float64)
                subset = bk
                nums, _keys, locs = candidate.shape
                candidate[..., 0] /= float(width)
                candidate[..., 1] /= float(height)
                body = candidate[:, :18].copy().reshape(nums * 18, locs)
                _score = subset[:, :18]
                if body.size > 0:
                    row = body[0]
                    pts2: list[list[float]] = []
                    for j in range(min(18, row.shape[0])):
                        pts2.append([float(row[j, 0]), float(row[j, 1]), 1.0])
                    named = _to_named_keypoints(pts2)
                    return named if named else None
            except Exception as exc:
                logger.warning("[PoseExtractor] candidate/subset parse: %s", exc)

    return None


def _extract_body_kps_from_result(result: Any) -> Optional[list[Any]]:
    if isinstance(result, dict):
        poses = result.get("poses")
        if isinstance(poses, list) and poses:
            p0 = poses[0]
            if isinstance(p0, dict):
                for key in ("body_keypoints", "bodies", "body", "candidate"):
                    val = p0.get(key)
                    if isinstance(val, list) and val:
                        return val
        for key in ("body_keypoints", "bodies", "body", "candidate"):
            val = result.get(key)
            if isinstance(val, list) and val:
                return val

    if isinstance(result, list) and result:
        if isinstance(result[0], (list, tuple, dict)):
            return result
    return None


def _extract_keypoints_via_dwpose(
    image: Image.Image, detector: Any
) -> Optional[dict[str, tuple[float, float, float]]]:
    """既存 DWPose 抽出ロジック (pose_estimation 優先 · detector() フォールバック)。"""
    try:
        named = _extract_via_pose_estimation(detector, image)
        if named:
            return named
    except Exception as exc:
        logger.warning("[PoseExtractor] pose_estimation 経路エラー: %s", exc)

    candidate_results: list[Any] = []
    for kwargs in (
        {"output_type": "json", "include_hand": False, "include_face": False},
        {"output_type": "json"},
        {},
    ):
        try:
            candidate_results.append(detector(image, **kwargs))
        except TypeError:
            continue
        except Exception as exc:
            logger.warning("[PoseExtractor] DWPose 呼び出し失敗 (%s): %s", kwargs, exc)

    for raw in candidate_results:
        body_kps = _extract_body_kps_from_result(raw)
        if body_kps:
            named = _to_named_keypoints(body_kps)
            if named:
                return named
    return None


def _lazy_init_openpose() -> Any:
    """生成側(03 PoseExtractor)と同一の OpenposeDetector を遅延ロード(controlnet_aux/Annotators)。

    RECON-029 Fix A: UI 体型抽出を生成側と同じ検出器スタックに寄せる根治。
    controlnet_aux は既存依存・03 が本番で実証済 = 新規 backend を増やさない。
    """
    global _openpose_detector
    if _openpose_detector is None:
        # 既存 DWPose と同じく submodule 直 import(top-level __init__ 破損環境でも shim 経由で読める)
        _bootstrap_controlnet_aux_shim()
        OpenposeDetector = importlib.import_module("controlnet_aux.open_pose").OpenposeDetector
        logger.info("[PoseExtractor] OpenposeDetector 初期化中 (lllyasviel/Annotators)...")
        _openpose_detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
        logger.info("[PoseExtractor] OpenposeDetector 初期化完了")
    return _openpose_detector


def _extract_keypoints_via_openpose(
    image: Image.Image,
) -> Optional[dict[str, tuple[float, float, float]]]:
    """OpenposeDetector.detect_poses の body 18点を既存 _to_named_keypoints へ流す。

    detect_poses の body.keypoints は OpenPose COCO-18 順(nose,neck,R/L shoulder…ear)で、
    x,y は [0,1] 正規化(x/W, y/H)= DWPose 経路 _extract_via_pose_estimation と同一スケール。
    → _to_named_keypoints(18点名前順一致)→ infer_body_shape に合流。
    """
    detector = _lazy_init_openpose()
    if detector is None:
        return None

    util = importlib.import_module("controlnet_aux.util")
    arr = util.HWC3(np.array(image.convert("RGB"), dtype=np.uint8))  # 生成側 __call__ と同じ前処理
    try:
        poses = detector.detect_poses(arr, include_hand=False, include_face=False)
    except TypeError:
        # 版差で include_* kwargs 非対応 → 位置引数のみで再試行
        poses = detector.detect_poses(arr)

    if not poses:
        logger.warning("[PoseExtractor/OpenPose] 人物未検出 (poses 空)")
        return None
    body = getattr(poses[0], "body", None)
    body_kps = getattr(body, "keypoints", None) if body is not None else None
    if not body_kps:
        logger.warning("[PoseExtractor/OpenPose] body.keypoints が空")
        return None

    pts: list[Any] = []
    for kp in body_kps:
        if kp is None:
            pts.append(None)  # 未検出関節 → _to_named_keypoints が skip
            continue
        x = getattr(kp, "x", None)
        y = getattr(kp, "y", None)
        if x is None or y is None:
            pts.append(None)
            continue
        score = getattr(kp, "score", 1.0)
        pts.append([float(x), float(y), float(score if score is not None else 1.0)])

    named = _to_named_keypoints(pts)
    return named if named else None


def extract_keypoints(image: Image.Image) -> Optional[dict[str, tuple[float, float, float]]]:
    """
    keypoints 抽出。RECON-029 Fix A: 最優先で生成側と同一 OpenposeDetector を試行し、
    失敗時のみ DWPose → MediaPipe Pose Landmarker にフォールバック。
    """
    global _last_used_backend
    _last_used_backend = "none"

    # 脚0(最優先・RECON-029 Fix A 根治): 生成側と同一 OpenposeDetector(本番に確実に存在)。
    #   これにより検出器スタック分岐が解消 = 全身画像での 422 が原理的に消える。
    try:
        kp_op = _extract_keypoints_via_openpose(image)
        if kp_op:
            _last_used_backend = "openpose"
            logger.info(
                "[PoseExtractor] backend=openpose keypoints=%d (生成側と同一 OpenposeDetector で抽出成功)",
                len(kp_op),
            )
            return kp_op
        logger.warning("[PoseExtractor] OpenposeDetector 抽出失敗 (空) → DWPose/MediaPipe へフォールバック")
    except Exception as exc:
        logger.warning(
            "[PoseExtractor] OpenposeDetector 例外 → DWPose/MediaPipe へフォールバック: %s: %s",
            type(exc).__name__,
            exc,
        )

    try:
        detector = _lazy_init_dwpose()
        kp = _extract_keypoints_via_dwpose(image, detector)
        if kp:
            _last_used_backend = "dwpose"
            logger.info(
                "[PoseExtractor] backend=dwpose keypoints=%d (DWPose 経路で抽出成功)",
                len(kp),
            )
            return kp
        logger.warning("[PoseExtractor] DWPose 抽出失敗 (空) → MediaPipe へフォールバック")
    except (NameError, ImportError, AttributeError, RuntimeError) as exc:
        logger.warning(
            "[PoseExtractor] DWPose 例外 → MediaPipe へフォールバック: %s: %s",
            type(exc).__name__,
            exc,
        )
    except Exception as exc:
        logger.warning("[PoseExtractor] DWPose 想定外例外 → MediaPipe へフォールバック: %s", exc)

    if _MEDIAPIPE_AVAILABLE:
        kp_mp = _extract_keypoints_via_mediapipe(image)
        if kp_mp:
            _last_used_backend = "mediapipe"
            logger.info(
                "[PoseExtractor] backend=mediapipe keypoints=%d (MediaPipe 経路で抽出成功)",
                len(kp_mp),
            )
            return kp_mp
    else:
        logger.error("[PoseExtractor] MediaPipe 未インストール · フォールバック不可")

    logger.error("[PoseExtractor] DWPose / MediaPipe 両方失敗")
    return None


def _infer_base_x(kp: dict) -> tuple[float, float]:
    ls, rs, lh, rh = kp.get("left_shoulder"), kp.get("right_shoulder"), kp.get("left_hip"), kp.get("right_hip")
    if not all([ls, rs, lh, rh]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    hip_width = _safe_dist(lh, rh)
    if not shoulder_width or not hip_width:
        return 0.0, 0.3
    ratio = shoulder_width / max(hip_width, 1e-6)
    value = _normalize_to_range(ratio, 0.9, 1.5)
    conf = (ls[2] + rs[2] + lh[2] + rh[2]) / 4.0
    return value, conf


def _infer_base_y(_kp: dict) -> tuple[float, float]:
    return 0.0, 0.3


def _infer_proportion_x(kp: dict) -> tuple[float, float]:
    nose, neck = kp.get("nose"), kp.get("neck")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not nose or not neck or not foot:
        return 0.0, 0.3
    head_height = _safe_dist(nose, neck)
    full_height = _safe_dist(nose, foot)
    if not head_height or not full_height:
        return 0.0, 0.3
    ratio = head_height / max(full_height, 1e-6)
    value = -_normalize_to_range(ratio, 0.10, 0.18)
    conf = (nose[2] + neck[2] + foot[2]) / 3.0
    return value, conf


def _infer_proportion_y(kp: dict) -> tuple[float, float]:
    nose, neck = kp.get("nose"), kp.get("neck")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not nose or not neck or not foot:
        return 0.0, 0.3
    head_height = _safe_dist(nose, neck) * 1.5
    full_height = _safe_dist(nose, foot)
    if not head_height or not full_height:
        return 0.0, 0.3
    head_count = full_height / max(head_height, 1e-6)
    value = _normalize_to_range(head_count, 7.0, 8.5)
    conf = (nose[2] + neck[2] + foot[2]) / 3.0
    return value, conf


def _infer_silhouette_x(kp: dict) -> tuple[float, float]:
    ls, rs, lh, rh = kp.get("left_shoulder"), kp.get("right_shoulder"), kp.get("left_hip"), kp.get("right_hip")
    nose = kp.get("nose")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not all([ls, rs, lh, rh, nose, foot]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    hip_width = _safe_dist(lh, rh)
    full_height = _safe_dist(nose, foot)
    if not shoulder_width or not hip_width or not full_height:
        return 0.0, 0.3
    avg_width = (shoulder_width + hip_width) / 2
    width_ratio = avg_width / max(full_height, 1e-6)
    return _normalize_to_range(width_ratio, 0.20, 0.32), 0.5


def _infer_silhouette_y(kp: dict) -> tuple[float, float]:
    nose, neck = kp.get("nose"), kp.get("neck")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not nose or not neck or not foot:
        return 0.0, 0.3
    head_height = _safe_dist(nose, neck) * 1.5
    full_height = _safe_dist(nose, foot)
    if not head_height or not full_height:
        return 0.0, 0.3
    head_count = full_height / max(head_height, 1e-6)
    return _normalize_to_range(head_count, 6.5, 8.5), 0.4


def _infer_curves_x(kp: dict) -> tuple[float, float]:
    ls, rs, lh, rh = kp.get("left_shoulder"), kp.get("right_shoulder"), kp.get("left_hip"), kp.get("right_hip")
    nose = kp.get("nose")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not all([ls, rs, lh, rh, nose, foot]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    hip_width = _safe_dist(lh, rh)
    full_height = _safe_dist(nose, foot)
    if not shoulder_width or not hip_width or not full_height:
        return 0.0, 0.3
    avg_width = (shoulder_width + hip_width) / 2
    width_ratio = avg_width / max(full_height, 1e-6)
    return _normalize_to_range(width_ratio, 0.18, 0.30), 0.4


def _infer_curves_y(kp: dict) -> tuple[float, float]:
    ls, rs, lh, rh = kp.get("left_shoulder"), kp.get("right_shoulder"), kp.get("left_hip"), kp.get("right_hip")
    if not all([ls, rs, lh, rh]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    hip_width = _safe_dist(lh, rh)
    if not shoulder_width or not hip_width:
        return 0.0, 0.3
    ratio = shoulder_width / max(hip_width, 1e-6)
    deviation = abs(ratio - 1.0)
    return _normalize_to_range(deviation, 0.0, 0.25), 0.3


def _infer_posture_x(kp: dict) -> tuple[float, float]:
    nose, neck = kp.get("nose"), kp.get("neck")
    lh, rh = kp.get("left_hip"), kp.get("right_hip")
    if not nose or not neck or (not lh and not rh):
        return 0.0, 0.3
    if lh and rh:
        mid_hip = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2)
    else:
        mid_hip = lh or rh
    angle = _angle_deg(nose, neck, mid_hip)
    if angle is None:
        return 0.0, 0.3
    value = _normalize_to_range(angle, 150.0, 180.0)
    conf = (nose[2] + neck[2]) / 2.0
    return value, conf


def _infer_posture_y(kp: dict) -> tuple[float, float]:
    ls, rs = kp.get("left_shoulder"), kp.get("right_shoulder")
    nose = kp.get("nose")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not all([ls, rs, nose, foot]):
        return 0.0, 0.3
    full_height = _safe_dist(nose, foot)
    if not full_height:
        return 0.0, 0.3
    relative_y_diff = abs(ls[1] - rs[1]) / max(full_height, 1e-6)
    value = -_normalize_to_range(relative_y_diff, 0.0, 0.05)
    conf = (ls[2] + rs[2]) / 2.0
    return value, conf


def _infer_hips_x(kp: dict) -> tuple[float, float]:
    """HIP「細い腰 ⇔ ふくよか」= ヒップ/肩 比。keypoint だけで堅牢(既存 base_x と同方式)。"""
    ls, rs = kp.get("left_shoulder"), kp.get("right_shoulder")
    lh, rh = kp.get("left_hip"), kp.get("right_hip")
    if not all([ls, rs, lh, rh]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    hip_width = _safe_dist(lh, rh)
    if not shoulder_width or not hip_width:
        return 0.0, 0.3
    ratio = hip_width / max(shoulder_width, 1e-6)        # ヒップ/肩 比
    value = _normalize_to_range(ratio, 0.75, 1.15)       # 既存軸と同じ _normalize_to_range(実機 1shot で調整可)
    conf = (ls[2] + rs[2] + lh[2] + rh[2]) / 4.0
    return value, conf


def _infer_hips_y(_kp: dict) -> tuple[float, float]:
    """HIP「ヒップ位置 低 ⇔ 高」。keypoint からの安定推定が難しいため手動のみ(0固定)。
    既存 _infer_base_y と同じく low-conf の 0 を返す(スライダー手動編集可・辞書側で y を解釈)。"""
    return 0.0, 0.3


def _infer_shoulder_x(kp: dict) -> tuple[float, float]:
    """SHOULDER「狭い肩 ⇔ 広い肩」= 肩幅/身長 比(§5)。keypoint だけで堅牢。"""
    ls, rs = kp.get("left_shoulder"), kp.get("right_shoulder")
    nose = kp.get("nose")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not all([ls, rs, nose, foot]):
        return 0.0, 0.3
    shoulder_width = _safe_dist(ls, rs)
    full_height = _safe_dist(nose, foot)
    if not shoulder_width or not full_height:
        return 0.0, 0.3
    ratio = shoulder_width / max(full_height, 1e-6)       # 肩幅/身長(肩幅基準=身長)
    value = _normalize_to_range(ratio, 0.18, 0.28)        # 実機 1shot で調整可
    conf = (ls[2] + rs[2]) / 2.0
    return value, conf


def _infer_shoulder_y(kp: dict) -> tuple[float, float]:
    """SHOULDER「なで肩 ⇔ いかり肩」= 左右肩 keypoint の Y 差(傾き)(§5)。
    NOTE: frontal 対称姿勢では ~0(中央)に寄る弱信号。値が出ない場合は手動調整で補う。
    左右非対称(肩ライン傾斜)時に いかり肩側へ寄る符号。要・実機検証(司令部レビュー対象)。"""
    ls, rs = kp.get("left_shoulder"), kp.get("right_shoulder")
    nose = kp.get("nose")
    foot = kp.get("left_ankle") or kp.get("right_ankle")
    if not all([ls, rs, nose, foot]):
        return 0.0, 0.3
    full_height = _safe_dist(nose, foot)
    if not full_height:
        return 0.0, 0.3
    rel = abs(ls[1] - rs[1]) / max(full_height, 1e-6)     # 左右肩の Y 差(正規化)
    value = _normalize_to_range(rel, 0.0, 0.05)
    conf = (ls[2] + rs[2]) / 2.0
    return value, conf


def _infer_legs_x(kp: dict) -> tuple[float, float]:
    """LEGS「短い脚 ⇔ 長い脚」= (hip→ankle 長)/胴長(neck→hip)比(§5)。"""
    lh, rh = kp.get("left_hip"), kp.get("right_hip")
    neck = kp.get("neck")
    ankle = kp.get("left_ankle") or kp.get("right_ankle")
    if lh and rh:
        hip = ((lh[0] + rh[0]) / 2, (lh[1] + rh[1]) / 2, (lh[2] + rh[2]) / 2)
    else:
        hip = lh or rh
    if not hip or not neck or not ankle:
        return 0.0, 0.3
    leg_len = _safe_dist(hip, ankle)
    torso_len = _safe_dist(neck, hip)
    if not leg_len or not torso_len:
        return 0.0, 0.3
    ratio = leg_len / max(torso_len, 1e-6)                # 脚長/胴長
    value = _normalize_to_range(ratio, 1.1, 1.7)          # 実機 1shot で調整可
    conf = (hip[2] + ankle[2]) / 2.0
    return value, conf


def infer_body_shape(keypoints: dict[str, tuple[float, float, float]]) -> tuple[dict[str, dict[str, float]], float]:
    # §5 再キー: proportion.x=頭身(旧 proportion.y の算出), legs.x=脚長, shoulder.x/y=新規。
    base_x = _infer_base_x(keypoints)
    base_y = _infer_base_y(keypoints)
    proportion_x = _infer_proportion_y(keypoints)   # §5: 頭身算出を PROPORTION.x へ
    silhouette_x = _infer_silhouette_x(keypoints)   # §3: メリハリ(現状の算出を維持)
    curves_x = _infer_curves_x(keypoints)
    curves_y = _infer_curves_y(keypoints)
    posture_x = _infer_posture_x(keypoints)
    posture_y = _infer_posture_y(keypoints)
    hips_x = _infer_hips_x(keypoints)
    hips_y = _infer_hips_y(keypoints)
    shoulder_x = _infer_shoulder_x(keypoints)
    shoulder_y = _infer_shoulder_y(keypoints)
    legs_x = _infer_legs_x(keypoints)

    extracted = [
        base_x, base_y, proportion_x, silhouette_x, curves_x, curves_y,
        posture_x, posture_y, hips_x, hips_y, shoulder_x, shoulder_y, legs_x,
    ]
    axis_confidences = [max(0.0, min(1.0, c)) for _, c in extracted]

    # §5 手動キー(proportion.y / silhouette.y / legs.y / bust.*)は **含めない**。
    #     抽出 result は「抽出できた軸のみの partial dict」。後段(server→フロント)で
    #     per-axis マージし、手動値/初期値を保持する。
    body_shape = {
        "base": {"x": base_x[0], "y": base_y[0]},
        "proportion": {"x": proportion_x[0]},
        "silhouette": {"x": silhouette_x[0]},
        "curves": {"x": curves_x[0], "y": curves_y[0]},
        "posture": {"x": posture_x[0], "y": posture_y[0]},
        "hips": {"x": hips_x[0], "y": hips_y[0]},
        "shoulder": {"x": shoulder_x[0], "y": shoulder_y[0]},
        "legs": {"x": legs_x[0]},
    }
    overall_conf = sum(axis_confidences) / len(axis_confidences) if axis_confidences else 0.0
    return body_shape, overall_conf


def _zero_body_shape() -> dict[str, dict[str, float]]:
    return {
        "base": {"x": 0.0, "y": 0.0},
        "proportion": {"x": 0.0, "y": 0.0},
        "silhouette": {"x": 0.0, "y": 0.0},
        "curves": {"x": 0.0, "y": 0.0},
        "posture": {"x": 0.0, "y": 0.0},
        "hips": {"x": 0.0, "y": 0.0},
    }


def extract_body_shape_from_image(image: Image.Image) -> BodyShapeResult:
    global _last_used_backend
    errors: list[str] = []
    warnings: list[str] = []
    _last_used_backend = "none"

    if image is None or image.size[0] < 64 or image.size[1] < 64:
        errors.append("invalid_image")
        return BodyShapeResult(
            body_shape=_zero_body_shape(),
            confidence=0.0,
            keypoints_count=0,
            person_detected=False,
            errors=errors,
            warnings=warnings,
            backend="none",
        )

    try:
        keypoints = extract_keypoints(image)
    except ImportError:
        errors.append("dwpose_unavailable")
        logger.error("[PoseExtractor] controlnet_aux が見つかりません")
        return BodyShapeResult(
            body_shape=_zero_body_shape(),
            confidence=0.0,
            keypoints_count=0,
            person_detected=False,
            errors=errors,
            warnings=warnings,
            backend="none",
        )
    except Exception as exc:
        errors.append("pose_runtime_error")
        logger.exception("[PoseExtractor] runtime error: %s", exc)
        return BodyShapeResult(
            body_shape=_zero_body_shape(),
            confidence=0.0,
            keypoints_count=0,
            person_detected=False,
            errors=errors,
            warnings=warnings,
            backend="none",
        )

    if keypoints is None or len(keypoints) < 3:
        errors.append("person_not_detected")
        return BodyShapeResult(
            body_shape=_zero_body_shape(),
            confidence=0.0,
            keypoints_count=0,
            person_detected=False,
            errors=errors,
            warnings=warnings,
            backend=_last_used_backend,
        )

    required = ["nose", "neck", "left_shoulder", "right_shoulder", "left_hip", "right_hip"]
    missing = [k for k in required if k not in keypoints]
    if missing:
        warnings.append(f"missing_keypoints:{','.join(missing)}")
        if len(missing) >= 4:
            errors.append("insufficient_keypoints")
            return BodyShapeResult(
                body_shape=_zero_body_shape(),
                confidence=0.2,
                keypoints_count=len(keypoints),
                person_detected=True,
                errors=errors,
                warnings=warnings,
                backend=_last_used_backend,
            )

    body_shape, confidence = infer_body_shape(keypoints)
    if confidence < 0.4:
        warnings.append("low_confidence")

    logger.info(
        "[PoseExtractor] backend=%s keypoints=%d confidence=%.2f",
        _last_used_backend,
        len(keypoints),
        confidence,
    )
    return BodyShapeResult(
        body_shape=body_shape,
        confidence=confidence,
        keypoints_count=len(keypoints),
        person_detected=True,
        errors=errors,
        warnings=warnings,
        backend=_last_used_backend,
    )
