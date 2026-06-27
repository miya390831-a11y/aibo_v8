# ═══════════════════════════════════════════════════════════════════════════
# ログ蛇口 v3: AIBO の [OSS] APPLIED / inject-point 行 → /content/aibo_gen.log
#   (prod 非改変・生成ロジックは一切触らない。出力を「確実に file に乗せる」だけ)
#
#   v2→v3 の変更(★force re-attach): 「既に attach 済みならスキップ」をやめた。
#   旧蛇口(v1=AIBO_v7 直付け等)が残っていると新配線に張り替わらず gen.log が拾えない事故が
#   起きたため、**同一 path / 旧蛇口の FileHandler を root・AIBO_v7 から一旦 remove してから
#   新版を 1 個だけ付け直す**。二重書き込みは「同一 path の FileHandler は 1 個だけ」で回避。
#
#   3 経路で確実化(根本原因に賭けない配線):
#     (1) ROOT logger に FileHandler = 伝播してくる全 logging を logger 名非依存で捕捉。
#     (2) "AIBO_v7"(05:855/878 の発生元)の propagate=True 強制 + level を INFO 以下に保証。
#     (3) sys.stdout を tee = 一部マーカーが print 由来でも file に乗せる(既 tee は再 tee しない)。
#   attach 直後に self-test(logging + print)→ size>0 を確認し `✅ spigot self-test OK size=..B`。
#   0 なら配線失敗を即警告(silent fail させない)。
#
#   使い方(CLEAN 起動後・[Cell-run] 内で自動 force re-attach 済み。手動なら):
#     exec(open("/content/aibo_clean/attach_aibo_log_spigot.py", encoding="utf-8").read())
#   生成後の確認は [LOG] セル(推奨)or  !tail -n 120 /content/aibo_gen.log
#
#   読み方(本物 UI 生成の [OSS] 行で判定):
#     ✓ `🧩 [OSS] inject-point reached: route=_run_pass1 steps=14 ...`  → 05 は OSS 搭載=live
#     ✓ `[OSS] APPLIED n=14 maxΔ=0.00000 ✓`                            → 本番発火(=GATE① 緑)
#     ⚠️ `[OSS] APPLIED n=14 ... ⚠️ FALLBACK/二重シフト疑い`            → wrap は乗るが上書き未達
#     ❌ inject-point 行が出ない                                         → 実行中 05 が stale(H1)
#        ただし self-test は乗るのに UI 生成行が出ない場合は、その生成がこのカーネルの
#        orchestrator を通っていない(ngrok 先が別/旧サーバ)疑い(蛇口バグではない)。
# ═══════════════════════════════════════════════════════════════════════════
import logging
import os
import sys

_LOG_PATH = os.environ.get("AIBO_GEN_LOG", "/content/aibo_gen.log")
_ABS = os.path.abspath(_LOG_PATH)
_FMT = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")

_root = logging.getLogger()
_av = logging.getLogger("AIBO_v7")


# ── (A) force re-attach: 旧蛇口 / 同一 path の FileHandler を root・AIBO_v7 から除去 ──────
def _purge_spigot(_lg):
    _n = 0
    for _h in list(_lg.handlers):
        _is_ours = getattr(_h, "_aibo_spigot", False)
        _same_path = (isinstance(_h, logging.FileHandler)
                      and os.path.abspath(getattr(_h, "baseFilename", "")) == _ABS)
        if _is_ours or _same_path:
            _lg.removeHandler(_h)
            try:
                _h.close()
            except Exception as _e:
                print("[spigot] (warn) 旧 handler close 失敗: " + type(_e).__name__ + ": " + str(_e), flush=True)
            _n += 1
    return _n


_n_removed = _purge_spigot(_root) + _purge_spigot(_av)

# ── (1) ROOT logger に新版 FileHandler を 1 個だけ(logger 名非依存で全 logging を捕捉)──
#    AIBO_v7 は propagate=True なので root の handler に必ず届く。root のみに付け二重書込みも回避。
_fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
_fh.setLevel(logging.DEBUG)                  # handler 側は広く拾う(logger level が gate)
_fh.setFormatter(_FMT)
_fh._aibo_spigot = True                       # 蛇口マーカー(次回 force re-attach で除去対象)
_root.addHandler(_fh)

