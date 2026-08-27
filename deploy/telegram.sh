#!/usr/bin/env bash
# Set up Telegram alerts, and prove a message actually arrives.
#
#   bash /opt/quant-4h-dual/deploy/telegram.sh
#
# Writing a token into a file only proves a string was stored. What matters is
# that a message reaches your phone, because the one time these alerts count is
# the time nobody is reading the log: the kill switch tripping, or an order
# failing. So this verifies the token with the API, finds the chat id for you,
# sends a test message, and only saves once that has gone through.

set -uo pipefail

ENV_FILE=${ENV_FILE:-/etc/quant4h.env}
PY=${PY:-/opt/quant-4h-dual/.venv/bin/python}

say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()  { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad() { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }
warn(){ printf '   \033[1;33mwarn\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }
[ -f "$ENV_FILE" ] || { bad "$ENV_FILE missing"; exit 1; }
[ -x "$PY" ] || { bad "$PY missing"; exit 1; }

cat <<'INTRO'

Before running this, create the bot in Telegram:

  1. open a chat with @BotFather
  2. send  /newbot  and follow the prompts
  3. it replies with a token like  1234567890:AAH...
  4. open a chat with YOUR new bot and send it  /start
     (Telegram will not let a bot message you until you do)

INTRO

say "existing credentials"
KEEP=0
# Re-running this to install the bot should not demand the token again. If what
# is already on file works, offer to keep it and skip straight to the install.
if [ -n "${TELEGRAM_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  HAVE=$(TG="$TELEGRAM_TOKEN" "$PY" - <<'PY'
import json, os, urllib.request
try:
    d = json.load(urllib.request.urlopen(
        f"https://api.telegram.org/bot{os.environ['TG']}/getMe", timeout=20))
    print(d["result"]["username"] if d.get("ok") else "ERR")
except Exception:
    print("ERR")
PY
)
  if [ "$HAVE" != "ERR" ]; then
    ok "already set up: @$HAVE, chat $TELEGRAM_CHAT_ID"
    printf '   keep these and just install the bot? [Y/n]: '
    read -r A
    case "$A" in n|N) ;; *) KEEP=1;; esac
  else
    warn "the stored token no longer works; asking for a new one"
  fi
fi

if [ "$KEEP" -eq 0 ]; then
say "token"
printf '   paste the BotFather token (nothing will be shown): '
IFS= read -rs TOKEN; echo
TOKEN=$(printf '%s' "$TOKEN" | tr -d '\r\n\t ')
if ! printf '%s' "$TOKEN" | grep -qE '^[0-9]{6,}:[A-Za-z0-9_-]{30,}$'; then
  bad "that does not look like a bot token (digits, a colon, then ~35 characters)"
  exit 1
fi

NAME=$(TG="$TOKEN" "$PY" - <<'PY'
import json, os, sys, urllib.request
try:
    d = json.load(urllib.request.urlopen(
        f"https://api.telegram.org/bot{os.environ['TG']}/getMe", timeout=20))
except Exception as e:
    print(f"ERR {e}"); sys.exit(0)
print(d["result"]["username"] if d.get("ok") else f"ERR {d}")
PY
)
case "$NAME" in
  ERR*) bad "Telegram rejected the token: ${NAME#ERR }"; exit 1;;
esac
ok "token works, bot is @$NAME"

say "chat"
CHATS=$(TG="$TOKEN" "$PY" - <<'PY'
import json, os, urllib.request
d = json.load(urllib.request.urlopen(
    f"https://api.telegram.org/bot{os.environ['TG']}/getUpdates", timeout=20))
seen = {}
for u in d.get("result", []):
    c = (u.get("message") or u.get("channel_post") or {}).get("chat")
    if c:
        seen[c["id"]] = c.get("title") or " ".join(
            filter(None, [c.get("first_name"), c.get("last_name"),
                          f"@{c['username']}" if c.get("username") else None]))
for k, v in seen.items():
    print(f"{k}\t{v}")
PY
)
if [ -z "$CHATS" ]; then
  bad "no chats found -- open a chat with @$NAME and send it /start, then rerun"
  exit 1
