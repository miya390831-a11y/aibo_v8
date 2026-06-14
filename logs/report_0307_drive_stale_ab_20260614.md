# 報告: 03/07 Drive 内容が古い — A/B 判定と修正(GATE① 再検証の前段)

- 日付: 2026-06-14
- 担当: 統括(git 実測・A/B 判定・G: 再書込み・文書化・ローカルコミット)
- 状態: **A/B 判定確定 / 原因特定 / docs 反映 / ローカルコミット完了。**
  **クラウド確定(Web UI 手動アップ)と再検証は PO 待ち**(desktop 同期は clobber に負けるため)。

## 0. 判定: 03/07 とも **Fork A(Drive が古い・manifest は正)**
git 実測(全て **正規化 CRLF→LF→md5[:8]**):

| file | working(PC) | git HEAD | git cdc4c8e | manifest | PO Drive now | 判定 |
|---|---|---|---|---|---|---|
| 03_identity_engine.py | a7556198 | a7556198 | a7556198 | a7556198 | **3b297f80** | **Fork A** |
| 07_main.py | 6e7f8a1a | 6e7f8a1a | 6e7f8a1a | 6e7f8a1a | **9f06cc31** | **Fork A** |

- **committed 正規化 md5 == manifest 期待値** で完全一致(両ファイル)→ **manifest は正しい。Drive 実物が旧。**
- git log: 07 は cdc4c8e(本ガード追加)で改変 → 旧 Drive と差が出るのは当然。
  03 は cdc4c8e で未改変・最終変更は `6e1b4aa`(2026-06-07)→ Drive の 3b297f80 は **6e1b4aa より前の旧 03**。
- **Fork B(manifest バグ)ではない**。03/07 とも基準(manifest)は実 committed と一致。05=4055f4a5 も不変(OSS 正常)。

## 1. 原因: DriveFS clobber(「sync 完了 ≠ 正しい中身」)
- `.errorfix/sync_modules_v3.ps1` は再三 `RESULT: ALL-MATCH` を出す(G:\ 書込み直後は正)。
  にもかかわらず G:\ の 03/07 は **mtime 16:02(新しい)なのに中身が旧** に化けていた。
- G: は Google **DriveFS** 仮想マウント(`%LOCALAPPDATA%\Google\DriveFS` キャッシュ確認済)。
  → **クラウド側の旧 03/07 を、こちらの local 書込みに被せて revert(clobber)**。
  mtime は revert 時刻で更新されるため「最新」に見えるが中身は旧。
  **PO 指摘どおり「ラグでなく、古い中身が新しい mtime で書かれた」**を裏取り。
- ∴ **mtime も「ALL-MATCH 表示」も、中身が正しい証拠にならない。証拠は「正規化 md5 == expected」のみ。**

## 2. 実施した修正(best-effort・desktop 経由)
- 正版(PC committed)を G:\ へ再書込み → 直後の正規化 md5:
  ```
  G/03 = a7556198 (want a7556198)  ✅
  G/07 = 6e7f8a1a (want 6e7f8a1a)  ✅
  ```
- ただし **DriveFS が再 clobber する可能性が高い**(16:02 で一度 revert された実績)。
  desktop 書込みは clobber に負けうるため、これは暫定。**確定は §3(PO・Web UI)**。

## 3. ★PO 必須アクション(クラウドを正にする=確実手段)
1. **Drive Web UI で手動アップロード**:drive.google.com → MyDrive/aibo_v7 →
   **03_identity_engine.py / 07_main.py を PC の committed 版で上書き**(クラウドへ直書き=stale キャッシュをバイパス)。
   - 正版の所在: `C:\Users\yuuki\aibo_v7\03_identity_engine.py` / `07_main.py`(= cdc4c8e、push 未のため GitHub 経由不可・PC が唯一の正)。
2. アップ後、**PO の正規化 md5 セル**で `03=a7556198 / 07=6e7f8a1a`(expected 一致)を確認 ← ここを通るまで進めない。
3. Drive 再マウント → **Colab 再起動 → Cell 0** →
   `[OBS] module manifest …` + `✅ runtime modules == committed`(STOP しない)を確認。
4. そのまま **GATE① 再検証**:ログ蛇口 attach → UI 1枚 → `!tail -n 120 /content/aibo_gen.log` で
   `🧩 [OSS] inject-point reached…` + `[OSS] APPLIED n=14 maxΔ≈0.0 ✓`。

## 4. 文書化(C・恒久ルール追記)
`docs/ops/module_desync_guard.md` に「事例: DriveFS clobber」を追記:
- **sync 完了 ≠ 正しい中身**(mtime 新でも中身旧)。証拠は常に正規化 md5 == expected。
- **DriveFS clobber 時は Web UI 手動アップ**(desktop 同期は当てにしない)。
- **manifest 期待値は必ず実 committed から生成**(編集中バッファから作らない)。

## 厳守事項
- 生成非改変・**検証済み構成不変**(Setting A 7値/PHASE3A3B/no-Hyper/**OSS 05=4055f4a5 維持**/pass2off/phase3off/PuLID 0.7)。
- コード変更なし(docs/report のみ)。最小・revertible。**ローカルコミットのみ**(push=PO)。
- manifest ガードは **正しく機能**(古い 03/07 で黙って走るのを build 入口で STOP)。基準は実 committed=正。

---
**要点:** 03/07 は **Fork A(Drive 実物が旧・manifest は正)**。git 実測で committed 正規化 md5 == 期待値を確認。
原因は **DriveFS の clobber**(クラウド旧版が local 書込みを revert・mtime は新)。desktop 再書込みは暫定で
負けうるため、**PO が Web UI で 03/07 を手動アップ → 正規化 md5 == expected を確認 → 再起動 → Cell 0 全緑 →
GATE① 再検証**。05(OSS)は正常・不変。
