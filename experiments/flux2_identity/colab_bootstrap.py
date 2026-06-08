# ============================================================
#  AIBO in-Colab エージェント ブートストラップ（ハードニング版 v2）
#  Claude Code CLI / Max サブスク認証 / API 別課金なし
#  2026-06-07 雛形 → 2026-06-08 統括ハードニング
# ============================================================
#  【事前準備：1回だけ（みやちん）】
#   1. PC で:   claude setup-token
#       → ブラウザ認証 → sk-ant-oat01-... が出る（1年有効・Max サブスク紐付け）
#   2. Colab 左の 🔑 シークレット → 追加:
#       名前 = CC_OAUTH_TOKEN
#       値   = その sk-ant-oat01-...
#       → このノートブックへのアクセスを ON
# ------------------------------------------------------------
#  このセルは「自分で確かめて分岐する」ように書いてある（!magic ではなく subprocess）:
#   - Node が古ければ自動で nodesource 20.x に上げて claude を入れ直す
#   - 認証が「サブスク経路（OAuth）」であることを不変条件として assert する
#       （CC_OAUTH_TOKEN あり / ANTHROPIC_API_KEY なし）
#   - claude -p の往復スモークで「実際に応答するか」まで確認する
#  Colab セル / ローカル CLI どちらに貼っても動く（google.colab が無ければ手動 env を許容）。
# ============================================================

import os
import shutil
import subprocess
import sys


# ------------------------------------------------------------
# 小道具: コマンド実行（必ず stdout/stderr を捕まえる。silent fail 禁止）
# ------------------------------------------------------------
def _run(cmd, check=False, timeout=600, env=None):
    """list[str] のコマンドを実行し CompletedProcess を返す。例外は握りつぶさず表に出す。"""
    print(f"$ {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env if env is not None else os.environ,
    )
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip(), file=sys.stderr)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}")
    return proc


# ------------------------------------------------------------
# 0) API キーの罠を無効化（OAuth と両立すると API キーが優先＝従量課金になる）
#    不変条件①: 走行中 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN は常に未設定。
# ------------------------------------------------------------
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)


# ------------------------------------------------------------
# 1) Drive マウント（重みキャッシュ＆途中結果の保存先）
#    Colab 以外（ローカル検証）では skip。
# ------------------------------------------------------------
IN_COLAB = False
try:
    from google.colab import drive  # type: ignore

    IN_COLAB = True
    if not os.path.ismount("/content/drive"):
        drive.mount("/content/drive")
    else:
        print("Drive は既にマウント済み")
except ImportError:
    print("⚠ google.colab 不在 → Colab 外（ローカル検証）として続行。Drive マウントは skip。")


# ------------------------------------------------------------
# 2) Max サブスクの OAuth トークンを Secrets から読み込む
#    不変条件②: Secrets 名は CC_OAUTH_TOKEN 固定。無ければ即停止（黙って続行しない）。
# ------------------------------------------------------------
_token = None
if IN_COLAB:
    from google.colab import userdata  # type: ignore

    try:
        _token = userdata.get("CC_OAUTH_TOKEN")
    except Exception as e:
        # userdata は鍵未登録/未許可で例外を投げる。握りつぶさず原因を出す。
        raise RuntimeError(
            "Colab Secrets から CC_OAUTH_TOKEN を取得できません。"
            "左の 🔑 で名前=CC_OAUTH_TOKEN を登録し、本ノートブックへのアクセスを ON に。"
        ) from e
else:
    # ローカル検証時は環境変数 CC_OAUTH_TOKEN を直接見る（手動投入を許容）。
    _token = os.environ.get("CC_OAUTH_TOKEN")

if not _token:
    raise RuntimeError(
        "CC_OAUTH_TOKEN が空です。PC で `claude setup-token` → sk-ant-oat01-... を "
        "Colab Secrets（名前=CC_OAUTH_TOKEN）に登録してください。"
    )
if not _token.startswith("sk-ant-oat"):
    # setup-token の OAuth トークンは sk-ant-oat... 形式。API キー(sk-ant-api...)を貼ると従量課金。
    raise RuntimeError(
        "CC_OAUTH_TOKEN が OAuth トークン形式 (sk-ant-oat...) ではありません。"
        "API キー(sk-ant-api...)を入れると従量課金になります。setup-token の値を貼ってください。"
    )
os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = _token
print("✅ OAuth トークン読込（sk-ant-oat… / Max サブスク経路）")


