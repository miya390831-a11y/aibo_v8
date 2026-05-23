"""RunPod REST: 既存 Pod の env をマージ更新（PATCH は Pod リセットを伴う場合あり）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not k or not v:
            continue
        if os.environ.get(k, "").strip():
            continue
        os.environ[k] = v


def main() -> int:
    _load_dotenv(SCRIPT_DIR / ".env")
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        print("RUNPOD_API_KEY missing (.env or environment).", file=sys.stderr)
        return 1
    if len(sys.argv) < 2:
        print("usage: runpod_patch_pod_env.py <podId>", file=sys.stderr)
        return 1
    pod_id = sys.argv[1].strip()

    hf = (
        os.environ.get("PATCH_HUGGINGFACE_HUB_TOKEN")
        or os.environ.get("HUGGINGFACE_HUB_TOKEN")
        or ""
    ).strip()
    hf_alt = (os.environ.get("PATCH_HF_TOKEN") or os.environ.get("HF_TOKEN") or "").strip()
    if not hf and hf_alt:
        hf = hf_alt
    if not hf:
        print("HUGGINGFACE_HUB_TOKEN / HF_TOKEN missing.", file=sys.stderr)
        return 1
    if not hf_alt:
        hf_alt = hf

    base = "https://rest.runpod.io/v1"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    r = requests.get(f"{base}/pods/{pod_id}", headers=headers, timeout=90)
    if r.status_code != 200:
        print(f"GET pod failed {r.status_code}: {r.text[:500]}", file=sys.stderr)
        return 1
    body = r.json()
    cur_env = body.get("env") or {}
    if not isinstance(cur_env, dict):
        cur_env = {}
    merged = dict(cur_env)
    merged["HUGGINGFACE_HUB_TOKEN"] = hf
    merged["HF_TOKEN"] = hf_alt

    patch = {"env": merged}
    r2 = requests.patch(
        f"{base}/pods/{pod_id}",
        headers=headers,
        data=json.dumps(patch),
        timeout=120,
    )
    print(f"PATCH status={r2.status_code}", flush=True)
    try:
        j = r2.json()
        if isinstance(j.get("env"), dict):
            j["env"] = {k: ("<set>" if v else "") for k, v in j["env"].items()}
        print(json.dumps(j, indent=2, ensure_ascii=False)[:4000], flush=True)
    except Exception:
        print((r2.text or "")[:500], flush=True)
    return 0 if r2.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
