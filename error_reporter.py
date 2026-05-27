"""
AIBO Cyber Studio · 生成エラー自動記録モジュール

生成失敗時に Drive へ詳細ログを自動保存し、
Claude Code (PC 側) からの解析・修復ループの入口を提供する。

設計原則:
  - 個人情報 (顔画像 base64 等) は記録しない
  - JSON (機械可読) + Markdown (人間可読) の両形式
  - error_reporter 自体の失敗で生成処理を止めない
  - Drive 未マウントでもローカル保存で動作継続
"""

from __future__ import annotations

import json
import shutil
import sys
import traceback
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, Optional

# ============================================================
# Paths
# ============================================================
DRIVE_ERROR_DIR = Path("/content/drive/MyDrive/aibo_v7/logs/errors")
LOCAL_ERROR_DIR = Path("/content/aibo_v7/logs/errors")

for _d in [DRIVE_ERROR_DIR, LOCAL_ERROR_DIR]:
    try:
        _d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


# ============================================================
# サニタイズ
# ============================================================
_SENSITIVE_KEYS = {
    "reference_image", "image_data", "face_image",
    "init_image", "mask_image", "image", "img",
    "base64", "image_base64", "ref_image_base64",
    "face_references", "reference_images",
}


def _sanitize_value(key: str, value: Any) -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        if isinstance(value, str) and len(value) > 100:
            return f"<image data omitted · {len(value)} chars>"
        if isinstance(value, (list, tuple)) and value:
            return f"<{len(value)} image(s) omitted>"
        return "<omitted>"
    if isinstance(value, str) and len(value) > 1000:
        return f"{value[:200]}... <truncated · {len(value)} chars>"
    if isinstance(value, dict):
        return {k: _sanitize_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) and len(value) > 20:
        return [_sanitize_value("", v) for v in value[:20]] + [f"<+{len(value)-20} more>"]
    return value


def _sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    if not data:
        return {}
    return {k: _sanitize_value(k, v) for k, v in data.items()}


# ============================================================
# システム状態取得
# ============================================================
def _get_system_state() -> Dict[str, Any]:
    state: Dict[str, Any] = {}
    try:
        import torch
        if torch.cuda.is_available():
            state["vram_used_gb"] = round(torch.cuda.memory_allocated() / 1e9, 2)
            state["vram_reserved_gb"] = round(torch.cuda.memory_reserved() / 1e9, 2)
            props = torch.cuda.get_device_properties(0)
            state["vram_total_gb"] = round(props.total_memory / 1e9, 2)
            state["gpu_name"] = props.name
    except Exception as e:
        state["vram_error"] = str(e)
    try:
        import psutil
        mem = psutil.virtual_memory()
        state["ram_used_gb"] = round(mem.used / 1e9, 2)
        state["ram_total_gb"] = round(mem.total / 1e9, 2)
    except Exception:
        pass
    return state


# ============================================================
# AIBO Config 取得
# ============================================================
def _get_aibo_config(context: Optional[Dict] = None) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    _keys = [
        "GFPGAN_STRENGTH", "ip_adapter_weight",
        "pulid_sigma_start", "pulid_sigma_end",
        "cn_depth_guidance_end", "pass2_strength", "pass2_pulid_boost",
        "guidance_scale", "num_inference_steps",
    ]
    if context:
        for key in _keys:
            if key in context:
                config[key] = context[key]
    if not config:
        try:
            mod = import_module("01_config")
            for key in _keys:
                if hasattr(mod, key):
                    config[key] = getattr(mod, key)
        except Exception as e:
            config["_config_error"] = str(e)
    return config


