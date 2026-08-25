#!/usr/bin/env python3
"""
Exercise the whole real-money runner locally, without API keys and without
touching an exchange.

    python scripts/simulate_live.py

Only two calls in live_real need credentials -- the futures wallet balance and
the open positions. Everything else (klines, exchangeInfo, book) is public, so
stubbing those two is enough to drive the real code path end to end: the same
replay, the same sizing, the same lot quantisation, the same guards.

The strategy replay runs once and is cached, so the scenarios after the first
are instant.

Every scenario is forced to DRY_RUN and writes into a temporary directory, so
this can never place an order or disturb results/live_real.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("BINANCE_API_KEY", "simulated")
os.environ.setdefault("BINANCE_API_SECRET", "simulated")
os.environ["DRY_RUN"] = "1"

import live_real as L  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="quant4h_sim_"))
L.RESULTS, L.STATE = TMP, TMP / "state.json"
L.DRY_RUN = True
L.notify = lambda *a, **k: None


def run(wallet, positions, *, state=None, real_capital=700.0,
        max_order=None, max_gross=None):
    """Run main() once against a fake account, returning (log, plan, state)."""
    L.STATE.unlink(missing_ok=True)
    if state is not None:
        L.STATE.write_text(json.dumps(state), encoding="utf-8")

    # live_real reads these at call time, so the environment is the knob
    for name, val in (("MAX_ORDER_USD", max_order),
                      ("MAX_GROSS_USD", max_gross),
                      ("REAL_CAPITAL", real_capital)):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(val)

    L.Futures.wallet_usdt = lambda self: float(wallet)
    L.Futures.positions = lambda self: dict(positions)

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        L.main()
    text = buf.getvalue()

    runs = sorted(TMP.glob("run_*.json"))
    plan = json.loads(runs[-1].read_text(encoding="utf-8"))["plan"] if runs else []
    for f in runs:
        f.unlink()
    return text, plan, L.STATE.exists()


def orders_of(plan, sym="BTCUSDT"):
    return [p for p in plan if p["symbol"] == sym]


CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def main() -> None:
    print("warming the replay (fetches bars and runs the strategy once) ...")
    frac, bar, detail = L.desired_positions()
    L.desired_positions = lambda: (frac, bar, detail)
    print(f"target at bar {bar}: {frac}")
    print(f"   {detail}\n")

    tgt = frac.get("BTCUSDT", 0.0)
    bid, ask = L.Futures("simulated", "simulated").book("BTCUSDT")
    mid = (bid + ask) / 2
    lot = 0.001 * mid
    print(f"BTCUSDT mid {mid:,.2f}   one lot = {lot:,.2f} USD   "
          f"target fraction {tgt:.4f}\n")

    print("1. wallet below the exchange minimum")
    log, plan, st = run(29.84, {})
    check("no orders placed", len(plan) == 0)
    check("sizing clamped to the wallet", "sizing=29.84" in log)
    check("wallet-vs-REAL_CAPITAL note shown", "NOTE: REAL_CAPITAL" in log)
    check("state.json untouched", not st)

    for w in (300.0, 500.0, 700.0):
        print(f"\n2. wallet {w:.0f} USDT, flat")
        log, plan, st = run(w, {})
        o = orders_of(plan)
        want = tgt * min(700.0, w)
        check(f"one BUY, ~{want:,.0f} USD wanted", len(o) == 1 and o[0]["side"] == "BUY",
              f"got {o[0]['notional']:,.2f} ({(o[0]['notional'] - want) / want:+.1%})" if o else "none")
        check("within one lot of the target", o and abs(o[0]["notional"] - want) <= lot)
        check("state.json untouched", not st)

    print("\n3. already holding the target -- must not churn")
    qty = round(tgt * 700.0 / mid, 3)
    log, plan, st = run(700.0, {"BTCUSDT": qty})
    check("no orders", len(plan) == 0, f"holding {qty} BTC")

    print("\n4. holding the opposite side -- must reverse")
    log, plan, st = run(700.0, {"BTCUSDT": -qty})
    o = orders_of(plan)
    check("one BUY", len(o) == 1 and o[0]["side"] == "BUY")
    check("roughly double the flat-start order", o and o[0]["notional"] > tgt * 700 * 1.5,
          f"{o[0]['notional']:,.2f} USD" if o else "")

    print("\n5. the caps scale with capital by default")
    for w in (300.0, 700.0):
        log, plan, st = run(w, {})
        cap = min(700.0, w)
        check(f"wallet {w:.0f}: order cap is 2x capital",
              f"order {2 * cap:.2f} USD" in log, f"expected {2 * cap:.2f}")
        check(f"wallet {w:.0f}: no cap warning raised",
              "WARNING: the order cap" not in log)

    print("\n6. an absolute MAX_ORDER_USD below capital is called out")
    log, plan, st = run(700.0, {}, max_order=300.0)
    check("warns that entries will be refused", "WARNING: the order cap" in log)
    check("and does refuse", len(plan) == 0)

    print("\n7. MAX_ORDER_USD below a single order")
    log, plan, st = run(700.0, {}, max_order=50.0)
    check("order refused", len(plan) == 0)
    check("refusal logged", "REFUSED" in log)

    print("\n8. MAX_GROSS_USD below the book")
    log, plan, st = run(700.0, {}, max_gross=10.0)
    check("nothing planned", len(plan) == 0)
    check("gross cap logged", "gross cap" in log)

    print("\n9. wallet below the kill floor, with a baseline on record")
    log, plan, st = run(300.0, {}, state={"baseline_equity": 700.0})
    check("kill reported", "KILL SWITCH would trip" in log)
    check("NOT latched in a dry run",
          "killed_at" not in L.STATE.read_text(encoding="utf-8"))
    check("no orders", len(plan) == 0)

    print("\n10. wallet above REAL_CAPITAL -- the ceiling holds")
    log, plan, st = run(2000.0, {})
    check("sizing capped at 700", "sizing=700.00" in log)
    o = orders_of(plan)
    check("order sized off 700, not 2000", o and o[0]["notional"] < tgt * 1000,
          f"{o[0]['notional']:,.2f} USD" if o else "")

    print("\n11. REAL_CAPITAL unset -- sizes off the wallet")
    log, plan, st = run(450.0, {}, real_capital=None)
    check("sizing follows the wallet", "sizing=450.00" in log)

    bad = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{'=' * 62}\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    for n in bad:
        print(f"  FAILED: {n}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
