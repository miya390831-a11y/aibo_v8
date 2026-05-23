# AIBO Cyber Studio - Desktop Shortcut Setup
# このスクリプトを実行すると、デスクトップに "AIBO Cyber Studio" のショートカットを作成します

$scriptDir = $PSScriptRoot
$batPath = Join-Path $scriptDir "start_aibo.bat"
$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "AIBO Cyber Studio.lnk"

if (-not (Test-Path $batPath)) {
    Write-Host "❌ start_aibo.bat not found at: $batPath" -ForegroundColor Red
    Write-Host "   このスクリプトと同じフォルダに start_aibo.bat が必要です"
    exit 1
}

try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($shortcutPath)
    $Shortcut.TargetPath = $batPath
    $Shortcut.WorkingDirectory = $scriptDir
    $Shortcut.IconLocation = "shell32.dll,13"
    $Shortcut.Description = "AIBO Cyber Studio - One-click launcher"
    $Shortcut.Save()
    
    Write-Host "✅ デスクトップショートカット作成完了:" -ForegroundColor Green
    Write-Host "   $shortcutPath"
    Write-Host ""
    Write-Host "以降はデスクトップの 'AIBO Cyber Studio' アイコンをダブルクリックで起動可能"
} catch {
    Write-Host "❌ ショートカット作成失敗: $_" -ForegroundColor Red
    exit 1
}
