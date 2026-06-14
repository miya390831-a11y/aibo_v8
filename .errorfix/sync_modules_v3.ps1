# ═══════════════════════════════════════════════════════════════════════════
# sync_modules_v3.ps1 — AIBO コアモジュール 4拠点同期 + md5 自己検証(恒久対策 B1)
#   ASCII-safe(日本語リテラル無し → PS5.1 ANSI .ps1 デコード問題に不感)。
#
#   v2 からの変更:
#     - 同期対象を「05/03 の2ファイル」から「コア全 .py + module_manifest.json + tools/」へ拡張
#       (今回 05 以外に 03/07/09/16 も desync していたため)。
#     - ★md5 自己検証を「成功扱いにしない」loud FAIL に格上げ:
#       コピー後に src<->dest を md5 比較し、1個でも不一致/欠落なら RESULT: SYNC-FAILED + exit 1。
#       = 「sync した」ではなく「md5 一致」を証拠にする(B3)。
#
#   使い方:
#     powershell -ExecutionPolicy Bypass -File .errorfix\sync_modules_v3.ps1
#   commit 前に tools\gen_manifest.py を実行して module_manifest.json を更新してから流すこと。
# ═══════════════════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$src = "C:\Users\yuuki\aibo_v7"

# 同期対象(runtime にロードされる=cached-module desync の起こり得るコア + ガード一式)
$files = @(
    "01_config.py", "02_colab_setup.py", "03_identity_engine.py", "04_pipeline_manager.py",
    "05_orchestrator.py", "06_ui.py", "07_main.py", "08_face_refiner.py", "09_fastapi_server.py",
    "10_mask_engine.py", "11_pulid_cn_pipeline.py", "15_makeup_engine.py",
    "16_pose_extractor.py", "17_neutralize_engine.py",
    "module_manifest.json",
    "tools\gen_manifest.py", "tools\check_manifest.py",
    "attach_aibo_log_spigot.py", "exp_portrait_verify_oneshot.py"
)

# 宛先(ASCII 固定2 + G: My Drive 動的解決)
$dests = New-Object System.Collections.Generic.List[string]
$dests.Add("C:\Users\yuuki\Downloads\AIBOV7")
$dests.Add("C:\Users\yuuki\Downloads\AIBOV7\3a")
if (Test-Path 'G:\') {
    $gRoot = Get-ChildItem 'G:\' -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'aibo_v7') } |
        Select-Object -First 1
    if ($gRoot) {
        $gDest = (Join-Path $gRoot.FullName 'aibo_v7')
        $dests.Add($gDest)
        Write-Host "G: My Drive resolved -> $gDest" -ForegroundColor Cyan
    } else { Write-Host "G: mounted but aibo_v7 not found" -ForegroundColor Yellow }
} else { Write-Host "G: not mounted" -ForegroundColor Yellow }

# copy(tools\ 等のサブフォルダは dest 側にも作る)
foreach ($d in $dests) {
    if (-not (Test-Path $d)) { Write-Host "DEST-MISSING: $d" -ForegroundColor Red; continue }
    foreach ($f in $files) {
        $sp = Join-Path $src $f
        if (-not (Test-Path $sp)) { Write-Host "SRC-MISSING: $sp" -ForegroundColor Red; continue }
        $dp = Join-Path $d $f
        $dpDir = Split-Path $dp -Parent
        if (-not (Test-Path $dpDir)) { New-Item -ItemType Directory -Path $dpDir -Force | Out-Null }
        Copy-Item -Path $sp -Destination $dp -Force
    }
    Write-Host "COPIED -> $d" -ForegroundColor Green
}

# ─── md5 自己検証(loud FAIL)───
Write-Host "`n--- MD5 SELF-VERIFY (src <-> each dest) ---"
$fail = $false
foreach ($f in $files) {
    $sp = Join-Path $src $f
    if (-not (Test-Path $sp)) { $fail = $true; Write-Host ("{0,-30} SRC-ABSENT" -f $f) -ForegroundColor Red; continue }
    $sh = (Get-FileHash $sp -Algorithm MD5).Hash
    foreach ($d in $dests) {
        $dp = Join-Path $d $f
        if (Test-Path $dp) {
            $dh = (Get-FileHash $dp -Algorithm MD5).Hash
            if ($dh -eq $sh) {
                Write-Host ("{0,-30} MATCH    {1}  [{2}]" -f $f, $sh.Substring(0,8), (Split-Path $d -Leaf))
            } else {
                $fail = $true
                Write-Host ("{0,-30} MISMATCH src={1} dst={2}  [{3}]" -f $f, $sh.Substring(0,8), $dh.Substring(0,8), $d) -ForegroundColor Red
            }
        } else {
            $fail = $true
            Write-Host ("{0,-30} ABSENT   [{1}]" -f $f, $d) -ForegroundColor Red
        }
    }
}
Write-Host ""
if ($fail) {
    Write-Host "RESULT: SYNC-FAILED (md5 mismatch/absent) — fix & re-run before restart/verify" -ForegroundColor Red
    exit 1
} else {
    Write-Host "RESULT: ALL-MATCH (every file md5-identical across all dests)" -ForegroundColor Green
    exit 0
}
