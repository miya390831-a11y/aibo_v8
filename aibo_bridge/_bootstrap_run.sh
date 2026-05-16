#!/usr/bin/env bash
set -euo pipefail
ROOT="/mnt/c/Users/yuuki/aibo_v7/aibo_bridge"
TF="$ROOT/.tokens_tmp.txt"
LOG="$ROOT/logs/bootstrap_wsl.log"
GH_WIN="/mnt/c/Program Files/GitHub CLI/gh.exe"
mkdir -p "$ROOT/logs"
: >"$LOG"
if [ -x "$GH_WIN" ]; then
  cat > /tmp/aibo-gh <<EOF
#!/usr/bin/env bash
exec "$GH_WIN" "\$@"
EOF
  chmod +x /tmp/aibo-gh
  export PATH="/tmp:${PATH}"
fi
{
  sed 's/\r$//' "$TF"
  printf 'y\ny\ny\n'
} | bash "$ROOT/bootstrap.sh" >>"$LOG" 2>&1
