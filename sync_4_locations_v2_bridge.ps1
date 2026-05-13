# AIBO 4 拠点同期 (PowerShell 版 · AIBO Bridge 対応)
# 起票: CTO Kuroudo (YOLO Mode)

$LOCATIONS = @(
    "C:\Users\yuuki\Downloads\AIBOV7",
    "C:\Users\yuuki\Downloads\AIBOV7\3a"
)

$EXCLUDE_DIRS = @(
    ".git",
    "_backups",
    "__pycache__",
    "aibo_bridge\logs",
    "aibo_bridge\inbox",
    "aibo_bridge\outbox",
    "aibo_bridge\bot\venv",
    "aibo_bridge\bot\__pycache__",
    ".cline-configs"
)

$EXCLUDE_FILES = @(
    "*.bak",
    ".env",
    ".env.*",
    "*.tmux.log"
)

$SOURCE = "C:\Users\yuuki\aibo_v7"

foreach ($dest in $LOCATIONS) {
    Write-Host "Syncing to $dest" -ForegroundColor Cyan
    if (-not (Test-Path $dest)) {
        New-Item -ItemType Directory -Path $dest -Force | Out-Null
    }
    robocopy $SOURCE $dest /MIR /XD $EXCLUDE_DIRS /XF $EXCLUDE_FILES /NFL /NDL /NJH /NJS | Out-Null
    Write-Host "$dest OK" -ForegroundColor Green
}
