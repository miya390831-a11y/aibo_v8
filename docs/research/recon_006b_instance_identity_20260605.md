# RECON-006b — 対抗B 確定調査:FastAPI と Colab グローバルの orchestrator/ie は同一か

- 日付: 2026-06-05
- 担当: ダイナミックくろうど(特殊部隊・偵察)
- 種別: コード調査のみ(変更なし)。核非接触。
- 前提(RECON-006 follow-up): 「UI 生成直後に `orchestrator.ie._last_extract_error` が None のまま=この ie の extract を呼んでいない」と実機確認した、との報告。

---

## 結論(先に要点)

1. **FastAPI が生成で使う orchestrator/ie は、Colab セルに渡した `m.orchestrator`(とその `m.orchestrator.ie`)と同一オブジェクト。**
   FastAPI は **同一プロセスの daemon thread** で動き(07_main.py:466-468)、`attach_orchestrator(m.orchestrator)` でモジュールグローバル `_orchestrator_ref` にその参照を入れ(09:60)、生成はそれを使う(09:541)。新規生成も job ごと生成もしない。**渡した本人と同じ Python オブジェクト**。

2. **ただし、報告の根拠 `orchestrator.ie._last_extract_error` は「読む属性を間違えている」可能性が高い。**
   `_last_extract_error` は **`PuLIDExtractor` の属性**であって **`IdentityEngine`(=`ie`)の属性ではない**。`ie` 側にこの名前は定義も `__getattr__` も無い(03:1458〜、設定箇所は 03:238-299 すべて `PuLIDExtractor` 内)。
   → `ie._last_extract_error` を直接見ると **常に「無い/None」**。これは「extract を呼んでいない」証拠にはならない。**正しくは `orchestrator.ie.pulid_extractor._last_extract_error`**。

   つまり「対抗B 確定」の根拠は測定アーティファクトの疑い。**同一性は問題なく、見る場所がズレていた**、というのが最有力。

---

## 1. インスタンス同一性の証明(コード経路)

ビルドから生成までを 1 本の参照チェーンで追える(別物になる分岐は後述)。

- `07_main.py:198`(phase_d): `self.identity_engine = IdentityEngine(sys_cfg)` … ie を1個生成。
- `07_main.py:255-259`(phase_f): `CharacterOrchestrator(..., identity_engine=self.identity_engine, ...)`。
- `05_orchestrator.py:351`: `self.ie = identity_engine` … orchestrator は **渡された ie をそのまま保持**(コピーしない)。
  → `m.orchestrator.ie is m.identity_engine`。
- `07_main.py:447-463`(`launch_fastapi_in_background`): `srv_mod = import_module("09_fastapi_server")` → `srv_mod.attach_orchestrator(orchestrator_instance, ...)`。
- `09_fastapi_server.py:57-62`: `_orchestrator_ref = orch` … **モジュールグローバルに同じ参照を格納**。
- `07_main.py:465-468`: `run_server` を `threading.Thread(daemon=True)` で起動 → `09:1133-1136` `uvicorn.run(app, ...)`。**別スレッド・同一プロセス**=同じ `sys.modules`・同じ Python オブジェクト空間。
- 生成時 `09_fastapi_server.py:541`: `orch = _orchestrator_ref` → `:549` `orch.generate(...)` → `05:501` `self.ie.prepare(...)` → `03:1536` `self.pulid_extractor.extract(...)`。

→ **`launch_fastapi_in_background(m.orchestrator, ...)` に渡した `m.orchestrator` と、生成で使われる `_orchestrator_ref` は同一。`.ie` も同一。** FastAPI が裏で別 orchestrator を作る箇所は無い(09 全体で orchestrator の入手は `_orchestrator_ref` のみ。生成 09:541 / 素体化 09:988-1018 とも同じ参照)。

---

## 2. 「別物」になりうる分岐点(ここを実機で潰す)

同一性が崩れるのは次の運用パターンのみ。コード構造上の自動分岐ではなく、**セルの渡し方/再ロード由来**。

- **(a) attach に渡したオブジェクトと、後で覗いたオブジェクトが違う**
  例: `m = run()` で作った後に別セルで `AiboMain()` を作り直した / `launch_fastapi_in_background(別の orchestrator, ...)` を渡した / 旧セルの変数を覗いた。
  → `srv._orchestrator_ref is orchestrator` で一発判定(後述)。
- **(b) `09_fastapi_server` モジュールの二重ロード**
  `import_module("09_fastapi_server")` は `sys.modules` キャッシュで通常は同一だが、`importlib.reload` や `spec_from_file_location` で別モジュールオブジェクトを作ると **`_orchestrator_ref` グローバルが2つ**になる。稼働中 uvicorn は `launch_fastapi_in_background` 内の `srv_mod` 側に属する。後から別ハンドルで `_orchestrator_ref` を覗くと食い違う(ただしアプリ実体は attach 済みを使う)。
- **(c) `03`/`05` の `importlib.reload`**
  reload するとクラスオブジェクトが新しくなるが、**既存インスタンスは旧クラスのまま**。インスタンス同一性自体は壊れないが、`isinstance`/型表示が紛らわしくなる。
