"""RunPod fullstack Pod デプロイ (Next.js :3000 + FastAPI :8000)"""
import json
import os
import sys
from pathlib import Path

import requests

_SCRIPT_DIR = Path(__file__).resolve().parent

API_KEY = os.environ.get("RUNPOD_API_KEY", "").strip()
API_URL = "https://api.runpod.io/graphql"
HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}

IMAGE = "ghcr.io/miya390831-a11y/aibo-studio-v8-full:latest"
REGISTRY_AUTH_ID = "cmp8hgy2x000dl2076m4ck734"
PREFERRED_GPU_IDS = ["NVIDIA A40", "NVIDIA RTX A6000", "NVIDIA RTX 6000 Ada Generation"]
# 単一 GPU を優先したいとき: DEPLOY_GPU_ID=NVIDIA A40（既定も A40）
DEPLOY_GPU_ID = (os.environ.get("DEPLOY_GPU_ID") or "NVIDIA A40").strip()
# カンマ区切りで複数指定可。既定は直近で使った fullstack Pod 群。
TERMINATE_OLD = os.environ.get(
    "TERMINATE_OLD_POD",
    "xed64txqg15j30,8rv5rl9ez3wfef,u55cyi0bmuthbg,rgigk6czigch55,6e32flpf4bwvko,tw6iovh7tvkfrp,jdfstef5w61dba,z8ftqbw7zhnl1j,1fnpzz8cliihlz",
)


_DOTENV_KEYS = ("HUGGINGFACE_HUB_TOKEN", "HF_TOKEN", "RUNPOD_API_KEY")


def _load_dotenv_secrets(path: Path) -> int:
    """aibo_v7/.env からシークレットを読み込む（既に os.environ にあるキーは上書きしない）。適用した行数を返す。"""
    if not path.is_file():
        return 0
    applied = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key not in _DOTENV_KEYS:
            continue
        if not val:
            continue
        if os.environ.get(key, "").strip():
            continue
        os.environ[key] = val
        applied += 1
    return applied


def _pod_env():
    """Pod 環境。HF はホストの HUGGINGFACE_HUB_TOKEN または HF_TOKEN から転送。"""
    env = [
        {"key": "NODE_ENV", "value": "production"},
        {"key": "PORT", "value": "3000"},
        {"key": "HOSTNAME", "value": "0.0.0.0"},
        {"key": "NEXT_PUBLIC_API_URL", "value": ""},
        {"key": "NEXT_PUBLIC_USE_RELATIVE_API", "value": "true"},
    ]
    tok = (os.environ.get("HUGGINGFACE_HUB_TOKEN") or os.environ.get("HF_TOKEN") or "").strip()
    if tok:
        env.append({"key": "HUGGINGFACE_HUB_TOKEN", "value": tok})
        env.append({"key": "HF_TOKEN", "value": tok})
    # Pod 起動時に Nunchaku 経路へ固定（ホストの AIBO_STRATEGY_OVERRIDE があればそれを優先）
    env.append(
        {
            "key": "AIBO_STRATEGY_OVERRIDE",
            "value": (os.environ.get("AIBO_STRATEGY_OVERRIDE") or "a100_40gb_nunchaku").strip(),
        }
    )
    return env


def graphql(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=90)
    except requests.RequestException as e:
        print(f"graphql request failed: {e}", file=sys.stderr)
        return {}
    try:
        out = resp.json()
    except ValueError:
        snippet = (resp.text or "")[:800]
        print(
            f"graphql invalid JSON (HTTP {resp.status_code}): {snippet!r}",
            file=sys.stderr,
        )
        return {}
    if out.get("errors"):
        print(
            "graphql errors:",
            json.dumps(out["errors"], indent=2, ensure_ascii=False),
            file=sys.stderr,
        )
    if "data" not in out:
        print(
            "graphql response without 'data' key:",
            json.dumps(out, indent=2, ensure_ascii=False)[:2000],
            file=sys.stderr,
        )
    return out


