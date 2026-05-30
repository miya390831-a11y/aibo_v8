#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
watch_errorfix.py  ―  実装検証チーム / エラー修正くろうど(当直・常駐ウォッチャー)

ドクトリン B(既知パターンは自動 / 新規は司令部レビュー):
  logs/ を常時監視し、新規エラーを検知したら headless で当直(errorfix-kuroudo)を起動して診断・報告。
  - 既知の安全パターン(WHITELIST)= 司令部の常設指示で自動対応許可:
      当直の diff を決定論的に適用(git apply→py_compile→commit)し、司令部へ事後報告(FYI)。
  - 新規 / リスクあり = 適用しない。報告を logs/errorfix_inbox/ に上げ、司令部(対話)でレビュー
      → 直し方を決定 → 統括(VS Code)に指示 → 統括が現場に実行させる。

設計上の安全装置:
  - whitelist    : 自動対応は司令部が認めた既知パターンに限定(他は必ずレビュー)
  - dedup        : 同一エラー署名はまとめる
  - debounce     : バースト発火を抑制
  - circuit break: 同一署名が MAX_RETRIES 回でエスカレーション(司令部判断へ)
  - lock         : 同時に1件だけ処理(多重起動を防止)
  - 自動適用は git で可逆 + py_compile 検証 + guard_forbidden フックの三重ガード
  - AUTO_PUSH 既定 False(自動対応はローカル commit まで。push は人が判断)

注意:
  エラーは Colab(A100)で発生し、ログは Drive 経由で PC に同期される。
  Drive FUSE のイベントは不安定なので inotify ではなくポーリングで監視する。
  "即座に" には Drive 同期のフロアがある点に留意。
