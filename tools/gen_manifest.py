#!/usr/bin/env python3
# ═══════════════════════════════════════════════════════════════════════════
# gen_manifest.py — committed AIBO コアモジュールの内容 md5 を module_manifest.json に記録
#
#   目的(恒久対策 B2):
#     「committed が source of truth、Colab runtime はそれに一致しないと走らない」を強制する。
#     commit 前にこれを実行 → module_manifest.json を commit。
#     Cell 0 build 時に tools/check_manifest.verify_module_manifest() がこの json と
#     runtime 実ロードモジュール(__file__)を照合し、desync なら STOP する。
#
#   ★改行正規化 md5:
#     Windows working tree(CRLF)/ Drive 同期物(CRLF)/ git(LF)で **同一ハッシュ**になるよう、
#     CRLF・CR を LF に正規化した内容を md5 する。= 改行差での false desync を出さない。
#
#   使い方(コミット前・Windows でも Colab でも可):
#     python tools/gen_manifest.py
# ═══════════════════════════════════════════════════════════════════════════
import glob
import hashlib
import json
import os

# core modules = リポジトリ直下の「数字始まり」.py(01_config 〜 17_*)。
# 実験ファイル(exp_*/diag_*/verify_*/attach_*)は runtime コア経路でないため対象外。
CORE_GLOB = "[0-9]*.py"


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm_md5(path):
    """改行正規化(CRLF/CR → LF)した内容の md5 hex。CRLF/LF 非依存。"""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def build_manifest(root=None):
    root = root or _repo_root()
    files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(root, CORE_GLOB)))
    return {f: norm_md5(os.path.join(root, f)) for f in files}


def main():
    root = _repo_root()
    modules = build_manifest(root)
    out = {
        "_comment": (
            "AIBO core module md5 (newline-normalized LF). "
            "regen: python tools/gen_manifest.py  |  verify: tools/check_manifest.py"
        ),
        "modules": modules,
    }
    path = os.path.join(root, "module_manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    print(f"[gen_manifest] wrote {path}  ({len(modules)} modules)")
    for k, v in modules.items():
        print(f"   {k:32s} {v[:8]}")


if __name__ == "__main__":
    main()