def terminate(pod_id: str):
    q = 'mutation { podTerminate(input: { podId: "%s" }) }' % pod_id
    return graphql(q)


def create_pod(gpu_type_id: str):
    m = """
    mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
      podFindAndDeployOnDemand(input: $input) {
        id name costPerHr desiredStatus
        machine { podHostId }
      }
    }
    """
    variables = {
        "input": {
            "gpuTypeId": gpu_type_id,
            "gpuCount": 1,
            "name": "aibo-studio-v8-full",
            "imageName": IMAGE,
            "containerDiskInGb": 80,
            "ports": "3000/http,8000/http",
            "containerRegistryAuthId": REGISTRY_AUTH_ID,
            "env": _pod_env(),
            "startSsh": False,
        }
    }
    return graphql(m, variables)


def main():
    global HEADERS

    n = _load_dotenv_secrets(_SCRIPT_DIR / ".env")
    if n:
        print(
            f"環境変数を {_SCRIPT_DIR / '.env'} から読み込みました（{n} 件・既存の env は上書きしません）",
            flush=True,
        )

    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    HEADERS = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    if not api_key:
        print(
            "Set RUNPOD_API_KEY in the environment or in .env next to this script.",
            file=sys.stderr,
        )
        return 1

    if not (
        (os.environ.get("HUGGINGFACE_HUB_TOKEN") or "").strip()
        or (os.environ.get("HF_TOKEN") or "").strip()
    ):
        print(
            "警告: ローカルに HUGGINGFACE_HUB_TOKEN / HF_TOKEN がありません。"
            "Pod にも渡されず、Phase C（FLUX 等）で認証エラーになる可能性があります。",
            file=sys.stderr,
        )

    for pid in [p.strip() for p in TERMINATE_OLD.split(",") if p.strip()]:
        print(f"Terminating old pod {pid}...")
        print(json.dumps(terminate(pid), indent=2))

    gpu_resp = graphql(
        "{ gpuTypes { id displayName memoryInGb maxGpuCount securePrice } }"
    )
    gpu_types = (gpu_resp.get("data") or {}).get("gpuTypes")
    order = []
    if isinstance(gpu_types, list) and gpu_types:
        available = {
            g["id"]: g for g in gpu_types if (g.get("maxGpuCount") or 0) >= 1
        }
        ids_order = []
        if DEPLOY_GPU_ID in available:
            ids_order.append(DEPLOY_GPU_ID)
        for pref in PREFERRED_GPU_IDS:
            if pref in available and pref not in ids_order:
                ids_order.append(pref)
        for gid in available:
            if gid not in ids_order:
                ids_order.append(gid)
        order = [available[i] for i in ids_order]
    else:
        print(
            f"GPU リスト取得に失敗または空です。DEPLOY_GPU_ID={DEPLOY_GPU_ID!r} のみ試行します。",
            file=sys.stderr,
        )
        order = [{"id": DEPLOY_GPU_ID, "displayName": DEPLOY_GPU_ID}]

    for gpu in order:
        gid = gpu["id"]
        print(f"Trying GPU {gid} ({gpu['displayName']})...")
        result = create_pod(gid)
        if result.get("errors"):
            print("  FAIL:", result["errors"][0].get("message", result["errors"])[:200])
            continue
        pod = (result.get("data") or {}).get("podFindAndDeployOnDemand")
        if not pod:
            print("  FAIL: response missing data.podFindAndDeployOnDemand", file=sys.stderr)
            continue
        host = pod["machine"]["podHostId"]
        print("\n=== SUCCESS ===")
        print(f"Pod ID: {pod['id']}")
        print(f"GPU: {gpu['displayName']}")
        print(f"UI:  https://{host}-3000.proxy.runpod.io")
        print(f"API: https://{host}-8000.proxy.runpod.io/docs")
        return 0

    print("All GPUs failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
