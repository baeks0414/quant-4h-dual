#!/usr/bin/env bash
# Find out why the Telegram bot is not answering.
#
#   bash /opt/quant-4h-dual/deploy/botcheck.sh
#
# Checks each link in the chain in order and stops at the first break, so the
# answer is the last line rather than something to infer from a wall of output.
# Silence from a bot has several unrelated causes -- never installed, no token,
# a crashing poller, the wrong chat id -- and they look identical from the phone.

set -uo pipefail

APP_DIR=${APP_DIR:-/opt/quant-4h-dual}
ENV_FILE=${ENV_FILE:-/etc/quant4h.env}
PY=$APP_DIR/.venv/bin/python

say()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '   \033[1;33mwarn\033[0m %s\n' "$*"; }
fix()  { printf '\n\033[1;36m   fix:\033[0m %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }

say "credentials"
[ -f "$ENV_FILE" ] || fix "no $ENV_FILE -- run deploy/setup.sh"
set -a; . "$ENV_FILE"; set +a
if [ -z "${TELEGRAM_TOKEN:-}" ]; then
  bad "TELEGRAM_TOKEN is not set"
  fix "bash $APP_DIR/deploy/telegram.sh"
fi
ok "TELEGRAM_TOKEN present (${#TELEGRAM_TOKEN} chars)"
[ -n "${TELEGRAM_CHAT_ID:-}" ] || fix "TELEGRAM_CHAT_ID is empty -- bash $APP_DIR/deploy/telegram.sh"
ok "TELEGRAM_CHAT_ID $TELEGRAM_CHAT_ID"

say "the bot is installed"
if [ ! -f /etc/systemd/system/quant4h-bot.service ]; then
  bad "quant4h-bot.service is not installed"
  fix "bash $APP_DIR/deploy/telegram.sh"
fi
ok "service installed"
if systemctl is-enabled --quiet quant4h-bot.timer 2>/dev/null; then
  ok "timer enabled"
else
  bad "quant4h-bot.timer is not enabled -- nothing is polling"
  fix "systemctl enable --now quant4h-bot.timer"
fi
systemctl list-timers quant4h-bot.timer --no-pager | sed -n '2p' | sed 's/^/   /'

say "the token reaches Telegram"
WHO=$(TG="$TELEGRAM_TOKEN" "$PY" - <<'PY'
import json, os, urllib.request
try:
    d = json.load(urllib.request.urlopen(
        f"https://api.telegram.org/bot{os.environ['TG']}/getMe", timeout=20))
    print(d["result"]["username"] if d.get("ok") else f"ERR {d}")
except Exception as e:
    print(f"ERR {e}")
PY
)
case "$WHO" in ERR*) bad "Telegram rejected the token: ${WHO#ERR }"
                    fix "bash $APP_DIR/deploy/telegram.sh";; esac
ok "bot is @$WHO"

say "charting"
if sudo -u quant MPLCONFIGDIR=/var/log/quant4h/.mpl "$PY" -c \
     "import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot" 2>/dev/null; then
  ok "matplotlib imports as quant"
else
  warn "matplotlib will not import -- /chart replies with an install hint,"
  warn "  but /status and /log are unaffected"
  warn "  fix: install -d -o quant -g quant /var/log/quant4h/.mpl"
  warn "       sudo -u quant $APP_DIR/.venv/bin/pip install -e '$APP_DIR[bot]'"
fi

say "a poll, run by hand"
# The important one: this is the exact command the timer runs, so whatever it
# prints here is what has been happening every minute in silence.
OUT=$(systemd-run --quiet --pipe --wait --uid=quant \
        --property=WorkingDirectory="$APP_DIR" \
        --property=EnvironmentFile="$ENV_FILE" \
        --property=Environment=MPLCONFIGDIR=/var/log/quant4h/.mpl \
        "$PY" scripts/status_bot.py 2>&1)
RC=$?
printf '%s\n' "${OUT:-(no output)}" | sed 's/^/   /'
[ $RC -eq 0 ] || fix "the poller exits $RC -- the traceback above is the cause"
ok "the poller ran cleanly"

say "result"
cat <<'DONE'
   Everything in the chain is working. If messages still go unanswered:

     - send a NEW message now; the poller only reads messages that arrived
       after the last offset it recorded, so anything sent while it was
       broken has already been marked as seen
     - check you are messaging the bot named above, not another one
     - a message from a different Telegram account is ignored on purpose

   Then: tail -f /var/log/quant4h/bot.log  and send /status.
DONE
