#!/usr/bin/env python3
"""
Exercise the bot's minutely kill-switch guard against a programmable account.

    python scripts/test_guard.py

The guard is the one path in the bot that can send orders, so its decision
table gets the same treatment as execute(): every branch pinned by a check.
Telegram, Binance and systemd are all stubbed; nothing leaves the process.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
os.environ.update(TELEGRAM_TOKEN="1:x", TELEGRAM_CHAT_ID="7",
                  KILL_DRAWDOWN="0.35",
                  BINANCE_API_KEY="k" * 64, BINANCE_API_SECRET="s" * 64)
import status_bot as B  # noqa: E402

tmp = pathlib.Path(tempfile.mkdtemp(prefix="quant4h_guard_"))
B.RESULTS, B.STATE = tmp, tmp / "state.json"

sent, orders, sysd = [], [], {"active": "inactive"}
B.send = lambda c, t: sent.append(t)


def fake_binance(method, path, params=None):
    if "account" in path:
        return {"assets": [{"asset": "USDT",
                            "marginBalance": str(fake_binance.eq)}]}
    if "positionRisk" in path:
        return [{"symbol": "ETHUSDT", "positionAmt": "0.037"},
                {"symbol": "BTCUSDT", "positionAmt": "-0.002"},
                {"symbol": "XRPUSDT", "positionAmt": "0"}]
    if "order" in path:
        orders.append(params)
        return {"ok": 1}
    raise AssertionError(path)


B._binance = fake_binance


def fake_run(cmd, **kw):
    if "disable" in cmd:
        sysd["disabled"] = True
    return types.SimpleNamespace(
        stdout=sysd["active"] if "is-active" in cmd else "")


B.subprocess.run = fake_run


def case(state, eq, active="inactive", dry=False):
    B.STATE.write_text(json.dumps(state))
    fake_binance.eq = eq
    sysd.update(active=active)
    sysd.pop("disabled", None)
    sent.clear()
    orders.clear()
    B.GUARD_DRY = dry
    B.guard_equity()
    st = json.loads(B.STATE.read_text())
    return dict(latched="killed_at" in st, orders=len(orders),
                alerts=len(sent), timer_off=sysd.get("disabled", False))


BASE = {"baseline_equity": 259.78}
NOOP = dict(latched=False, orders=0, alerts=0, timer_off=False)
CASES = [
    ("no baseline recorded -> not armed", case({}, 100), NOOP),
    ("already latched -> stays latched, acts no further",
     case({**BASE, "killed_at": "x"}, 100),
     {**NOOP, "latched": True}),
    ("equity above the floor -> nothing", case(BASE, 200), NOOP),
    ("breach while a trader run is active -> defer to it",
     case(BASE, 150, active="active"), NOOP),
    ("breach under GUARD_DRY -> report only",
     case(BASE, 150, dry=True), NOOP),
    ("breach -> latch, flatten, stop the schedule, alert",
     case(BASE, 150),
     dict(latched=True, orders=2, alerts=1, timer_off=True)),
]

ok = True
for name, got, want in CASES:
    good = got == want
    ok &= good
    print(("  PASS  " if good else "  FAIL  ") + f"{name:<52} {got}")

flat = {(o["symbol"], o["side"], o["quantity"], o["reduceOnly"])
        for o in orders}
want_flat = {("ETHUSDT", "SELL", "0.037", "true"),
             ("BTCUSDT", "BUY", "0.002", "true")}
good = flat == want_flat
ok &= good
print(("  PASS  " if good else "  FAIL  ")
      + f"{'flatten orders are reduce-only, right side, right size':<52} "
      + f"{sorted(flat)}")

print(f"\n{7 if ok else 'SOME'}/7 checks passed" if ok else "\nFAILURES above")
sys.exit(0 if ok else 1)
