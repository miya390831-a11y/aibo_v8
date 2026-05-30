#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_fix.py  ―  統括が「司令部(対話)で承認された修正」を安全に適用する補助ツール

ドクトリン A:
  直すかどうか・どう直すかは司令部(CTOくろうど + みやちんの対話)で決まる。
  このツールは "決定済みの修正を、統括が現場に安全に適用する" ための手だけを担う。
  approve_errorfix.py(旧・承認制)は廃止。これに置き換える。

使い方:
  python .errorfix/apply_fix.py <報告 .md または .patch>
    - .md(logs/errorfix_inbox/ の報告)を渡すと ```diff ブロックを抽出して適用
    - .patch を渡すと直接適用
  司令部が diff を手直しした場合は、その最終 diff を .patch に保存して渡す。

安全:
  git apply --check → git apply → 変更 .py を py_compile → NG なら自動ロールバック
  → 標準化コミット → push 確認 → 司令部への結果報告を logs/ に出力。
  ※ guard_forbidden.py(PreToolUse フック)とは別レイヤーの保険。
"""

import os
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(os.environ.get("AIBO_REPO", Path.cwd()))
LOG_DIR   = REPO_ROOT / "logs"
BRANCHES  = ["master", "colab-stable"]
DIFF_RE   = re.compile(r"```diff\s*\n(.*?)```", re.DOTALL)


def sh(args, **kw):
    return subprocess.run(args, cwd=str(REPO_ROOT), text=True,
                          capture_output=True, encoding="utf-8", **kw)


def load_diff(src: Path) -> str:
    text = src.read_text(encoding="utf-8")
    if src.suffix == ".patch":
        return text if text.endswith("\n") else text + "\n"
    m = DIFF_RE.search(text)
    if not m:
        return ""
    d = m.group(1).strip()
    return d + "\n"


def syntax_ok(diff_text: str) -> bool:
    files = re.findall(r"^\+\+\+ b/(.+)$", diff_text, re.MULTILINE)
    ok = True
    for f in files:
        if f.endswith(".py"):
            r = sh([sys.executable, "-m", "py_compile", f])
            if r.returncode != 0:
                print(f"  [構文NG] {f}: {r.stderr.strip()[:200]}")
                ok = False
    return ok


def main():
    if len(sys.argv) < 2:
        print("使い方: python .errorfix/apply_fix.py <報告.md または .patch>")
        sys.exit(1)
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"ファイルが見つからない: {src}")
        sys.exit(1)

    diff = load_diff(src)
    if not diff:
        print("diff が抽出できない。司令部が確定した最終 diff を確認。")
        sys.exit(1)

    patch_file = REPO_ROOT / ".errorfix" / (src.stem + ".patch")
    patch_file.write_text(diff, encoding="utf-8")

    if sh(["git", "apply", "--check", str(patch_file)]).returncode != 0:
        chk = sh(["git", "apply", "--check", str(patch_file)])
        print(f"  git apply --check 失敗(現コードに当たらない): {chk.stderr.strip()[:200]}")
        sys.exit(1)

    if sh(["git", "apply", str(patch_file)]).returncode != 0:
        print("  git apply 失敗。")
        sys.exit(1)

    if not syntax_ok(diff):
        print("  構文NG → ロールバックします。")
        sh(["git", "checkout", "--", "."])
        sys.exit(1)

    msg = f"fix: {src.stem} (司令部承認 / 統括適用)"
    sh(["git", "add", "-A"])
    if sh(["git", "commit", "-m", msg]).returncode != 0:
        print("  commit 失敗。")
        sys.exit(1)
    print(f"  コミット完了: {msg}")

    if input("  push する?(master/colab-stable)[y/N]: ").strip().lower() == "y":
        for br in BRANCHES:
            r = sh(["git", "push", "origin", f"HEAD:{br}"])
            print(f"  push {br}: {'OK' if r.returncode == 0 else r.stderr.strip()[:160]}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(exist_ok=True)
    (LOG_DIR / f"report_apply_{ts}.md").write_text(
        f"# 統括 → 司令部 適用結果報告 {ts}\n\n"
        f"- 元: {src.name}\n- コミット: {msg}\n"
        f"- 結果: 適用・構文チェック OK\n"
        f"- 残作業: **Colab 側で再 run(os.kill 再起動)が必要**\n",
        encoding="utf-8")
    print(f"  司令部への結果報告: logs/report_apply_{ts}.md")


if __name__ == "__main__":
    main()
