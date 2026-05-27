# AIBO Desktop Shortcut Setup
# Creates: AIBO Cyber Studio, AIBO Claude Code, AIBO Colab

$Host.UI.RawUI.WindowTitle = "AIBO · Desktop Setup"

Write-Host ""
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host "  AIBO デスクトップアイコン整備" -ForegroundColor Cyan
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host ""

$desktop = [Environment]::GetFolderPath("Desktop")
$aiboDir = "C:\Users\yuuki\aibo_v7"
$iconsDir = Join-Path $aiboDir "icons"
$shell = New-Object -ComObject WScript.Shell

function Get-IconLocation {
    param([string]$IconFile, [string]$Fallback)
    $path = Join-Path $iconsDir $IconFile
    if (Test-Path $path) { return "$path,0" } else { return $Fallback }
}

# ============================================
# 1. AIBO Cyber Studio (既存 · 互換性のため上書き対応)
# ============================================
Write-Host "  [1/3] AIBO Cyber Studio ショートカット作成中..." -ForegroundColor Yellow

$shortcut1 = $shell.CreateShortcut("$desktop\AIBO Cyber Studio.lnk")
$shortcut1.TargetPath = "$aiboDir\start_aibo.bat"
$shortcut1.WorkingDirectory = $aiboDir
$shortcut1.Description = "AIBO Cyber Studio · バックエンド + フロントエンド起動"
$shortcut1.IconLocation = (Get-IconLocation "aibo.ico" "shell32.dll,13")
$shortcut1.Save()

Write-Host "    [OK] $desktop\AIBO Cyber Studio.lnk" -ForegroundColor Green

# ============================================
# 2. AIBO Claude Code (新規)
# ============================================
Write-Host "  [2/3] AIBO Claude Code ショートカット作成中..." -ForegroundColor Yellow

$shortcut2 = $shell.CreateShortcut("$desktop\AIBO Claude Code.lnk")
$shortcut2.TargetPath = "$aiboDir\start_claude_code.bat"
$shortcut2.WorkingDirectory = $aiboDir
$shortcut2.Description = "AIBO Cyber Studio · Claude Code CLI 開発環境"
$shortcut2.IconLocation = (Get-IconLocation "claude.ico" "shell32.dll,25")
$shortcut2.Save()

Write-Host "    [OK] $desktop\AIBO Claude Code.lnk" -ForegroundColor Green

# ============================================
# 3. AIBO Colab (新規)
# ============================================
Write-Host "  [3/3] AIBO Colab ショートカット作成中..." -ForegroundColor Yellow

$shortcut3 = $shell.CreateShortcut("$desktop\AIBO Colab.lnk")
$shortcut3.TargetPath = "$aiboDir\start_aibo_colab.bat"
$shortcut3.WorkingDirectory = $aiboDir
$shortcut3.Description = "AIBO Cyber Studio · Colab Notebook 起動"
$shortcut3.IconLocation = (Get-IconLocation "colab.ico" "shell32.dll,14")
$shortcut3.Save()

Write-Host "    [OK] $desktop\AIBO Colab.lnk" -ForegroundColor Green

# ============================================
# 4. AIBO Emergency Stop (新規 · 緊急用)
# ============================================
Write-Host "  [4/4] AIBO 緊急停止 ショートカット作成中..." -ForegroundColor Yellow

$shortcut4 = $shell.CreateShortcut("$desktop\AIBO Emergency Stop.lnk")
$shortcut4.TargetPath = "$aiboDir\emergency_stop.bat"
$shortcut4.WorkingDirectory = $aiboDir
$shortcut4.Description = "AIBO Cyber Studio · 緊急停止 (Claude Code 暴走時)"
$shortcut4.IconLocation = (Get-IconLocation "stop.ico" "shell32.dll,131")
$shortcut4.Save()

Write-Host "    [OK] $desktop\AIBO Emergency Stop.lnk" -ForegroundColor Green

# ============================================
# 結果サマリ
# ============================================
Write-Host ""
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host "  作成完了 (4 アイコン)" -ForegroundColor Cyan
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  AIBO Cyber Studio        -> start_aibo.bat" -ForegroundColor White
Write-Host "  AIBO Claude Code         -> start_claude_code.bat [BYPASS]" -ForegroundColor White
Write-Host "  AIBO Colab               -> start_aibo_colab.bat" -ForegroundColor White
Write-Host "  AIBO Emergency Stop      -> emergency_stop.bat" -ForegroundColor Red
Write-Host ""
Write-Host "  [NOTE]" -ForegroundColor Yellow
Write-Host "    - icons\ フォルダにアイコン画像がない場合は default アイコン" -ForegroundColor Gray
Write-Host "    - start_aibo_colab.bat の COLAB_URL を更新してください" -ForegroundColor Gray
Write-Host ""
