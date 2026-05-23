#!/usr/bin/env python3
"""
RunPod Pod アイドル時の自動停止（Windows タスクスケジューラ向け）。

RunPod GraphQL では「最後のブラウザアクセス時刻」は取得できないため、
config.json の status_url（プロキシの /api/system/status）をポーリングし、
VRAM 使用率 (vram_pct) が一定時間変化しなければ「アイドル」とみなして Stop する。

必須環境変数: RUNPOD_API_KEY
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DIR = Path(__file__).resolve().parent
LOG_FILE = DIR / "auto_stop.log"
STATE_FILE = DIR / "idle_state.json"
CONFIG_FILE = DIR / "config.json"
GRAPHQL_URL = "https://api.runpod.io/graphql"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("runpod_auto_stop")


def load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        log.error("config.json がありません。config.example.json をコピーして編集してください。")
        sys.exit(1)
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def graphql(api_key: str, query: str) -> dict[str, Any]:
    body = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        GRAPHQL_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def fetch_pod(api_key: str, pod_id: str) -> dict[str, Any] | None:
    safe = pod_id.replace('"', "").replace("\n", "").strip()
    q = """
    {
      pod(input: {podId: "%s"}) {
        id
        desiredStatus
        name
        runtime {
          uptimeInSeconds
        }
        machine {
          podHostId
          gpuDisplayName
        }
      }
    }
    """ % safe
    data = graphql(api_key, q)
    if data.get("errors"):
        log.error("GraphQL errors: %s", data["errors"])
        return None
    return data.get("data", {}).get("pod")


def terminate_pod(api_key: str, pod_id: str) -> bool:
    safe = pod_id.replace('"', "").replace("\n", "").strip()
    q = 'mutation { podTerminate(input: { podId: "%s" }) }' % safe
    data = graphql(api_key, q)
    if data.get("errors"):
        log.error("podTerminate errors: %s", data["errors"])
        return False
    log.info("podTerminate 送信: podId=%s response=%s", safe, data.get("data"))
    return True


def fetch_status_vram_pct(status_url: str) -> float | None:
    try:
        req = urllib.request.Request(status_url, method="GET")
        req.add_header("User-Agent", "AIBO-RunPod-AutoStop/1.0")
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = json.loads(resp.read().decode())
        if "vram_pct" in body:
            return float(body["vram_pct"])
        return None
    except urllib.error.HTTPError as e:
        log.warning("status URL HTTP %s (%s)", e.code, status_url)
        return None
    except Exception as e:
        log.warning("status URL 取得失敗: %s", e)
        return None


def main() -> None:
    api_key = os.environ.get("RUNPOD_API_KEY", "").strip()
    if not api_key:
        log.error("環境変数 RUNPOD_API_KEY が設定されていません。")
        sys.exit(1)

    cfg = load_config()
    pod_id = str(cfg.get("pod_id", "")).strip()
    idle_sec = int(cfg.get("idle_minutes", 10)) * 60
    min_uptime = int(cfg.get("min_uptime_before_stop_seconds", 600))
    vram_eps = float(cfg.get("vram_change_epsilon_pct", 0.5))
    status_url = str(cfg.get("status_url", "") or "").strip()

    if not pod_id:
        log.error("config.json の pod_id が空です。")
        sys.exit(1)

    pod = fetch_pod(api_key, pod_id)
    if not pod:
        sys.exit(1)

    ds = (pod.get("desiredStatus") or "").upper()
    uptime = int((pod.get("runtime") or {}).get("uptimeInSeconds") or 0)

    if ds != "RUNNING":
        log.info("Pod は RUNNING ではありません (%s)。終了します。", pod.get("desiredStatus"))
        return

    if uptime < min_uptime:
        log.info(
            "起動直후のため停止しません uptime=%ss < min_uptime=%ss",
            uptime,
            min_uptime,
        )
        return

    if not status_url:
        log.error(
            "config.json の status_url が空です。"
            " 例: https://<podHostId>-3000.proxy.runpod.io/api/system/status"
        )
        sys.exit(1)

    vram = fetch_status_vram_pct(status_url)
    if vram is None:
        log.info("VRAM 取得できず。Pod 停止中か URL 誤りの可能性。今回は何もしません。")
        return

    state: dict[str, Any] = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}

    now = time.time()
    last_vram = state.get("last_vram_pct")
    last_change = float(state.get("last_vram_change_ts", now))

    if last_vram is None:
        state = {"last_vram_pct": vram, "last_vram_change_ts": now}
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log.info("状態初期化 vram_pct=%.2f pod=%s", vram, pod_id)
        return

    last_vram_f = float(last_vram)
    if abs(vram - last_vram_f) >= vram_eps:
        log.info("VRAM 変化 %.2f -> %.2f (アクティブ扱い・タイマーリセット)", last_vram_f, vram)
        state["last_vram_pct"] = vram
        state["last_vram_change_ts"] = now
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return

    idle_for = now - last_change
    log.info(
        "VRAM 安定 %.2f%% ・最後の変化から %.0fs (閾値 %ss)",
        vram,
        idle_for,
        idle_sec,
    )

    if idle_for >= idle_sec:
        log.warning("アイドル閾値超過: Pod %s を停止します。 idle=%.0fs", pod_id, idle_for)
        if terminate_pod(api_key, pod_id):
            STATE_FILE.write_text("{}", encoding="utf-8")
    else:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
