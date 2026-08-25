#!/usr/bin/env bash
# Pre-flight check before the first dry run.
#
#   bash /opt/quant-4h-dual/deploy/check.sh
#
# Verifies the env file and the API key WITHOUT ever printing a secret. Console
# paste silently drops characters, so a key that looks right can still be one
# character short; the length and charset checks below catch that before the
# signature error does.

set -uo pipefail

ENV_FILE=${ENV_FILE:-/etc/quant4h.env}
APP_DIR=${APP_DIR:-/opt/quant-4h-dual}

ok()   { printf '   \033[1;32mok\033[0m   %s\n' "$*"; }
bad()  { printf '   \033[1;31mFAIL\033[0m %s\n' "$*"; FAILED=1; }
warn() { printf '   \033[1;33mwarn\033[0m %s\n' "$*"; }
say()  { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
FAILED=0

[ "$(id -u)" -eq 0 ] || { bad "run as root"; exit 1; }
[ -f "$ENV_FILE" ] || { bad "$ENV_FILE missing — run setup.sh first"; exit 1; }

say "env file"
PERM=$(stat -c '%a' "$ENV_FILE")
[ "$PERM" = "600" ] && ok "permissions $PERM" || warn "permissions $PERM (600 preferred)"

# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

check_secret() {
  local name=$1 val=${2:-}
  if [ -z "$val" ]; then bad "$name is empty"; return; fi
  local len=${#val}
  local junk; junk=$(printf '%s' "$val" | tr -d 'A-Za-z0-9' | wc -c)
  local msg="$name  length=$len"
  if [ "$junk" -ne 0 ]; then
    bad "$msg  contains $junk non-alphanumeric character(s) — likely a paste artefact"
  elif [ "$len" -ne 64 ]; then
    bad "$msg  expected 64 — a character was dropped or added"
  else
    ok "$msg  charset clean"
  fi
}
check_secret BINANCE_API_KEY "${BINANCE_API_KEY:-}"
check_secret BINANCE_API_SECRET "${BINANCE_API_SECRET:-}"

say "settings"
printf '   DRY_RUN=%s  REAL_CAPITAL=%s  KILL_DRAWDOWN=%s\n' \
  "${DRY_RUN:-unset}" "${REAL_CAPITAL:-unset}" "${KILL_DRAWDOWN:-unset}"
printf '   MAX_ORDER_USD=%s  MAX_GROSS_USD=%s  LIMIT_WAIT_SEC=%s\n' \
  "${MAX_ORDER_USD:-scales with capital}" "${MAX_GROSS_USD:-scales with capital}" \
  "${LIMIT_WAIT_SEC:-unset}"

# A fixed order cap below the capital refuses every entry. It reads as a prudent
# setting and behaves as an off switch, so it is worth failing on rather than
# warning about: nothing would trade and the log would still look healthy.
CAP=${REAL_CAPITAL:-0}
if [ -n "${MAX_ORDER_USD:-}" ] && [ "$CAP" != "0" ] \
   && [ "$(awk -v a="$MAX_ORDER_USD" -v b="$CAP" 'BEGIN{print (a<b)?1:0}')" = "1" ]; then
  bad "MAX_ORDER_USD=$MAX_ORDER_USD is below REAL_CAPITAL=$CAP"
  printf '        this strategy takes positions near 100%% of capital, so every\n'
  printf '        entry would be refused. Delete the MAX_ORDER_USD line from\n'
  printf '        %s and let the cap scale with capital.\n' "$ENV_FILE"
fi
[ "${DRY_RUN:-1}" = "1" ] && ok "DRY_RUN is on — no orders will be sent" \
                          || warn "DRY_RUN is OFF — this configuration TRADES REAL MONEY"

if [ "$FAILED" -eq 1 ]; then
  say "line map of $ENV_FILE (values hidden)"
  awk '{
    if ($0 ~ /^[[:space:]]*#/ || $0 !~ /=/) next
    n = index($0, "=")
    printf "   line %-3d [%s] value length %d\n", NR, substr($0, 1, n-1), length($0) - n
  }' "$ENV_FILE"
  cat <<'HINT'

   a variable that reads as EMPTY is almost always one of:
     - the paste silently dropped the whole value (common over VNC)
     - the name is misspelled, or has a space before the "="
     - the line is still commented out with a leading #
     - the name appears TWICE and the later, empty one wins
     - the value landed on the following line instead of after the "="

   the bracketed name above is the literal text before the "=", so a trailing
   space or a typo is visible there.
HINT
fi

[ "$FAILED" -eq 1 ] && { printf '\n\033[1;31mfix the failures above before continuing\033[0m\n'; exit 1; }

say "binance authentication"
"$APP_DIR/.venv/bin/python" - <<'PY'
import hashlib, hmac, os, sys, time, urllib.parse, json, urllib.request

KEY = os.environ["BINANCE_API_KEY"]
SEC = os.environ["BINANCE_API_SECRET"]
FAPI = "https://fapi.binance.com"

def signed(path, params=None):
    p = dict(params or {})
    p["timestamp"] = int(time.time() * 1000)
    p["recvWindow"] = 10000
    qs = urllib.parse.urlencode(p)
    sig = hmac.new(SEC.encode(), qs.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(f"{FAPI}{path}?{qs}&signature={sig}",
                                 headers={"X-MBX-APIKEY": KEY})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def fail(msg):
    print(f"   \033[1;31mFAIL\033[0m {msg}")
    sys.exit(1)

try:
    acc = signed("/fapi/v2/account")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"   \033[1;31mFAIL\033[0m HTTP {e.code}: {body}")
    if "-2015" in body:
        print("        -2015 means one of: wrong key, IP not whitelisted, or")
        print("        Futures permission not enabled on the key.")
    elif "-1022" in body:
        print("        -1022 is a bad signature: the SECRET is wrong or truncated.")
    elif "-1021" in body:
        print("        -1021 is clock skew. Run: timedatectl set-ntp true")
    sys.exit(1)
except Exception as e:
    fail(f"{type(e).__name__}: {e}")

print("   \033[1;32mok\033[0m   authenticated, futures permission active")

bal = next((a for a in acc.get("assets", []) if a.get("asset") == "USDT"), {})
wallet = float(bal.get("walletBalance") or 0)
avail = float(bal.get("availableBalance") or 0)
print(f"   \033[1;32mok\033[0m   USDT wallet {wallet:,.2f}   available {avail:,.2f}")

cap = float(os.environ.get("REAL_CAPITAL") or wallet)
if wallet <= 0:
    print("   \033[1;33mwarn\033[0m wallet is empty — transfer USDT to the USDT-M FUTURES wallet")
elif wallet < cap * 0.9:
    print(f"   \033[1;33mwarn\033[0m REAL_CAPITAL={cap:,.0f} exceeds the wallet {wallet:,.2f}")

pos = [p for p in signed("/fapi/v2/positionRisk")
       if abs(float(p.get("positionAmt") or 0)) > 0]
if pos:
    print(f"   \033[1;33mwarn\033[0m {len(pos)} position(s) already open:")
    for p in pos:
        print(f"        {p['symbol']}  {float(p['positionAmt']):+.6f}  "
              f"entry {p.get('entryPrice')}  uPnL {p.get('unRealizedProfit')}")
    print("        the runner will reconcile TOWARD its target, not close these.")
else:
    print("   \033[1;32mok\033[0m   no open futures positions")

if acc.get("canTrade") is False:
    print("   \033[1;31mFAIL\033[0m account canTrade=false")
    sys.exit(1)
PY
RC=$?

say "result"
if [ $RC -eq 0 ]; then
  cat <<'NEXT'
   ready. run the dry run:

     systemctl start quant4h.service; sleep 75; tail -n 40 /var/log/quant4h/run.log

   it must print "mode=DRY RUN" and end with "DRY RUN - nothing sent".
NEXT
else
  echo "   authentication failed — see the message above"
  exit 1
fi
