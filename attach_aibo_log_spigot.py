# ═══════════════════════════════════════════════════════════════════════════
# ログ蛇口 v2: AIBO の [OSS] APPLIED / inject-point 行 → /content/aibo_gen.log
#   (prod 非改変・生成ロジックは一切触らない。出力を「確実に file に乗せる」だけ)
#
#   旧 v1 の問題: FileHandler を logger "AIBO_v7" にだけ付けていた。原理上は同一プロセス
#   (FastAPI は 07_main の daemon thread)なので拾えるはずだが、実機で 0 bytes だった。
#   → 原因を 1 つに賭けず、3 経路で確実化する(根本原因に依存しない配線):
#     (1) ROOT logger に FileHandler を付ける
#         = 伝播してくる全 logging を logger 名に依存せず捕捉(AIBO_v7 以外で出ていても拾う)。
#     (2) "AIBO_v7" の propagate=True を強制 + level を INFO 以下に保証
#         = [OSS] APPLIED は logger.info で出る。level が WARNING に上がっていても落とさない。
#     (3) sys.stdout を tee
#         = もし一部マーカーが print 由来でも file に乗せる(指示書 §2「print なら tee」)。
#   さらに attach 時に self-test(logging + print)を撃ち、file size>0 を即確認する
#   → PO は「UI で 1 枚生成する前に」配線が生きていることを確認できる。
#
#   使い方(CLEAN 起動後・[Cell-run] 末尾で自動 attach 済み。手動なら):
#     exec(open("/content/aibo_clean/attach_aibo_log_spigot.py", encoding="utf-8").read())
#   生成後の確認:
#     !tail -n 120 /content/aibo_gen.log     # `[OSS] APPLIED n=14 maxΔ=... ✓` を目視
#
#   読み方(本物 UI 生成の [OSS] 行で判定):
#     ✓ `🧩 [OSS] inject-point reached: route=_run_pass1 steps=14 ...`  → 05 は OSS 搭載=live
#     ✓ `[OSS] APPLIED n=14 maxΔ=0.00000 ✓`                            → 本番発火(=GATE① 緑)
#     ⚠️ `[OSS] APPLIED n=14 ... ⚠️ FALLBACK/二重シフト疑い`            → wrap は乗るが上書き未達
#     ❌ inject-point 行が出ない                                         → 実行中 05 が stale(H1)
#        ただし self-test が file に乗っているのに UI 生成行が出ない場合は、
#        「その UI 生成がこのカーネルの orchestrator を通っていない」(ngrok 先が別/旧サーバ)疑い。
# ═══════════════════════════════════════════════════════════════════════════
import logging
import os
import sys

_LOG_PATH = os.environ.get("AIBO_GEN_LOG", "/content/aibo_gen.log")
_FMT = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")


def _has_spigot(_lg):
    return any(getattr(_h, "_aibo_spigot", False) for _h in _lg.handlers)


# ── (1) ROOT logger に FileHandler(logger 名非依存で全 logging を捕捉)──────────
#    AIBO_v7 は propagate=True なので root の handler に必ず届く。root だけに付ければ
#    二重書き込みも起きない(AIBO_v7 にも付けると propagate で 2 回書かれる)。
_root = logging.getLogger()
_attached = False
if not _has_spigot(_root):
    _fh = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    _fh.setLevel(logging.DEBUG)              # handler 側は広く拾う(logger level が gate)
    _fh.setFormatter(_FMT)
    _fh._aibo_spigot = True                  # 二重 attach 検出マーカー
    _root.addHandler(_fh)
    _attached = True
    print(f"[spigot] root に FileHandler を attach → {_LOG_PATH}", flush=True)
else:
    print(f"[spigot] root に既に attach 済み → {_LOG_PATH}(二重 attach 回避)", flush=True)

# ── (2) [OSS] APPLIED(=logger.info)を確実に通す: level / propagate を保証 ──────
#    prod 非改変の範囲(level は「下げるだけ」=より多く拾う方向。生成挙動は変えない)。
if _root.level == logging.NOTSET or _root.level > logging.INFO:
    _root.setLevel(logging.INFO)
_av = logging.getLogger("AIBO_v7")
if _av.level != logging.NOTSET and _av.level > logging.INFO:
    _av.setLevel(logging.INFO)
_av.propagate = True                         # 誰かが propagate=False にしていても root 経路で拾う


# ── (3) sys.stdout を tee(print 由来のマーカーも file に乗せる)──────────────────
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
    print("[spigot] stdout tee は既に有効(二重 tee 回避)", flush=True)

# ── self-test: logging と print の両経路を撃って file>0 を即確認 ───────────────
_av.info("[spigot] self-test (logging→root FileHandler→file) ✓")
print("[spigot] self-test (print→stdout tee→file) ✓", flush=True)
for _h in _root.handlers:
    try:
        _h.flush()
    except Exception as _e:
        print(f"[spigot] (warn) handler flush 失敗: {type(_e).__name__}: {_e}", flush=True)
_size = os.path.getsize(_LOG_PATH) if os.path.exists(_LOG_PATH) else 0
print(f"[spigot] {_LOG_PATH} size={_size}B / root.level={logging.getLevelName(_root.level)} "
      f"/ AIBO_v7.level={logging.getLevelName(_av.level)} propagate={_av.propagate}", flush=True)
if _size > 0:
    print("[spigot] ✅ 配線 OK(self-test が file に乗った)。UI で 1 枚生成 → "
          "!tail -n 120 /content/aibo_gen.log で `[OSS] APPLIED n=14 ✓` を確認", flush=True)
else:
    print("[spigot] ⚠️ self-test が file に乗らない。path/権限を確認(/content への書込みは通常可)", flush=True)