# ============================================================
# 保存処理
# ============================================================
def save_error_report(
    error: Exception,
    context: Optional[Dict[str, Any]] = None,
    request_data: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
    phase: Optional[str] = None,
) -> Optional[Path]:
    """生成エラーを Drive に自動保存。失敗しても呼び出し元に例外を伝播しない。"""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        request_id = request_id or f"req_{timestamp}"

        report = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id,
                "aibo_version": "v7.4.0",
                "phase": phase or "unknown",
            },
            "error": {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
            "context": {
                "config": _get_aibo_config(context),
                "system": _get_system_state(),
                "extra": _sanitize_dict(context or {}),
            },
            "request": _sanitize_dict(request_data or {}),
        }

        # JSON 保存 (Drive 優先 → ローカル fallback)
        json_path = DRIVE_ERROR_DIR / f"error_{timestamp}_{request_id}.json"
        try:
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except Exception:
            json_path = LOCAL_ERROR_DIR / f"error_{timestamp}_{request_id}.json"
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(
                json.dumps(report, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        # Markdown 保存
        try:
            _write_markdown_report(json_path.with_suffix(".md"), report)
        except Exception:
            pass

        # ローカルにもコピー
        try:
            if json_path.parent != LOCAL_ERROR_DIR:
                LOCAL_ERROR_DIR.mkdir(parents=True, exist_ok=True)
                shutil.copy2(json_path, LOCAL_ERROR_DIR / json_path.name)
                md = json_path.with_suffix(".md")
                if md.exists():
                    shutil.copy2(md, LOCAL_ERROR_DIR / md.name)
        except Exception:
            pass

        print(
            f"\n{'⚠️' * 20}\n"
            f"⚠️ AIBO 生成エラーが記録されました:\n"
            f"   {json_path}\n"
            f"   PC: G:\\マイドライブ\\aibo_v7\\logs\\errors\\\n"
            f"   🔬 デスクトップの 'AIBO Error Diagnostic' で自動解析可能\n"
            f"{'⚠️' * 20}\n",
            file=sys.stderr,
        )
        return json_path

    except Exception as e:
        print(f"❌ error_reporter 内部エラー (無視): {e}", file=sys.stderr)
        return None


def _write_markdown_report(path: Path, report: Dict[str, Any]) -> None:
    md = report["metadata"]
    err = report["error"]
    ctx = report["context"]

    content = f"""# AIBO 生成エラーレポート

**Timestamp**: {md['timestamp']}
**Request ID**: `{md['request_id']}`
**Phase**: `{md['phase']}`

---

## エラー詳細

**Type**: `{err['type']}`

**Message**:
```
{err['message']}
```

**Traceback**:
```python
{err['traceback']}
```

---

## Config

```json
{json.dumps(ctx['config'], indent=2, ensure_ascii=False)}
```

## System State

```json
{json.dumps(ctx['system'], indent=2, ensure_ascii=False)}
```

## Request Data (機微情報除外済)

```json
{json.dumps(report.get('request', {}), indent=2, ensure_ascii=False)}
```

---

Generated by AIBO error_reporter
"""
    path.write_text(content, encoding="utf-8")


# ============================================================
# Context Manager
# ============================================================
class ErrorCapture:
    """
    with ErrorCapture(phase="phase1", request_id="req_123") as cap:
        cap.context["pipeline_mode"] = "pulid"
        result = generate(...)
    """

    def __init__(
        self,
        phase: str = "unknown",
        request_id: Optional[str] = None,
        request_data: Optional[Dict] = None,
        reraise: bool = True,
    ):
        self.phase = phase
        self.request_id = request_id
        self.request_data = request_data
        self.reraise = reraise
        self.context: Dict[str, Any] = {}
        self.error_path: Optional[Path] = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            self.error_path = save_error_report(
                error=exc_val,
                context=self.context,
                request_data=self.request_data,
                request_id=self.request_id,
                phase=self.phase,
            )
            if not self.reraise:
                return True
        return False


# ============================================================
# 最新エラー取得 (API 用)
# ============================================================
def get_latest_error() -> Optional[Dict[str, Any]]:
    try:
        latest_file: Optional[Path] = None
        latest_mtime = 0.0
        for d in [DRIVE_ERROR_DIR, LOCAL_ERROR_DIR]:
            if not d.exists():
                continue
            for f in d.glob("error_*.json"):
                mt = f.stat().st_mtime
                if mt > latest_mtime:
                    latest_mtime = mt
                    latest_file = f
        if not latest_file:
            return None
        return json.loads(latest_file.read_text(encoding="utf-8"))
    except Exception as e:
        return {"_error": f"get_latest_error failed: {e}"}


def list_recent_errors(limit: int = 10) -> list:
    try:
        files = []
        for d in [DRIVE_ERROR_DIR, LOCAL_ERROR_DIR]:
            if d.exists():
                files.extend(d.glob("error_*.json"))
        seen = set()
        unique = []
        for f in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            if f.name not in seen:
                seen.add(f.name)
                unique.append(f)
        results = []
        for f in unique[:limit]:
            try:
                r = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "filename": f.name,
                    "timestamp": r["metadata"]["timestamp"],
                    "phase": r["metadata"]["phase"],
                    "error_type": r["error"]["type"],
                    "error_message": r["error"]["message"][:200],
                })
            except Exception:
                pass
        return results
    except Exception as e:
        return [{"_error": str(e)}]