# ------------------------------------------------------------
# 3) Node を確認し、必要なら 20.x に上げてから Claude Code CLI を導入
#    方針（指示§1）: 古くて npm install が失敗する時だけ nodesource フォールバック。
#    → ここでは「node major < 18」または「install 失敗」を検知して自動で上げる。
# ------------------------------------------------------------
def _node_major():
    if shutil.which("node") is None:
        return None
    p = _run(["node", "--version"])
    if p.returncode != 0 or not p.stdout.strip().startswith("v"):
        return None
    try:
        return int(p.stdout.strip().lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        return None


def _install_node_20():
    """nodesource 20.x を導入（Colab の sudo 前提）。フォールバック専用。"""
    print("→ Node を 20.x に更新（nodesource フォールバック）")
    setup = subprocess.run(
        "curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -",
        shell=True, capture_output=True, text=True, timeout=600,
    )
    print(setup.stdout[-2000:])
    if setup.stderr.strip():
        print(setup.stderr[-2000:], file=sys.stderr)
    _run(["sudo", "apt-get", "install", "-y", "nodejs"], timeout=600)


def _install_claude_cli():
    return _run(["npm", "install", "-g", "@anthropic-ai/claude-code"], timeout=600)


_major = _node_major()
print(f"検出 Node major: {_major}")
if _major is None or _major < 18:
    if IN_COLAB:
        _install_node_20()
    else:
        print("⚠ Node が無い/古い。ローカルは手動で Node18+ を用意してください。")

# claude が無ければ npm install。失敗したら nodesource → 再 install を1回試す。
if shutil.which("claude") is None:
    inst = _install_claude_cli()
    if inst.returncode != 0:
        print("⚠ npm install 失敗 → Node 更新して再試行")
        if IN_COLAB:
            _install_node_20()
            _install_claude_cli()
else:
    print("claude は既に導入済み")


# ------------------------------------------------------------
# 4) 動作確認（バージョン + 認証経路 + 往復スモーク）
# ------------------------------------------------------------
_run(["node", "--version"])
ver = _run(["claude", "--version"])
if ver.returncode != 0:
    raise RuntimeError("`claude --version` が失敗。CLI 導入に失敗しています。")

# 認証経路の確証:
#   - 不変条件①再確認: ANTHROPIC_API_KEY/AUTH_TOKEN が未設定であること
#   - 不変条件②再確認: CLAUDE_CODE_OAUTH_TOKEN が設定されていること
#   → この2つが満たされていれば CLI はサブスク(OAuth)経路で動く。
assert not os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY が設定されています（従量課金の罠）"
assert not os.environ.get("ANTHROPIC_AUTH_TOKEN"), "ANTHROPIC_AUTH_TOKEN が設定されています（従量課金の罠）"
assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"), "CLAUDE_CODE_OAUTH_TOKEN が未設定"

# `claude doctor` は環境診断（非対話）。出力はノイズ込みのことがあるので参考表示に留める。
#   （対話 `/status` は TTY 必須＝ヘッドレス Colab では使わない。不変条件 assert を主の確証とする。）
_run(["claude", "doctor"], timeout=120)

# 往復スモーク: 実際に1往復して応答が返るか（＝トークンが有効か）を確認。
#   --output-format text + -p で最小往復。サブスク無効なら 401/認証エラーで非0終了する。
smoke = _run(["claude", "-p", "Reply with exactly: OK", "--output-format", "text"], timeout=180)
if smoke.returncode != 0:
    raise RuntimeError(
        "claude -p 往復スモークが失敗。OAuth トークン失効/未許可の可能性。"
        "PC で `claude setup-token` を取り直して Secrets を更新してください。"
    )

print("\n✅ ブートストラップ完了：このセッションで claude が Max(OAuth) 認証で使えます")
print("   不変条件: CC_OAUTH_TOKEN あり / ANTHROPIC_API_KEY なし（従量課金なし）")


# ============================================================
#  ▼▼▼ 実験の起動（指示 2026-06-07 / 構成B = チェックポイント付きセル）▼▼▼
# ============================================================
#  方針:
#   - 構成B（Klein ネイティブ multi-reference / diffusers / 本機と同一スタック）は
#     "自律エージェントループ" ではなく **直接実行のチェックポイント付きセル** で回す。
#     → configB_klein_multiref.py を直接 run する（下記）。セッションが落ちても再実行で復帰。
#   - 構成A（PuLID-Flux2 / ComfyUI, β）は将来、下のヘッドレス `claude -p` 自律ループで回す枠。
#     今回は実装しない（指示によりスコープ外）。
#
#  --- 構成B の回し方（このセルの後で別セル） ---
#   依存（隔離 venv 推奨。重みは Drive にキャッシュ）:
#   !pip install -q "diffusers>=0.38" transformers accelerate safetensors \
#       insightface onnxruntime-gpu sentencepiece pillow
#
#   HF_HOME を Drive に向けて GB 再DLを避ける + 実験本体を実行:
#   import os
#   os.environ["HF_HOME"] = "/content/drive/MyDrive/aibo_lab/hf_cache"   # ★本番フォルダではない
#   !python /content/drive/MyDrive/aibo_lab/flux2_identity/configB_klein_multiref.py
#       （引数で ref/baseline/prompt のパスと scratch dir を渡す。--help 参照）
#
#  --- 構成A（β・将来枠・今回は使わない） ---
#   # !cat .../experiment_brief.md \
#   #   | claude -p "このブリーフ通りに実験を完走し結果と画像を出力して" \
#   #     --dangerously-skip-permissions --output-format json \
#   #   | tee /content/drive/MyDrive/aibo_lab/exp_out/run_log.json
# ============================================================
