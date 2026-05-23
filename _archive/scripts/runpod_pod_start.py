"""POST /v1/pods/{id}/start — 停止中 Pod の再開。"""
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
        print("RUNPOD_API_KEY missing.", file=sys.stderr)
        return 1
    if len(sys.argv) < 2:
        print("usage: runpod_pod_start.py <podId>", file=sys.stderr)
        return 1
    pod_id = sys.argv[1].strip()
    r = requests.post(
        f"https://rest.runpod.io/v1/pods/{pod_id}/start",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120,
    )
    print(f"POST /start status={r.status_code}", flush=True)
    try:
        j = r.json()
        if isinstance(j.get("env"), dict):
            j["env"] = {k: ("<set>" if v else "") for k, v in j["env"].items()}
        print(json.dumps(j, indent=2, ensure_ascii=False)[:4000], flush=True)
    except Exception:
        print((r.text or "")[:500], flush=True)
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
