#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
# check_manifest.py — module-manifest preflight(恒久対策 B2 の本命ガード)
#
#   狙い:
#     silent な module desync(例: 04 新版 / 05 旧版)を **build 時に大声で検出して STOP**。
#     GATE① の真因(05 が runtime で stale → OSS 注入ブロック未実行 → OSS='None')は、
#     このガードがあれば Cell 0 で即死していた。
#
#   仕組み:
#     committed の module_manifest.json(各コア .py の改行正規化 md5)を読み、
#     runtime に実ロードされたモジュール(sys.modules の __file__・無ければ repo 直下)の
#     同じ正規化 md5 を計算して照合。1個でも不一致なら(strict)SystemExit。
#
#   呼ばれ方:
#     - 自動: 07_main.run() 冒頭(build 前)で verify_module_manifest() を呼ぶ。
#     - 手動: Colab セルで
#         exec(open("/content/drive/MyDrive/aibo_v7/tools/check_manifest.py",
#                   encoding="utf-8").read())
#       または import_module("tools.check_manifest").verify_module_manifest(strict=False)
#
#   生成ロジックは一切変えない(検証のみ)。manifest 不在時は skip(=ガード未導入環境を壊さない)。
# ═══════════════════════════════════════════════════════════════════════════
import hashlib
import json
import logging
import os
import sys

logger = logging.getLogger("AIBO_v7")


def _safe_print(s):
    """Windows cp932 等の非 UTF-8 コンソールでも絵文字で落ちないよう encode フォールバック。"""
    try:
        print(s)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "utf-8"
        print(s.encode(enc, errors="replace").decode(enc, errors="replace"))


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _norm_md5(path):
    """改行正規化(CRLF/CR → LF)した内容の md5 hex。gen_manifest.norm_md5 と同一規則。"""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _resolve_module_file(name, filename, repo_root):
    """(path, source) を返す。実ロード済なら __file__(=runtime が読んだ実体)優先。"""
    mod = sys.modules.get(name)
    f = getattr(mod, "__file__", None) if mod is not None else None
    if f and os.path.exists(f):
        return f, ("loaded" if mod is not None else "disk")
    cand = os.path.join(repo_root, filename)
    if os.path.exists(cand):
        return cand, "disk(not-loaded)"
    return None, "missing"


def verify_module_manifest(manifest_path=None, strict=True):
    """committed manifest と runtime モジュールの md5 を照合。
    不一致: strict=True で SystemExit、False で False を返す。
    全一致: True。manifest 不在: skip して True。"""
    root = _repo_root()
    manifest_path = manifest_path or os.path.join(root, "module_manifest.json")
    if not os.path.exists(manifest_path):
        msg = f"[manifest] module_manifest.json 不在({manifest_path})→ ガード skip(生成は続行)"
        logger.warning(msg)
        _safe_print(msg)
        return True

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("modules", data)  # {filename: md5}

    parts, mismatches, skipped = [], [], []
    for filename in sorted(entries):
        name = filename[:-3] if filename.endswith(".py") else filename
        tag = name.split("_", 1)[0]  # "05_orchestrator" -> "05"
        expected = entries[filename]
        path, src = _resolve_module_file(name, filename, root)
        if path is None:
            skipped.append(filename)
            parts.append(f"{tag}=MISSING")
            mismatches.append((filename, "MISSING", expected, "(not found)", src))
            continue
        actual = _norm_md5(path)
        parts.append(f"{tag}={actual[:8]}")
        if actual != expected:
            mismatches.append((filename, actual, expected, path, src))

    line = "[OBS] module manifest | " + " ".join(parts)
    logger.info(line)
    _safe_print(line)

    if mismatches:
        out = ["❌ MODULE DESYNC 検出(committed manifest と不一致 → build STOP):"]
        for fn, act, exp, path, src in mismatches:
            a8 = act if act == "MISSING" else act[:8]
            out.append(f"   {fn}  runtime={a8}  expected={exp[:8]}  src={src}  ({path})")
        out.append("   対処: 該当 .py を G:\\マイドライブ\\aibo_v7\\ に再同期(md5 一致を確認)→ Colab 再起動。")
        out.append("   ※ 『sync した』は証拠ではない。『manifest 一致』が verify/ship ゲートの前提。")
        report = "\n".join(out)
        logger.error(report)
        _safe_print(report)
        if strict:
            raise SystemExit(report)
        return False

    if skipped:
        logger.info(f"[manifest] 未ロードで skip(build 後に再確認可): {skipped}")
    ok_msg = "✅ [manifest] runtime modules == committed(desync なし)"
    logger.info(ok_msg)
    _safe_print(ok_msg)
    return True


if __name__ == "__main__":
    # standalone / Colab exec: 単体確認は非 strict(レポートのみ・落とさない)
    _ok = verify_module_manifest(strict=False)
    sys.exit(0 if _ok else 1)
