#!/usr/bin/env bash
# Turn on real trading, checking each precondition instead of trusting the eye.
#
#   bash /opt/quant-4h-dual/deploy/golive.sh
#
# It shows what the strategy would do right now, asks for a typed confirmation,
# then flips DRY_RUN, runs once, and verifies the result before enabling the
# timer. If the baseline it records does not match the wallet, it puts DRY_RUN
# back and stops without enabling anything: that number governs the kill switch
# for the life of the account, and a wrong one disables the limit silently.

set -uo pipefail

APP_DIR=${APP_DIR:-/opt/quant-4h-dual}
ENV_FILE=${ENV_FILE:-/etc/quant4h.env}
STATE=$APP_DIR/results/live_real/state.json
PY=$APP_DIR/.venv/bin/python

say()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ok()   { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; }
warn() { printf '   \033[1;33mwarn\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }
[ -f "$ENV_FILE" ] || { bad "$ENV_FILE missing"; exit 1; }

say "preconditions"
set -a; . "$ENV_FILE"; set +a

[ "${DRY_RUN:-1}" = "1" ] || { bad "DRY_RUN is already 0; this script is for the first switch"; exit 1; }
ok "DRY_RUN=1, nothing is trading yet"

if systemctl is-enabled --quiet quant4h.timer 2>/dev/null; then
  bad "the timer is already enabled"; exit 1
fi
ok "timer not enabled"

if [ -f "$STATE" ] && grep -q killed_at "$STATE"; then
  bad "the kill switch is latched in $STATE. Clear killed_at deliberately first."
  exit 1
fi

if [ -f "$STATE" ] && grep -q baseline_equity "$STATE"; then
  warn "a baseline is already on record; it will be kept, not re-read from the wallet"
fi

WALLET=$("$PY" - <<'PY'
import hashlib, hmac, json, os, time, urllib.parse, urllib.request
k, s = os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"]
qs = urllib.parse.urlencode({"timestamp": int(time.time() * 1000), "recvWindow": 10000})
sig = hmac.new(s.encode(), qs.encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request(
    f"https://fapi.binance.com/fapi/v2/account?{qs}&signature={sig}",
    headers={"X-MBX-APIKEY": k})
a = json.load(urllib.request.urlopen(req, timeout=20))
print(next((x["walletBalance"] for x in a["assets"] if x["asset"] == "USDT"), "0"))
PY
) || { bad "could not read the wallet"; exit 1; }
ok "USDT wallet $WALLET"

say "what it would do right now"
systemctl start quant4h.service
tail -n 14 /var/log/quant4h/run.log | sed 's/^/   /'

cat <<CONFIRM

────────────────────────────────────────────────────────────────
This switches the account to REAL trading.

  wallet          $WALLET USDT
  kill switch     halts permanently at ${KILL_DRAWDOWN:-0.35} below the baseline
  schedule        every 4h at :02 UTC once the timer is enabled

Orders will be placed automatically, without asking again.
To stop later:  systemctl disable --now quant4h.timer
                (open positions are NOT closed; close them on Binance)
────────────────────────────────────────────────────────────────
CONFIRM

printf 'Type LIVE to proceed, anything else to abort: '
read -r ANSWER
[ "$ANSWER" = "LIVE" ] || { echo "aborted, nothing changed"; exit 1; }

say "switching to live"
cp -p "$ENV_FILE" "$ENV_FILE.bak"
sed -i 's/^DRY_RUN=1/DRY_RUN=0/' "$ENV_FILE"
grep -q '^DRY_RUN=0' "$ENV_FILE" || { bad "DRY_RUN was not changed"; exit 1; }
ok "DRY_RUN=0"

say "first live run"
# Type=oneshot blocks until the run finishes and propagates its exit code --
# discarding it here would let verification pass on a stale state.json from an
# earlier attempt while the run itself had died.
if ! systemctl start quant4h.service; then
  cp -p "$ENV_FILE.bak" "$ENV_FILE"
  bad "the first live run FAILED -- see /var/log/quant4h/run.log"
  echo "   DRY_RUN restored to 1; the timer was NOT enabled."
  exit 1
fi
tail -n 20 /var/log/quant4h/run.log | sed 's/^/   /'

say "verifying what it recorded"
revert() {
  cp -p "$ENV_FILE.bak" "$ENV_FILE"
  bad "$1"
  echo "   DRY_RUN restored to 1; the timer was NOT enabled."
  exit 1
}

[ -f "$STATE" ] || revert "no state.json was written; the run did not complete"

BASE=$("$PY" -c "import json;print(json.load(open('$STATE')).get('baseline_equity',0))")
grep -q killed_at "$STATE" && revert "the kill switch tripped on the first run"

# The baseline anchors the kill switch permanently. If it does not match the
# wallet, the floor is in the wrong place and the 35% limit means nothing.
OKBASE=$(awk -v b="$BASE" -v w="$WALLET" \
  'BEGIN{d=(b>w?b-w:w-b); print (w>0 && d/w<0.02)?1:0}')
[ "$OKBASE" = "1" ] || revert "baseline $BASE does not match the wallet $WALLET"
ok "baseline $BASE matches the wallet"
ok "floor $(awk -v b="$BASE" -v k="${KILL_DRAWDOWN:-0.35}" 'BEGIN{printf "%.2f", b*(1-k)}') USDT"

say "enabling the timer"
systemctl enable --now quant4h.timer >/dev/null 2>&1
systemctl is-enabled --quiet quant4h.timer && ok "enabled" || { bad "could not enable"; exit 1; }
systemctl list-timers quant4h.timer --no-pager | sed 's/^/   /'

cat <<'DONE'

   Live. It runs on its own from here.

   watch     tail -f /var/log/quant4h/run.log
   stop      systemctl disable --now quant4h.timer
   full stop systemctl disable --now quant4h.timer; sed -i 's/^DRY_RUN=0/DRY_RUN=1/' /etc/quant4h.env

   Stopping does not close open positions. Close those on Binance.
DONE
