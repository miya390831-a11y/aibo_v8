#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guard_forbidden.py  ―  PreToolUse フック(決定論的な厳守ルール保護)

Claude Code の Edit/Write の直前に呼ばれ、AIBO の厳守ルールに抵触する変更を
exit code 2 で機械的にブロックする。プロンプト頼みにしない最後の砦。
.claude/settings.json の PreToolUse から呼ぶ(設定は settings_hooks.json 参照)。

入力: tool 呼び出しの JSON が stdin から渡される。
出力: 抵触なし → exit 0 / 抵触あり → 理由を stderr に出して exit 2(ブロック)。
"""

import sys
import json
import re

# 値を変えてはいけない Setting A の7定数(名前に触れる編集は警告対象)
SETTING_A = [
    "GFPGAN_STRENGTH", "ip_adapter_weight", "pulid_sigma_start",
    "pulid_sigma_end", "cn_depth_guidance_end", "pass2_strength",
    "pass2_pulid_boost",
]

# 内容として現れたら即ブロックする禁止パターン
FORBIDDEN = [
    (re.compile(r"PHASE3B_ENABLED\s*=\s*True"), "PHASE3B_ENABLED=True は禁止"),
    (re.compile(r"except\s*:\s*pass|except\s+\w+\s*:\s*pass"), "try/except: pass(silent fail)は禁止"),
    (re.compile(r"pulid[_a-z]*weight\s*=\s*-\d"), "負の PuLID weight は禁止"),
    (re.compile(r"pulid_double_interval\s*="), "pulid_double_interval の変更は禁止"),
    (re.compile(r"(import|from)\s+.*ace_?plus|ACE\+\+|ACEPlus", re.IGNORECASE), "ACE++ 関連の復活は禁止"),
    (re.compile(r"\.mean\(\s*(dim|axis)?\s*=?\s*0?\s*\).*embed|embed.*\.mean\("), "単純 mean embedding は禁止(quality-weighted/medoid を使う)"),
]


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        sys.exit(0)  # 解釈できなければ通す(フックで作業を止めない)

    tool = payload.get("tool_name", "")
    if tool not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    ti = payload.get("tool_input", {}) or {}
    path = ti.get("file_path", "") or ti.get("path", "")
    content = " ".join(str(v) for k, v in ti.items()
                       if k in ("content", "new_string", "new_str") and v)

    for pat, reason in FORBIDDEN:
        if pat.search(content):
            print(f"[guard] ブロック: {reason}  ({path})", file=sys.stderr)
            sys.exit(2)

    for name in SETTING_A:
        if re.search(rf"\b{name}\b\s*=", content):
            print(f"[guard] ブロック: Setting A 定数 '{name}' の値変更は禁止。"
                  f"本当に必要なら人間が手動で。({path})", file=sys.stderr)
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