"""

import os
import re
import sys
import json
import time
import glob
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime

# ============================================================
# CONFIG  ―  環境に合わせて調整
# ============================================================
REPO_ROOT   = Path(os.environ.get("AIBO_REPO", Path.cwd()))
LOG_DIR     = REPO_ROOT / "logs"                 # 監視対象(Colab から同期される)
WORK_DIR    = REPO_ROOT / ".errorfix"
POLL_SEC    = 4.0                                # ポーリング間隔(Drive 同期を考慮)
DEBOUNCE_SEC = 30.0                              # 同一署名の再発火を抑える窓
MAX_RETRIES = 3                                  # 同一署名がこの回数でエスカレーション
CLAUDE_BIN  = os.environ.get("CLAUDE_BIN", r"C:\Users\yuuki\AppData\Roaming\npm\claude.cmd")
AUTO_PUSH   = False                              # 既知パターン自動対応時に push まで行うか(既定: ローカルcommitのみ)
BRANCHES    = ["master", "colab-stable"]
# 起動時に既存ログを全走査するか。既定 False = 既存ファイルは「既読」扱いにし、起動後に
# 追記された分・新規作成ファイルだけを拾う(過去バックログの再診断・連続起動を防ぐ)。
SCAN_BACKLOG_ON_START = os.environ.get("SCAN_BACKLOG_ON_START", "0") == "1"

# ★ ドクトリン B: 司令部が「自動対応してよい」と認めた既知パターン(常設指示)。
#   これに当たるエラーだけ統括が自動で直して報告。新規/リスクありは司令部レビューへ。
#   引継書の既知障害から初期登録。安全と確認できた署名は whitelist_signatures.txt に追記して増やす。
WHITELIST_PATTERNS = [
    re.compile(r"numpy.*reinstall|PROTECT_IF_SATISFIED", re.IGNORECASE),
    re.compile(r"Drive.*FUSE|rsync.*failed|input/output error", re.IGNORECASE),
    re.compile(r"bind_forward|PuLID.*rebind|TypeError.*bind", re.IGNORECASE),
]
WHITELIST_SIG_FILE = None  # 後で WORK_DIR/"whitelist_signatures.txt" に設定

# headless 起動フラグ。※ claude のバージョンでフラグ名が変わることがあるので
#   初回は `claude --help` で確認すること。診断は report-only(Edit/Bash を渡さない)。
CLAUDE_FLAGS = [
    "-p",
    "--allowedTools", "Read,Grep,Glob,Write",
    "--output-format", "text",
]

# エラーとみなすパターン
ERROR_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s*[A-Za-z_]*Error\b"),
    re.compile(r"\bRuntimeError\b"),
    re.compile(r"CUDA out of memory|OutOfMemoryError|torch\.cuda\.OutOfMemoryError"),
    re.compile(r"\bException\b.*"),
    re.compile(r"\[ERROR\]|🔬"),                  # error_reporter.py マーカー
]

# 署名の正規化(タイムスタンプ・アドレス・行番号差を吸収)
NORM_SUBS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}[.,\d]*"), "<TS>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<ADDR>"),
    (re.compile(r"line \d+"), "line <N>"),
    (re.compile(r"\d+\.\d+ ?(GiB|MiB|GB|MB)"), "<MEM>"),
]
# ============================================================

WORK_DIR.mkdir(parents=True, exist_ok=True)
(WORK_DIR / "incoming").mkdir(exist_ok=True)
(WORK_DIR / "applied").mkdir(exist_ok=True)
INBOX_DIR = LOG_DIR / "errorfix_inbox"
INBOX_DIR.mkdir(parents=True, exist_ok=True)

STATE_PATH = WORK_DIR / "state.json"
LOCK_PATH  = WORK_DIR / "lock"
WHITELIST_SIG_FILE = WORK_DIR / "whitelist_signatures.txt"


def whitelisted_signatures():
    if WHITELIST_SIG_FILE.exists():
        return {ln.strip() for ln in WHITELIST_SIG_FILE.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")}
    return set()


def is_whitelisted(sig: str, text: str) -> bool:
    if sig in whitelisted_signatures():
        return True
    return any(p.search(text) for p in WHITELIST_PATTERNS)


def load_state():
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[watch] state.json 読み込み失敗(初期化します): {e}")
    return {"offsets": {}, "signatures": {}}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def signature_of(block: str) -> str:
    norm = block
    for pat, repl in NORM_SUBS:
        norm = pat.sub(repl, norm)
    # 例外型 + 最終フレームを優先的に署名へ
    etype = ""
    m = re.search(r"([A-Za-z_]+(?:Error|Exception))\b", norm)
    if m:
        etype = m.group(1)
    last_frame = ""
    frames = re.findall(r'File "(.+?)", line <N>, in (\w+)', norm)
    if frames:
        last_frame = "|".join(frames[-1])
    key = (etype + "::" + last_frame + "::" + norm[-300:]).encode("utf-8")
    return hashlib.sha1(key).hexdigest()[:12]


def looks_like_error(line: str) -> bool:
    return any(p.search(line) for p in ERROR_PATTERNS)


def acquire_lock() -> bool:
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_lock():
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def notify(title: str, body: str):
    """統括 inbox へ書き出し + Windows トースト(あれば)。失敗しても止めない。"""
    print(f"[notify] {title} :: {body[:80]}")
    # Windows トースト(BurntToast が無ければ握りつぶさず print に落とす)
    try:
        ps = (
            f"if (Get-Module -ListAvailable -Name BurntToast) {{"
            f" New-BurntToastNotification -Text '{title}', '{body[:120]}' }}"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       timeout=10, capture_output=True)
    except Exception as e:
        print(f"[notify] toast 不可(無視): {e}")


def _claude(task: str, timeout=600) -> bool:
    """headless で claude を起動。例外時 False。"""
    cmd = [CLAUDE_BIN] + CLAUDE_FLAGS + [task]
    try:
        res = subprocess.run(
            cmd, cwd=str(REPO_ROOT), timeout=timeout,
            capture_output=True, text=True, encoding="utf-8",
        )
        if res.returncode != 0:
            print(f"[claude] 異常終了({res.returncode}): {res.stderr[:300]}")
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        print("[claude] タイムアウト")
        return False
    except FileNotFoundError:
        print(f"[claude] '{CLAUDE_BIN}' が見つからない。CLAUDE_BIN を確認。")
        return False


def run_diagnosis(report_id: str, signature: str, error_text: str):
    """
    当直(エラー修正くろうど)が検知→診断→司令部への報告を作る。自動適用はしない。
    成果は logs/errorfix_inbox/ に置き、みやちんが司令部(対話)に持ち込んでレビューする。
    成功すると報告パスを返す。失敗時 None。
    """
    incoming = WORK_DIR / "incoming" / f"{report_id}_error.txt"
    incoming.write_text(error_text, encoding="utf-8")
    report = INBOX_DIR / f"{report_id}.md"

    print(f"[当直] 診断報告作成: {report_id}")
    task = (
        "あなたは errorfix-kuroudo(当直)。.claude/agents/errorfix-kuroudo.md を読み、"
        "役割と厳守ルールに従う。\n"
        f"検知したエラー全文は {incoming} にある。Read して診断し、"
        "**司令部(CTOくろうど+みやちんの対話)へ上げる報告**を作る。"
        "あなたは直さない・適用しない(検知と診断と提案まで)。\n\n"
        "報告は専門用語を避け、次の構成で書く:\n"
        f"# 🔬 当直からの報告 [{report_id}]\n"
        f"- 署名: {signature} / ステータス: **司令部レビュー待ち・未適用**\n"
        "1. 何が起きたか(エラーの中身を一言で)\n"
        "2. 推定原因(証拠を示す。関連ソースを Read で特定。推測なら『推測』と明記)\n"
        "3. 直し方の提案(平易に)＋ 最小修正の unified diff を ```diff フェンスで\n"
        "4. リスク・気になる点(正直に)\n"
        "5. 厳守ルール適合チェック\n"
        "6. 司令部への確認事項(あれば。ディープリサーチが要りそうな論点も挙げる)\n\n"
        f"成果は Markdown で {report} にのみ Write すること。"
    )
    if not _claude(task) or not report.exists():
        print("[当直] 報告作成失敗")
        return None
    return report


def _sh(args):
    return subprocess.run(args, cwd=str(REPO_ROOT), text=True,
                          capture_output=True, encoding="utf-8")


def extract_diff(text: str) -> str:
    m = re.search(r"```diff\s*\n(.*?)```", text, re.DOTALL)
    return (m.group(1).strip() + "\n") if m else ""


def auto_apply(report_path: Path, report_id: str):
    """既知パターン: 報告内の diff を決定論的に適用(git apply --check→apply→py_compile→commit)。
    成功で (True, msg)、失敗で (False, 理由)。失敗時は変更を巻き戻す。"""
    diff = extract_diff(report_path.read_text(encoding="utf-8"))
    if not diff:
        return False, "diff を抽出できない"
    patch = WORK_DIR / f"{report_id}.patch"
    patch.write_text(diff, encoding="utf-8")

    if _sh(["git", "apply", "--check", str(patch)]).returncode != 0:
        return False, "git apply --check 失敗(現コードに当たらない)"
    if _sh(["git", "apply", str(patch)]).returncode != 0:
        return False, "git apply 失敗"

    for f in re.findall(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE):
        if f.endswith(".py"):
            if _sh([sys.executable, "-m", "py_compile", f]).returncode != 0:
                _sh(["git", "checkout", "--", "."])
                return False, f"構文NG: {f}(ロールバック済み)"

    _sh(["git", "add", "-A"])
    msg = f"fix(auto): {report_id} 既知パターン自動対応 / 統括"
    if _sh(["git", "commit", "-m", msg]).returncode != 0:
        return False, "commit 失敗"
    if AUTO_PUSH:
        for br in BRANCHES:
            _sh(["git", "push", "origin", f"HEAD:{br}"])
    return True, msg


def _log_files():
    """監視対象ファイル一覧(inbox は除外)。scan_once と seed_offsets で共用。"""
    files = sorted(glob.glob(str(LOG_DIR / "**" / "*.log"), recursive=True)) + \
            sorted(glob.glob(str(LOG_DIR / "**" / "*.txt"), recursive=True)) + \
            sorted(glob.glob(str(LOG_DIR / "report_*.md"), recursive=True))
    return [f for f in files if str(INBOX_DIR) not in f]


def seed_offsets(state):
    """起動時、既存ログを『既読』として現在サイズを offsets に記録する。
    以降は起動後に追記された分・新規ファイルだけを拾う(過去バックログの再診断を防ぐ)。"""
    n = 0
    for f in _log_files():
        if f in state["offsets"]:
            continue
        try:
            state["offsets"][f] = os.path.getsize(f)
            n += 1
        except OSError:
            continue
    return n


def scan_once(state):
    for f in _log_files():
        try:
            size = os.path.getsize(f)
        except OSError:
            continue
        prev = state["offsets"].get(f, 0)
        if size < prev:        # ローテーション/再生成
            prev = 0
        if size == prev:
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(prev)
                new = fh.read()
        except OSError:
            continue
        state["offsets"][f] = size
        if not new.strip():
            continue
        if any(looks_like_error(ln) for ln in new.splitlines()):
            handle_error_block(state, source=f, block=new)


def handle_error_block(state, source: str, block: str):
    sig = signature_of(block)
    now = time.time()
    info = state["signatures"].get(sig, {"count": 0, "last": 0, "status": "open"})

    if info["status"] == "escalated":
        return
    if now - info["last"] < DEBOUNCE_SEC:
        return
    if info["count"] >= MAX_RETRIES:
        info["status"] = "escalated"
        state["signatures"][sig] = info
        notify("🔬 要・人間判断",
               f"署名 {sig} が {MAX_RETRIES} 回再発。自動提案を停止しエスカレーション。")
        (INBOX_DIR / f"ESCALATED_{sig}.md").write_text(
            f"# ⚠ エスカレーション [{sig}] — 司令部判断が必要\n\n"
            f"同一エラーが {MAX_RETRIES} 回繰り返したため自動診断を停止しました。"
            f"対症療法では潰せない構造的原因(設計レベル)の可能性が高い。"
            f"司令部(対話)でディープリサーチ含む作戦会議を推奨。\n\n"
            f"発生元: `{source}`\n",
            encoding="utf-8")
        return

    if not acquire_lock():
        print("[watch] 別処理が進行中。次回に回す。")
        return
    try:
        report_id = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{sig}"
        report = run_diagnosis(report_id, sig, error_text=block)
        info["count"] += 1
        info["last"] = now
        state["signatures"][sig] = info
        if report is None:
            notify("🔬 報告生成に失敗", f"署名 {sig} の当直の起動に失敗。ログを確認。")
            return

        if is_whitelisted(sig, block):
            # 既知の安全パターン → 統括が自動対応(常設指示)+ 報告
            ok, msg = auto_apply(report, report_id)
            if ok:
                with open(report, "a", encoding="utf-8") as fh:
                    fh.write(f"\n\n---\n## 🤖 自動対応済み(既知パターン)\n"
                             f"- {msg}\n- AUTO_PUSH={AUTO_PUSH}(False ならローカル commit のみ)\n"
                             f"- 残作業: **Colab 再 run(os.kill 再起動)**\n"
                             f"- これは司令部への事後報告です(判断不要・FYI)\n")
                notify("🤖 既知パターン自動対応済み",
                       f"署名 {sig}: 統括が自動修正→報告。判断不要(FYI)。")
            else:
                with open(report, "a", encoding="utf-8") as fh:
                    fh.write(f"\n\n---\n## ⚠ 自動対応を見送り\n"
                             f"既知パターンだが自動適用できず({msg})。"
                             f"**司令部レビューに切替**。\n")
                notify("🔬 自動対応できず → 司令部レビュー",
                       f"署名 {sig}: 自動適用失敗({msg})。司令部で確認を。")
        else:
            # 新規 / リスクあり → 司令部レビュー待ち(未適用)
            notify("🔬 司令部レビュー待ちの報告",
                   f"署名 {sig}: 新規/要判断。logs/errorfix_inbox/ に報告。司令部で確認を。")
    finally:
        release_lock()


def main():
    print(f"[watch] 起動: REPO={REPO_ROOT} LOG_DIR={LOG_DIR}")
    print(f"[watch] poll={POLL_SEC}s debounce={DEBOUNCE_SEC}s max_retries={MAX_RETRIES}")
    release_lock()  # 異常終了の残骸を掃除
    fresh_start = not STATE_PATH.exists()
    state = load_state()
    if fresh_start and not SCAN_BACKLOG_ON_START:
        seeded = seed_offsets(state)
        save_state(state)
        print(f"[watch] 初回起動: 既存ログ {seeded} 件を既読扱い(過去バックログは診断しない)。"
              f" 全走査するなら SCAN_BACKLOG_ON_START=1。")
    elif fresh_start:
        print("[watch] 初回起動: SCAN_BACKLOG_ON_START=1 のため既存ログも走査する。")
    try:
        while True:
            scan_once(state)
            save_state(state)
            time.sleep(POLL_SEC)
    except KeyboardInterrupt:
        print("\n[watch] 停止しました。")
        save_state(state)


if __name__ == "__main__":
    main()
