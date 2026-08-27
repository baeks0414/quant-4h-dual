#!/usr/bin/env bash
# Bring an installed server up to date, then run the pre-flight check.
#
#   curl -fsSL https://raw.githubusercontent.com/baeks0414/quant-4h-dual/master/deploy/update.sh | bash
#
# One short line, because a console that drops characters mid-paste turns a long
# sed expression into a different sed expression, and this one edits the file
# holding the API keys.
#
# Safe to run repeatedly. It does not enable the timer and does not change
# DRY_RUN; going live stays a deliberate, separate act.

set -uo pipefail

APP_DIR=${APP_DIR:-/opt/quant-4h-dual}
ENV_FILE=${ENV_FILE:-/etc/quant4h.env}

say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad() { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }
[ -d "$APP_DIR/.git" ] || { bad "$APP_DIR is not a checkout — run setup.sh first"; exit 1; }

say "code"
BEFORE=$(git -C "$APP_DIR" rev-parse --short HEAD)
sudo -u quant git -C "$APP_DIR" pull -q --ff-only || { bad "git pull failed"; exit 1; }
AFTER=$(git -C "$APP_DIR" rev-parse --short HEAD)
[ "$BEFORE" = "$AFTER" ] && ok "already at $AFTER" || ok "$BEFORE -> $AFTER"

say "settings"
# A fixed order cap below the capital refuses every entry, silently, forever.
# The caps derive from the capital in use unless overridden, so the override is
# removed rather than corrected.
if grep -qE '^(MAX_ORDER_USD|MAX_GROSS_USD)=' "$ENV_FILE"; then
  cp -p "$ENV_FILE" "$ENV_FILE.bak"
  KEYS_BEFORE=$(grep -cE '^BINANCE_API_(KEY|SECRET)=.{20,}' "$ENV_FILE")
  grep -vE '^(MAX_ORDER_USD|MAX_GROSS_USD)=' "$ENV_FILE.bak" > "$ENV_FILE"
  KEYS_AFTER=$(grep -cE '^BINANCE_API_(KEY|SECRET)=.{20,}' "$ENV_FILE")
  if [ "$KEYS_BEFORE" != "$KEYS_AFTER" ]; then
    cp -p "$ENV_FILE.bak" "$ENV_FILE"
    bad "editing $ENV_FILE lost a credential line; restored from .bak"
    exit 1
  fi
  chmod 600 "$ENV_FILE"
  ok "removed the fixed order caps (previous file kept as $ENV_FILE.bak)"
else
  ok "no fixed order caps set; they scale with capital"
fi

say "systemd units"
# git pull updates the copies under deploy/, not the ones systemd reads
install -m 644 "$APP_DIR/deploy/quant4h.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/quant4h.timer"   /etc/systemd/system/
systemctl daemon-reload
ok "reinstalled and reloaded"

if systemctl is-enabled --quiet quant4h.timer 2>/dev/null; then
  ok "timer is ENABLED — the strategy is running on the bar"
else
  ok "timer is not enabled — nothing runs on its own yet"
fi

say "clock"
if command -v timedatectl >/dev/null 2>&1; then
  timedatectl set-ntp true >/dev/null 2>&1 || true
  SYNC=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
  [ "$SYNC" = "yes" ] && ok "system clock synchronised" \
    || printf '   \033[1;33mwarn\033[0m clock not yet synchronised; Binance rejects skewed timestamps (-1021)\n'
fi

exec bash "$APP_DIR/deploy/check.sh"
