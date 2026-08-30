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

# The scenarios assert on sizes, so the target they size has to be fixed. Using
# whatever the strategy wants right now made the suite fail whenever the market
# moved -- seven checks broke the day the target fell from 0.82 to 0.17, none of
# them because of the code. The live target is still printed, and still gets a
# scenario of its own.
PINNED = 0.82
BAR = DETAIL = None


def set_target(x):
    L.desired_positions = lambda: ({"BTCUSDT": x} if x else {}, BAR, DETAIL)


def run(wallet, positions, *, state=None, real_capital=700.0,
        max_order=None, max_gross=None, leverage=20.0, available=None,
        other_assets=None, include_collateral=False, coin_px=None,
        hedge_mode=False, target=None, transfers=0.0):
    """Run main() once against a fake account, returning (log, plan, state)."""
    L.STATE.unlink(missing_ok=True)
    if state is not None:
        L.STATE.write_text(json.dumps(state), encoding="utf-8")

    # live_real reads these at call time, so the environment is the knob
    if include_collateral:
        os.environ["INCLUDE_COLLATERAL"] = "1"
    else:
        os.environ.pop("INCLUDE_COLLATERAL", None)
    for name, val in (("MAX_ORDER_USD", max_order),
                      ("MAX_GROSS_USD", max_gross),
                      ("REAL_CAPITAL", real_capital)):
        if val is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = str(val)

    set_target(PINNED if target is None else target)
    L.Futures.wallet_usdt = lambda self: float(wallet)
    L.Futures.available_usdt = lambda self: float(
        wallet if available is None else available)
    L.Futures.positions = lambda self: dict(positions)
    L.Futures.other_assets = lambda self: dict(other_assets or {})
    L.Futures.transfers_since = lambda self, ms: float(transfers)
    L.Futures._signed = lambda self, m, path, params=None: (
        {"dualSidePosition": bool(hedge_mode)}
        if "positionSide" in path else {})
    L.Futures.total_usd = lambda self: float(wallet) + sum(
        q * (coin_px or 0.0) for q in (other_assets or {}).values())
    L.Futures.risk = lambda self: {
        s: {"leverage": float(leverage), "margin": "cross"}
        for s in ("BTCUSDT", "ETHUSDT")}

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
    global BAR, DETAIL
    print("warming the replay (fetches bars and runs the strategy once) ...")
    live, BAR, DETAIL = L.desired_positions()
    print(f"live target at bar {BAR}: {live}")
    print(f"   {DETAIL}")
    print(f"scenarios are pinned to BTCUSDT {PINNED} so they do not depend "
          f"on the market\n")

    tgt = PINNED
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

    print("\n9. leverage too low to post margin for the plan")
    log, plan, st = run(700.0, {}, leverage=1.0, available=100.0)
    check("the plan is still shown", len(plan) == 1)
    check("a live run would refuse", "a live run would refuse" in log)
    check("margin requirement reported", "margin required" in log)

    print("\n9b. ample leverage -- no objection")
    log, plan, st = run(700.0, {}, leverage=20.0)
    check("no margin objection", "would refuse" not in log)
    check("leverage reported", "20x" in log)

    print("\n9c. a coin parked in the futures wallet is called out")
    log, plan, st = run(700.0, {}, other_assets={"BTC": 0.0029})
    check("non-USDT collateral warned about", "non-USDT assets" in log)
    check("the coin is named", "0.0029 BTC" in log)
    check("orders still planned", len(plan) == 1)

    print("\n9d. INCLUDE_COLLATERAL folds the coin into capital and position")
    coin = 0.0029
    off_log, off_plan, _ = run(159.78, {}, other_assets={"BTC": coin},
                               real_capital=None, coin_px=mid)
    on_log, on_plan, _ = run(159.78, {}, other_assets={"BTC": coin},
                             real_capital=None, coin_px=mid,
                             include_collateral=True)
    total = 159.78 + coin * mid
    check("off: sizes against USDT only", "sizing=159.78" in off_log)
    check("off: warns about the coin", "non-USDT assets" in off_log)
    check("on: sizes against the whole wallet", f"sizing={total:.2f}" in on_log)
    check("on: counts the coin as an open position",
          "counting 0.0029 BTC of collateral" in on_log)
    off_n = off_plan[0]["notional"] if off_plan else 0.0
    on_n = on_plan[0]["notional"] if on_plan else 0.0
    check("on: buys only the difference", 0 < on_n < off_n,
          f"off {off_n:,.2f} -> on {on_n:,.2f} USD")
    want_total = tgt * total
    check("on: total exposure lands on target",
          abs(coin * mid + on_n - want_total) <= lot,
          f"coin {coin * mid:,.2f} + leg {on_n:,.2f} vs target {want_total:,.2f}")

    print("\n9e. collateral above target -- the leg shorts against it")
    big = 0.020
    log, plan, st = run(159.78, {}, other_assets={"BTC": big}, real_capital=None,
                        coin_px=mid, include_collateral=True)
    o = orders_of(plan)
    got = o[0]["side"] if o else "no order"
    check("sells rather than buys", len(o) == 1 and got == "SELL", got)

    print("\n9f. Hedge mode -- every order would be rejected")
    log, plan, st = run(700.0, {}, hedge_mode=True)
    check("refuses outright", "Hedge mode" in log)
    check("nothing planned", len(plan) == 0)

    print("\n9g. a deposit moves the baseline only when the ledger confirms it")
    log, plan, st = run(700.0, {}, transfers=540.0,
                        state={"baseline_equity": 160.0, "last_wallet": 160.0,
                               "last_run": "20260827T000000"})
    check("ledger transfer recognised", "ledger shows +540.00" in log)
    check("baseline follows the deposit", "baseline=700.00" in log)
    check("floor recomputed off the new baseline", "floor=455.00" in log)

    print("\n9h. ordinary P&L must NOT move the baseline")
    log, plan, st = run(690.0, {}, transfers=0.0,
                        state={"baseline_equity": 700.0, "last_wallet": 700.0,
                               "last_run": "20260827T000000"})
    check("left alone", "ledger shows" not in log)
    check("baseline unchanged", "baseline=700.00" in log)

    print("\n9h2. a crash bar is NOT a withdrawal -- the floor must hold")
    log, plan, st = run(500.0, {}, transfers=0.0,
                        state={"baseline_equity": 700.0, "last_wallet": 700.0,
                               "last_run": "20260827T000000"})
    check("recognised as P&L, not a transfer", "the baseline stays" in log)
    check("baseline still 700", "baseline=700.00" in log)
    check("floor still 455", "floor=455.00" in log)

    print("\n9i. a target too small for one lot is explained, not silent")
    log, plan, st = run(160.0, {}, target=0.17)
    check("no order", len(plan) == 0)
    check("the lot fraction is reported", "of a" in log and "lot" in log)
    check("the inflation and the cap are named", "cap -- skipping" in log)

    print("\n9j. the same small target trades once capital is larger")
    log, plan, st = run(700.0, {}, target=0.17)
    check("one order", len(plan) == 1)

    print("\n9k. whatever the strategy actually wants today")
    live_tgt = live.get("BTCUSDT", 0.0)
    log, plan, st = run(700.0, {}, target=live_tgt)
    check("completes without error", "done" in log,
          f"live target {live_tgt:.4f}, {len(plan)} order(s)")

    print("\n10. wallet below the kill floor, with a baseline on record")
    log, plan, st = run(300.0, {}, state={"baseline_equity": 700.0})
    check("kill reported", "KILL SWITCH would trip" in log)
    check("NOT latched in a dry run",
          "killed_at" not in L.STATE.read_text(encoding="utf-8"))
    check("no orders", len(plan) == 0)

    print("\n11. wallet above REAL_CAPITAL -- the ceiling holds")
    log, plan, st = run(2000.0, {})
    check("sizing capped at 700", "sizing=700.00" in log)
    o = orders_of(plan)
    check("order sized off 700, not 2000", o and o[0]["notional"] < tgt * 1000,
          f"{o[0]['notional']:,.2f} USD" if o else "")

    print("\n12. REAL_CAPITAL unset -- sizes off the wallet")
    log, plan, st = run(450.0, {}, real_capital=None)
    check("sizing follows the wallet", "sizing=450.00" in log)

    bad = [n for n, ok, _ in CHECKS if not ok]
    print(f"\n{'=' * 62}\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    for n in bad:
        print(f"  FAILED: {n}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
