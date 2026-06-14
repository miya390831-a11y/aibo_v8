# 報告: (A) 05 再同期(md5検証付き)+ (B) module desync 恒久対策 + (C) ルール文書化

- 日付: 2026-06-14
- 担当: 統括(再同期・md5検証・ガード実装・文書化・ローカルコミット)
- 状態: **A 完了(4拠点 md5 全一致)/ B 実装・自己テスト完了 / C 文書化完了 / ローカルコミット完了。**
  **GATE① 緑の最終確定は Colab 実機=PO 再起動→再検証 待ち**(ここで「緑」とは言わない)。

## ★追加で判明した重要事実(正直に)
desync は **05 単独ではなかった**。local(=committed)vs G ドライブで **5 ファイルが不一致**:
`03 / 05 / 07 / 09 / 16`。さらに **G ドライブ 05 は GATE① テスト時点で既に OSS ブロック搭載**
(`_oss_force_sigmas`×3・mtime 06-14 00:03)だった。
→ 真因は「Drive 上のファイルが旧」よりも **runtime のモジュールキャッシュが旧**(更新後に
クリーン再起動されず、旧 05 が import 済のまま)である可能性が高い。
→ だから **B2 は file md5 だけでなく runtime 実ロード(__file__)を見る**設計にし、**B3(必ず再起動)**
を対にした。前回の「stale 05」結論は方向は正しいが、ファイル desync + runtime キャッシュの複合だった。

## A. 05(+他4ファイル)再同期 — md5 全一致を確認
- `.errorfix/sync_modules_v3.ps1` で全コア .py + manifest + tools を 4拠点へ。**md5 自己検証 = ALL-MATCH**。

| file | src/4拠点 md5(raw) | 状態 |
|---|---|---|
| 05_orchestrator.py | `4541CEE4` | ALL-MATCH(旧 G=d26cc739 から更新) |
| 03_identity_engine.py | `FA38B952` | ALL-MATCH(旧 G=a06decbb) |
| 07_main.py | `39B57A70` | ALL-MATCH(本タスクで編集) |
| 09_fastapi_server.py | `9DF8E88E` | ALL-MATCH(旧 G=b08c449f) |
| 16_pose_extractor.py | `CD96F5BE` | ALL-MATCH(旧 G=b57b43f4) |
| 01/02/04/06/08/10/11/15/17 | (各一致) | ALL-MATCH(元から一致) |
| module_manifest.json / tools/*.py / attach_aibo_log_spigot.py / exp_portrait_verify_oneshot.py | (各一致) | ALL-MATCH |

- 検証: G/05 は now `inject-point reached`=1 + `_oss_force_sigmas`=3(新版確定)。
  G/05 の**正規化 md5=4055f4a5** = committed manifest 05 と一致(再起動後 preflight 緑になる)。

## B. 恒久対策(silent desync を build 時に STOP)
| 区分 | 内容 | 場所 |
|---|---|---|
| B1 sync 自己検証 | 全コア .py + manifest + tools を4拠点コピー→src↔dest md5 比較→不一致は **loud FAIL/exit1** | `.errorfix/sync_modules_v3.ps1` |
| B2 manifest 生成 | コア .py の**改行正規化 md5** を json 記録(CRLF/LF 非依存) | `tools/gen_manifest.py` → `module_manifest.json` |
| B2 preflight | runtime 実ロード(`__file__`)の md5 を manifest と照合・不一致で SystemExit | `tools/check_manifest.py` |
| B2 build フック | `run()` 冒頭(build 前)で preflight 自動実行。ツール不在は warn 続行 | `07_main.py`(Phase 0) |
| B3 プロセス | verify/ship は preflight 緑まで回さない | CLAUDE.md / docs/ops |

### 自己テスト(このPCで実施)
- **happy path(strict)**: 14 モジュール全一致 → `✅ runtime modules == committed` / 戻り True。
- **negative(05 を偽 md5 に改竄)**: `NEGTEST=OK_STOPPED`(SystemExit 発火=desync を確実に STOP)。
- `[OBS] module manifest` 実出力:
  ```
  [OBS] module manifest | 01=c7d16e5d 02=7e53e4cc 03=a7556198 04=045100c0 05=4055f4a5
   06=4a3232f3 07=6e7f8a1a 08=48cd93f6 09=ddd35c2a 10=5358f699 11=11005606 15=922fca01
   16=5370cb94 17=36f0de36
  ```
- desync 時 STOP メッセージ例:
  ```
  ❌ MODULE DESYNC 検出(committed manifest と不一致 → build STOP):
     05_orchestrator.py  runtime=4055f4a5  expected=deadbeef  src=loaded  (…/05_orchestrator.py)
     対処: 該当 .py を G:\マイドライブ\aibo_v7\ に再同期(md5 一致を確認)→ Colab 再起動。
     ※ 『sync した』は証拠ではない。『manifest 一致』が verify/ship ゲートの前提。
  ```
- `python -m py_compile` 05/07/tools/spigot → **OK**。

## C. ルール文書化
- `CLAUDE.md` repo 運用規約に「module desync 防止(恒久ルール)」3条を追記(口伝→自動ゲート昇格)。
- `docs/ops/module_desync_guard.md` 新規(B1/B2/B3 の使い方・標準手順・限界)。
- 統括メモリにも反映(`module-desync-guard`)。

## 厳守事項の遵守
- A=同期+検証のみ / B=検証ゲート追加のみ。**生成ロジック非改変**(07 の追加は build 前 preflight 呼出し1つ)。
- **検証済み構成 不変**:no-Hyper / OSS schedule / pass2 off / phase3 off / PuLID 0.7 / Setting A 7値・
  PHASE3A/3B に一切触れていない。`set_lora_strength` 不使用。silent fail なし。
- 最小・revertible。git **ローカルコミットのみ**(push は PO 判断)。
- ★改行正規化 md5 設計:CRLF(Win/Drive)/LF(git)差で false desync を出さない(罠回避)。

## ★PO 次アクション(GATE① 緑の確定)
1. `.errorfix\sync_modules_v3.ps1` は実施済(ALL-MATCH)。**Drive 反映の最終確認のみ**でよい。
2. **Colab 再起動**(`os.kill(os.getpid(),9)`)→ Cell 0 build。
   - build ログに `[OBS] module manifest …` + `✅ runtime modules == committed` が出る(desync なら STOP)。
3. ログ蛇口 attach → 検証セル + UI 1枚 → `!tail -n 120 /content/aibo_gen.log`。
   - 期待: `🧩 [OSS] inject-point reached…` + `[OSS] APPLIED n=14 maxΔ≈0.0 ✓` → **GATE① 緑**。
4. 万一 manifest STOP が出たら、表示された file を Drive Web UI で手動再アップ → 再 sync → 再起動。

---
**要点:** A=全コア .py 再同期し **4拠点 md5 全一致**を確認(desync は 05 含む5ファイルだった)。
B=**build 時に runtime モジュール md5 を committed manifest と照合し、ズレたら STOP**(+ sync 自己検証)で
silent desync を恒久封殺。自己テストで happy/negative 両方確認済。C=CLAUDE.md + docs/ops + メモリに明文化。
検証済み構成は不変・push 保留。**GATE① 緑は PO 再起動→再検証で確定。**