- **(d) 起動順の取り違え**
  `phase_g_launch_ui`(07:306)の `self.ui_app.launch(...)` は **ブロッキング**。FastAPI を attach する前に Gradio をブロッキング起動していると attach 漏れ → `_orchestrator_ref is None`(=503 になるはずなので、生成が走る現症状とは別系統)。

---

## 3. 測定の落とし穴(今回の本丸)

- `_last_extract_error` の所在:
  - 設定するのは **`PuLIDExtractor`** のメソッド内のみ(`03:238, 242, 264, 288, 289, 295, 299`)。`self` は `PuLIDExtractor`。
  - 読む正規ルートも `05:656-657`:
    ```python
    _ext = getattr(self.ie, "pulid_extractor", None)
    _extract_err = getattr(_ext, "_last_extract_error", None)
    ```
    = **`ie.pulid_extractor._last_extract_error`**。
  - `IdentityEngine`(`03:1458`〜、`__init__` 1469-1498)は `self._last_extract_error` を一切設定せず、`__getattr__` も無い。
  - → `orchestrator.ie._last_extract_error` は **存在しない属性**。直接アクセスなら `AttributeError`、`getattr(..., None)` なら常に `None`。**「呼んでいない」証拠にならない**。
- 同様の取り違え注意: `_last_face_count` も `PuLIDExtractor` 側(`03:319`)。`ie` 直下には無い。
- pulid_extractor が None のケース(真の対抗B): `sys_cfg.enable_pulid=False` なら `ie.pulid_extractor=None`(`03:1476`)。この場合 prepare の `03:1534 if self.pulid_extractor:` で PuLID を skip。
  - **ただし**「`orchestrator.ie.pulid_extractor.extract(ref)` を直接叩けて成功」した、という確定事実が **同じ ie** に対するものなら、`ie.pulid_extractor` は **非 None**=この経路の対抗B は否定される。standalone を叩いた ie が `orchestrator.ie` と同一かが分岐点(下の1行で確認)。

---

## 4. 実機で確認できる1行(同一性 + 正しい属性)

Colab グローバルを `orchestrator`(= `m.orchestrator`)とする。

**(A) 同一性チェック:**
```python
import importlib; srv = importlib.import_module("09_fastapi_server")
print("orch同一:", srv._orchestrator_ref is orchestrator,
      "| ie同一:", srv._orchestrator_ref.ie is orchestrator.ie,
      "| extractor:", srv._orchestrator_ref.ie.pulid_extractor is not None,
      "| extractor同一:", srv._orchestrator_ref.ie.pulid_extractor is orchestrator.ie.pulid_extractor)
```
- すべて True かつ extractor=非None なら「同一オブジェクト・PuLID 有効」が確定。

**(B) 正しい属性で再判定(UI 生成を1回した直後に実行):**
```python
ext = orchestrator.ie.pulid_extractor
print("extract_err:", getattr(ext, "_last_extract_error", "ATTR_MISSING"),
      "| init_err:", getattr(ext, "_last_init_error", "ATTR_MISSING"),
      "| face_count:", getattr(ext, "_last_face_count", "ATTR_MISSING"))
```
- `extract_err` が `"get_id_embedding が None (顔未検出…)"` → **extract は呼ばれていて顔未検出**=本命A(RECON-006 のクロップ起因)。対抗B は否定。
- `extract_err` が `None`(かつ A で extractor 同一=True なのに更新されない)→ 本当に extract 未到達。その時だけ「prepare 前で分岐/別経路」を疑う。
- `srv._orchestrator_ref.ie.pulid_extractor is None` → enable_pulid False=対抗B 確定。

> 補足: server ログ `[OBS-SUMMARY]`(05:664-678)は既に **正しい属性**を読んで `↳ 失敗理由 : extract=... / init=...` を出している。手元変数を覗くより **このログ行が最も信頼できる一次情報**。

---

## 5. 推奨(案・決定は司令部)

1. 上記 (A)(B) を実行。ほぼ確実に「同一オブジェクト・extractor 非None」になり、`_last_extract_error` を **`ie.pulid_extractor` 側**で読めば中身が出る、という結果になるはず。
2. その値が `get_id_embedding が None ...` なら、**対抗B は誤判定**で原因は RECON-006 本命A(UI クロップ + Phase0Sniper 二重クロップ→顔未検出)。→ RECON-006 の案1(snipe 前原画でリトライ)へ。
3. 万一 (A) が False(別オブジェクト)になった場合のみ、本書 §2 の (a)〜(d) を順に潰す(セルの渡し違い/二重ロード/reload)。

---

## 参照(file:line)

- FastAPI attach/使用: `09_fastapi_server.py:53-71, 541, 711-720, 988-1018, 1133-1136`
- 起動(同一プロセス・別スレッド): `07_main.py:447-471`
- ie 生成→orchestrator 保持: `07_main.py:198, 255-259` / `05_orchestrator.py:351, 501`
- `_last_extract_error` の所在(PuLIDExtractor 専用): `03_identity_engine.py:238-299, 366`
- OBS 正規読み出し: `05_orchestrator.py:656-678`(`getattr(self.ie, "pulid_extractor", None)` 経由)
- pulid_extractor の None 条件: `03_identity_engine.py:1469-1498`(特に 1476)
