#!/usr/bin/env bash
# One-shot VPS setup for the 4h dual-sleeve real-money runner.
#
# Web and VNC consoles routinely drop characters when a long block is pasted,
# which is how this script came to exist: paste one short line instead.
#
#   curl -fsSL https://raw.githubusercontent.com/baeks0414/quant-4h-dual/master/deploy/setup.sh | bash
#
# Safe to run repeatedly. It creates nothing it has not checked for first, and
# it never writes secrets: /etc/quant4h.env is left for you to fill in by hand.

set -euo pipefail

APP_DIR=/opt/quant-4h-dual
LOG_DIR=/var/log/quant4h
ENV_FILE=/etc/quant4h.env
REPO=https://github.com/baeks0414/quant-4h-dual

say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[1;32mok\033[0m  %s\n' "$*"; }
bad() { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }

say "user and directories"
id quant >/dev/null 2>&1 || adduser --system --group quant >/dev/null
mkdir -p "$APP_DIR" "$LOG_DIR"
chown -R quant:quant "$APP_DIR" "$LOG_DIR"
ok "quant user, $APP_DIR, $LOG_DIR"

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip git curl >/dev/null
ok "python3-venv python3-pip git curl"

say "code"
if [ -d "$APP_DIR/.git" ]; then
  sudo -u quant git -C "$APP_DIR" pull -q --ff-only || true
  ok "repo updated"
else
  sudo -u quant git clone -q "$REPO" "$APP_DIR"
  ok "repo cloned"
fi

say "python environment"
[ -x "$APP_DIR/.venv/bin/python" ] || sudo -u quant python3 -m venv "$APP_DIR/.venv"
sudo -u quant "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u quant "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR"
ok "venv ready"

say "systemd units"
install -m 644 "$APP_DIR/deploy/quant4h.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/quant4h.timer"   /etc/systemd/system/
systemctl daemon-reload
ok "quant4h.service and quant4h.timer installed (timer NOT started yet)"

if [ ! -f "$ENV_FILE" ]; then
  install -m 600 -o root -g root "$APP_DIR/deploy/quant4h.env.example" "$ENV_FILE"
  ok "created $ENV_FILE from the template (mode 600) — fill in your keys"
else
  ok "$ENV_FILE already exists, left untouched"
fi

say "checks"
if sudo -u quant "$APP_DIR/.venv/bin/python" -c "import quant,pandas,requests" 2>/dev/null; then
  ok "imports"
else
  bad "imports — the package did not install correctly"
fi

PYV=$("$APP_DIR/.venv/bin/python" -V 2>&1)
ok "$PYV"

IP=$(curl -fsS --max-time 10 https://api.ipify.org || echo "")
if [ -n "$IP" ]; then
  ok "server IP  $IP"
else
  bad "could not determine the server IP"
fi

BN=$(curl -fsS --max-time 10 https://fapi.binance.com/fapi/v1/time || echo "")
if printf '%s' "$BN" | grep -q serverTime; then
  ok "binance reachable  $BN"
else
  bad "binance UNREACHABLE from this region — rebuild the VPS in Tokyo or Singapore"
fi

cat <<NEXT

────────────────────────────────────────────────────────────────
next, by hand:

  1. put $IP in the Binance API key IP whitelist.
     the Futures permission only unlocks once an IP restriction is set.

  2. nano $ENV_FILE
     fill BINANCE_API_KEY and BINANCE_API_SECRET. leave DRY_RUN=1.

  3. dry run once and read the plan:
     systemctl start quant4h.service
     tail -n 40 $LOG_DIR/run.log

  4. only after several clean dry runs, set DRY_RUN=0 and start the timer:
     systemctl enable --now quant4h.timer

the timer is deliberately NOT enabled by this script.
────────────────────────────────────────────────────────────────
NEXT
