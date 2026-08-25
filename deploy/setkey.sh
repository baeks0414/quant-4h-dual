#!/usr/bin/env bash
# Put the Binance credentials into /etc/quant4h.env without an editor.
#
#   bash /opt/quant-4h-dual/deploy/setkey.sh
#
# Editing the file over a VNC console is how this script came to exist: a paste
# split mid-line, leaving "BINANCE_API_KEY" with no "=" and the value stranded
# on a line of its own. Typing into a `read -rs` prompt instead means the shell
# receives the paste as one string, nothing is echoed to the screen, and the
# value is validated before it is written.

set -uo pipefail

ENV_FILE=${ENV_FILE:-/etc/quant4h.env}

ok()   { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '   \033[1;33mwarn\033[0m %s\n' "$*"; }
say()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }
[ -f "$ENV_FILE" ] || { bad "$ENV_FILE missing — run setup.sh first"; exit 1; }

BAK="$ENV_FILE.bak"
cp -p "$ENV_FILE" "$BAK"
say "backup"
ok "previous file kept at $BAK"

# Any line that is neither blank, nor a comment, nor NAME=value is wreckage from
# a broken paste. Sourcing it would run it as a command, so drop it.
say "repairing the file"
STRAY=$(grep -cvE '^[[:space:]]*($|#|[A-Za-z_][A-Za-z0-9_]*=)' "$ENV_FILE")
if [ "$STRAY" -gt 0 ]; then
  warn "$STRAY malformed line(s) found — removing them"
  grep -nvE '^[[:space:]]*($|#|[A-Za-z_][A-Za-z0-9_]*=)' "$ENV_FILE" \
    | sed 's/:.*/:  <removed, contents hidden>/' | sed 's/^/        line /'
else
  ok "no malformed lines"
fi
grep -E '^[[:space:]]*($|#|[A-Za-z_][A-Za-z0-9_]*=)' "$BAK" > "$ENV_FILE"

current() {
  # last assignment wins, matching how the shell sources the file
  grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2-
}

ask() {
  local name=$1 have cur val clean len junk
  cur=$(current "$name")
  have=${#cur}
  say "$name"
  if [ "$have" -gt 0 ]; then
    printf '   currently set, %d characters. press Enter alone to keep it.\n' "$have"
  else
    printf '   currently missing.\n'
  fi
  for attempt in 1 2 3; do
    printf '   paste the value (nothing will be shown), then Enter: '
    IFS= read -rs val; echo
    if [ -z "$val" ] && [ "$have" -gt 0 ]; then
      ok "kept the existing value"
      return 0
    fi
    # strip carriage returns and surrounding whitespace that pastes drag along
    clean=$(printf '%s' "$val" | tr -d '\r\n\t ' )
    len=${#clean}
    junk=$(printf '%s' "$clean" | tr -d 'A-Za-z0-9' | wc -c)
    if [ "$len" -eq 0 ]; then
      bad "nothing was received (attempt $attempt of 3)"
    elif [ "$junk" -ne 0 ]; then
      bad "contains $junk non-alphanumeric character(s) (attempt $attempt of 3)"
    elif [ "$len" -ne 64 ]; then
      bad "length $len, expected 64 — the paste was truncated (attempt $attempt of 3)"
    else
      sed -i "/^$name=/d" "$ENV_FILE"
      printf '%s=%s\n' "$name" "$clean" >> "$ENV_FILE"
      ok "written, 64 characters, charset clean"
      return 0
    fi
  done
  bad "$name not set after 3 attempts"
  return 1
}

FAILED=0
ask BINANCE_API_KEY    || FAILED=1
ask BINANCE_API_SECRET || FAILED=1

chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

say "result"
if [ "$FAILED" -ne 0 ]; then
  bad "credentials incomplete — rerun this script"
  exit 1
fi
ok "$ENV_FILE written, mode 600"
echo
echo "   verifying..."
exec bash "$(dirname "$0")/check.sh"