fi
printf '%s\n' "$CHATS" | sed 's/^/   /'
COUNT=$(printf '%s\n' "$CHATS" | wc -l)
if [ "$COUNT" -eq 1 ]; then
  CHAT_ID=$(printf '%s' "$CHATS" | cut -f1)
  ok "using chat $CHAT_ID"
else
  printf '   more than one chat; type the id to use: '
  read -r CHAT_ID
fi
printf '%s' "$CHAT_ID" | grep -qE '^-?[0-9]+$' || { bad "not a chat id"; exit 1; }

say "test message"
RES=$(TG="$TOKEN" CID="$CHAT_ID" "$PY" - <<'PY'
import json, os, urllib.parse, urllib.request
body = urllib.parse.urlencode({
    "chat_id": os.environ["CID"],
    "text": "quant-4h-dual: alerts are working. "
            "You will get a message on every run, and when the kill switch trips.",
}).encode()
try:
    d = json.load(urllib.request.urlopen(
        f"https://api.telegram.org/bot{os.environ['TG']}/sendMessage",
        data=body, timeout=20))
    print("SENT" if d.get("ok") else f"ERR {d}")
except Exception as e:
    print(f"ERR {e}")
PY
)
case "$RES" in
  SENT) ok "sent -- check your phone before continuing";;
  *)    bad "could not send: ${RES#ERR }"; exit 1;;
esac

printf '\n   did the message arrive? [y/N]: '
read -r GOT
case "$GOT" in
  y|Y|yes|YES) ;;
  *) bad "not saved; nothing changed"; exit 1;;
esac

say "saving"
cp -p "$ENV_FILE" "$ENV_FILE.bak"
KB=$(grep -cE '^BINANCE_API_(KEY|SECRET)=.{20,}' "$ENV_FILE")
grep -vE '^TELEGRAM_(TOKEN|CHAT_ID)=' "$ENV_FILE.bak" > "$ENV_FILE"
printf 'TELEGRAM_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT_ID" >> "$ENV_FILE"
KA=$(grep -cE '^BINANCE_API_(KEY|SECRET)=.{20,}' "$ENV_FILE")
if [ "$KB" != "$KA" ]; then
  cp -p "$ENV_FILE.bak" "$ENV_FILE"
  bad "editing $ENV_FILE lost a credential line; restored from .bak"
  exit 1
fi
chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"
ok "written to $ENV_FILE (previous kept as $ENV_FILE.bak)"
fi

say "two-way bot"
APP_DIR=${APP_DIR:-/opt/quant-4h-dual}
SYSCTL=$(command -v systemctl)

# The bot may disable the schedule and nothing else. That is a safe thing to
# reach from a chat because it can only reduce activity -- it cannot open a
# position, resize one, or move funds. The rule is written narrowly for exactly
# that command, and validated before it is installed, since a malformed sudoers
# file locks sudo for everyone.
TMP=$(mktemp)
cat > "$TMP" <<EOF
quant ALL=(root) NOPASSWD: $SYSCTL disable --now quant4h.timer
EOF
if visudo -c -q -f "$TMP" 2>/dev/null; then
  install -m 440 -o root -g root "$TMP" /etc/sudoers.d/quant4h-bot
  ok "the bot may stop the schedule, and nothing else"
else
  warn "could not install the sudoers rule; /stop will not work from Telegram"
fi
rm -f "$TMP"

sudo -u quant "$APP_DIR/.venv/bin/pip" install -q -e "$APP_DIR[bot]" \
  && ok "charting installed" || warn "matplotlib missing; /chart will say so"

install -d -o quant -g quant -m 755 /var/log/quant4h/.mpl
install -m 644 "$APP_DIR/deploy/quant4h-bot.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/quant4h-bot.timer"   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quant4h-bot.timer >/dev/null 2>&1
systemctl is-enabled --quiet quant4h-bot.timer   && ok "polling every minute" || bad "could not enable the bot timer"

cat <<'NEXT'

   Message the bot and it will answer within a minute:

     /status       wallet, distance to the kill switch, positions
     /positions    open positions in detail
     /log          the tail of the runner log
     /stop CONFIRM stop placing orders (positions are NOT closed)

   It also messages you on every run -- six a day. Say so if that is too much
   and it can be narrowed to orders and faults only.
NEXT
