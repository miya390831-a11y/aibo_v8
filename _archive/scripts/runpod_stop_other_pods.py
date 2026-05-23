"""新規 Pod 以外の fullstack 相当 Pod を podStop する（課金停止用）。"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
FULLSTACK_IMAGE_SUBSTR = "aibo-studio-v8-full"
API_URL = "https://api.runpod.io/graphql"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k == "RUNPOD_API_KEY" and v and not os.environ.get(k, "").strip():
            os.environ[k] = v


def graphql(headers: dict, query: str, variables: dict | None = None) -> dict:
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables
    r = requests.post(API_URL, json=payload, headers=headers, timeout=120)
    r.raise_for_status()
    return r.json()


def main() -> int:
    _load_dotenv(SCRIPT_DIR / ".env")
    if len(sys.argv) < 2:
        print("usage: runpod_stop_other_pods.py <keepPodId>", file=sys.stderr)
        return 1
    keep_id = sys.argv[1].strip()
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        print("RUNPOD_API_KEY missing", file=sys.stderr)
        return 1

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    q = """
    query {
      myself {
        pods { id name imageName desiredStatus }
        backgroundPods { id name imageName desiredStatus }
      }
    }
    """
    out = graphql(headers, q)
    if out.get("errors"):
        print(json.dumps(out["errors"], indent=2), file=sys.stderr)
        return 1
    myself = (out.get("data") or {}).get("myself") or {}
    seen: set[str] = set()
    pods: list[dict] = []
    for key in ("pods", "backgroundPods"):
        for p in myself.get(key) or []:
            pid = p.get("id") or ""
            if pid and pid not in seen:
                seen.add(pid)
                pods.append(p)

    mut = """
    mutation ($podId: String!) {
      podStop(input: { podId: $podId, incrementVersion: false }) {
        id
        desiredStatus
        name
      }
    }
    """

    stopped = 0
    for p in pods:
        pid = p.get("id") or ""
        if not pid or pid == keep_id:
            continue
        img = ((p.get("imageName") or "") + " " + (p.get("name") or "")).lower()
        if FULLSTACK_IMAGE_SUBSTR.lower() not in img:
            continue
        status = p.get("desiredStatus") or ""
        if str(status).upper() in ("STOPPED", "EXITED", "TERMINATED"):
            print(f"skip (already stopped) {pid} {p.get('name')!r}")
            continue
        print(f"podStop {pid} name={p.get('name')!r} image={p.get('imageName')!r} status={status}")
        r2 = graphql(headers, mut, {"podId": pid})
        if r2.get("errors"):
            print(json.dumps(r2["errors"], indent=2)[:1500], file=sys.stderr)
        else:
            print(json.dumps(r2.get("data"), indent=2)[:800])
            stopped += 1

    print(f"Done. podStop issued for {stopped} pod(s). Kept {keep_id!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
