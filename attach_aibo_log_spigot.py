# ═══════════════════════════════════════════════════════════════════════════
# ログ蛇口: AIBO_v7 ロガー → /content/aibo_gen.log(logging only・prod 非改変)
#
#   目的(GATE① 最終真偽判定・指示書 §2):
#     検証セルは本番関数を「直接」呼ぶが、UI → FastAPI → generate の“本物経路”が
#     最も確実。orchestrator のロガー("AIBO_v7", [OSS] 行を含む)に FileHandler を
#     1個足し、/content/aibo_gen.log に追記するだけ。生成ロジックは一切変えない。
#
#   使い方(Cell 0 / server 起動後に1回だけ):
#     exec(open("/content/drive/MyDrive/aibo_v7/attach_aibo_log_spigot.py",
#               encoding="utf-8").read())
#   → その後 PO が UI(localhost:3000・slider 14)で1枚生成 → 別セルで:
#     !tail -n 120 /content/aibo_gen.log
#
#   読み方(本物 UI 生成の [OSS] 行で判定):
#     ✓ `🧩 [OSS] inject-point reached: route=_run_pass1 steps=14 ...` が出る
#         → 実行中の 05 は OSS ブロック搭載(=live)。続けて:
#         ・`[OSS] APPLIED n=14 maxΔ≈0.0 ✓`   → 本番発火(H2:検証セルの捕捉ミスだった)
#         ・`[OSS] APPLIED n=14 ... ⚠️FALLBACK` → wrap は乗るが上書き未達(仮説 a/c)
#         ・`[OSS] sigma 準備失敗 ...`          → oss_sigmas 例外(np 等・要調査)
#     ❌ inject-point 行が“出ない”
#         → 実行中の 05 が stale(OSS ブロック未搭載)= H1 確定。
#           対処: 全 .py(特に 05_orchestrator.py)を G:\マイドライブ\aibo_v7\ に
#           再同期 → Colab 再起動(os.kill(os.getpid(),9))→ Cell 0 再 build。
# ═══════════════════════════════════════════════════════════════════════════
import logging

_LOG_PATH = "/content/aibo_gen.log"
_av = logging.getLogger("AIBO_v7")

# 既定 effective level は 01_config の basicConfig(INFO)。[OSS] APPLIED は info で出るため
# logger level は変更しない(= さらなる prod 非改変)。handler 側だけ DEBUG で広く拾う。
_already = any(getattr(h, "_aibo_spigot", False) for h in _av.handlers)
if _already:
    print(f"[spigot] 既に attach 済み → {_LOG_PATH}(二重 attach 回避)")
else:
    _fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _fh._aibo_spigot = True            # 二重 attach 検出マーカー
    _av.addHandler(_fh)
    print(f"[spigot] attached(FileHandler・logging only)→ {_LOG_PATH}")

print("[spigot] 次の手順:")
print("  1) UI(localhost:3000・slider=14)で1枚生成")
print("  2) 別セル: !tail -n 120 /content/aibo_gen.log")
print("  3) `🧩 [OSS] inject-point reached` 行の有無で H1(stale)/ live を判定")
print("     → 詳細はこのファイル冒頭コメントの『読み方』参照")