# ── (2) [OSS] APPLIED(=logger.info)を確実に通す: level / propagate を保証 ─────────────
#    prod 非改変の範囲(level は「下げるだけ」=より多く拾う方向。生成挙動は変えない)。
if _root.level == logging.NOTSET or _root.level > logging.INFO:
    _root.setLevel(logging.INFO)
if _av.level != logging.NOTSET and _av.level > logging.INFO:
    _av.setLevel(logging.INFO)
_av.propagate = True                          # 誰かが propagate=False にしていても root 経路で拾う

print("[spigot] force re-attach: 旧 handler " + str(_n_removed) + " 個除去 → root に新版 FileHandler 1個 → "
      + _LOG_PATH, flush=True)


# ── (3) sys.stdout を tee(print 由来のマーカーも file に乗せる。既 tee は再 tee しない)──
class _Tee:
    """orig stream と file の両方へ書く薄い wrapper。Colab の表示は壊さない。
    file 側の I/O 失敗は握りつぶさず _fobj_err に記録する(silent fail 禁止)。"""
    _aibo_tee = True

    def __init__(self, _orig, _fobj):
        self.__dict__["_orig"] = _orig
        self.__dict__["_fobj"] = _fobj
        self.__dict__["_fobj_err"] = None

    def write(self, _s):
        _n = len(_s) if _s else 0
        try:
            _n = self._orig.write(_s) or _n
        except Exception as _e:        # orig 表示が壊れても file 側は試す(原因は保持)
            self.__dict__["_fobj_err"] = f"orig.write: {type(_e).__name__}: {_e}"
        try:
            self._fobj.write(_s)
            self._fobj.flush()
        except Exception as _e:        # file 書込み失敗は記録(次の flush で露見させる)
            self.__dict__["_fobj_err"] = f"fobj.write: {type(_e).__name__}: {_e}"
        return _n

    def flush(self):
        for _t in (self._orig, self._fobj):
            try:
                _t.flush()
            except Exception as _e:
                self.__dict__["_fobj_err"] = f"flush: {type(_e).__name__}: {_e}"

    def __getattr__(self, _n):
        return getattr(self.__dict__["_orig"], _n)


if not getattr(sys.stdout, "_aibo_tee", False):
    _tee_f = open(_LOG_PATH, "a", encoding="utf-8")
    sys.stdout = _Tee(sys.stdout, _tee_f)
    print("[spigot] stdout tee 有効(print 由来の [OSS]/inject-point も捕捉)", flush=True)
else:
    print("[spigot] stdout tee は既に有効(再 tee せず=二重書込み回避)", flush=True)

# ── self-test: logging と print の両経路を撃って file>0 を即確認 ───────────────
_av.info("[spigot] self-test (AIBO_v7 logging → root FileHandler → file) ✓")
print("[spigot] self-test (print → stdout tee → file) ✓", flush=True)
for _h in _root.handlers:
    try:
        _h.flush()
    except Exception as _e:
        print("[spigot] (warn) handler flush 失敗: " + type(_e).__name__ + ": " + str(_e), flush=True)
_size = os.path.getsize(_LOG_PATH) if os.path.exists(_LOG_PATH) else 0
print("[spigot] root.level=" + logging.getLevelName(_root.level)
      + " / AIBO_v7.level=" + logging.getLevelName(_av.level)
      + " propagate=" + str(_av.propagate), flush=True)
if _size > 0:
    print("✅ spigot self-test OK size=" + str(_size) + "B → " + _LOG_PATH
          + "(UI で 1 枚生成 → [LOG] セルで `[OSS] APPLIED n=14` を確認)", flush=True)
else:
    print("⚠️ spigot 配線失敗: self-test が file に乗らない(size=0)。path/権限を確認"
          "(silent fail させない)", flush=True)
