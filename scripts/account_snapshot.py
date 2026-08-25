#!/usr/bin/env python3
"""
Show exactly what the futures account holds, and what the runner would do to it.

    python scripts/account_snapshot.py

Read-only: it places nothing and changes nothing.

The runner reconciles POSITIONS. A coin sitting in the futures wallet as an
asset is not a position, so the runner cannot see it and will build its own
exposure on top. An open position, on the other hand, the runner treats as its
own and will adjust or close. Those are opposite behaviours, and from the
Binance app both look like "I have BTC in futures", so this prints which one is
actually the case.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_local import ENV, load_env  # noqa: E402  (also runs the leak check)

load_env()
import os  # noqa: E402

os.environ["DRY_RUN"] = "1"
import live_real as L  # noqa: E402

TRADED = ("BTCUSDT", "ETHUSDT")


def main() -> None:
    ex = L.Futures(os.environ["BINANCE_API_KEY"], os.environ["BINANCE_API_SECRET"])
    acct = ex._account()
    print(f"credentials: {ENV}\n")

    print("=== futures wallet assets ===")
    held = []
    for a in acct.get("assets", []):
        bal = float(a.get("walletBalance") or 0)
        if abs(bal) < 1e-8:
            continue
        held.append((a["asset"], bal, float(a.get("availableBalance") or 0)))
    if not held:
        print("  (empty)")
    for asset, bal, avail in held:
        print(f"  {asset:<8} balance {bal:>14,.8f}   available {avail:>14,.8f}")

    non_usdt = [h for h in held if h[0] != "USDT"]

    print("\n=== margin mode ===")
    try:
        multi = ex._signed("GET", "/fapi/v1/multiAssetsMargin")
        on = bool(multi.get("multiAssetsMargin"))
        print(f"  multi-assets mode: {'ON' if on else 'off'}")
    except Exception as exc:  # noqa: BLE001
        on = None
        print(f"  could not read multi-assets mode: {exc}")

    print("\n=== open positions (what the runner reconciles) ===")
    risk = ex._signed("GET", "/fapi/v2/positionRisk")
    open_pos = [r for r in risk if abs(float(r.get("positionAmt") or 0)) > 0]
    if not open_pos:
        print("  none")
    for r in open_pos:
        amt = float(r["positionAmt"])
        print(f"  {r['symbol']:<12} {amt:+.6f}  entry {float(r.get('entryPrice') or 0):,.2f}  "
              f"notional {abs(float(r.get('notional') or 0)):,.2f} USD  "
              f"uPnL {float(r.get('unRealizedProfit') or 0):+,.2f}")

    print("\n=== leverage on the symbols this strategy trades ===")
    for r in risk:
        if r["symbol"] in TRADED:
            lev = float(r.get("leverage") or 1)
            flag = "  <-- 1x cannot post margin for a full-size position" if lev <= 1 else ""
            print(f"  {r['symbol']:<12} {lev:g}x  {r.get('marginType', '?')}{flag}")

    print("\n=== what this means for the runner ===")
    usdt = next((b for a, b, _ in held if a == "USDT"), 0.0)
    print(f"  it sizes against the USDT balance only: {usdt:,.2f} USDT")

    if non_usdt:
        names = ", ".join(f"{b:,.8f} {a}" for a, b, _ in non_usdt)
        print(f"\n  You hold {names} in the futures wallet as an ASSET, not a")
        print("  position. The runner cannot see it. It will open its own BTC")
        print("  exposure on top, so your total BTC exposure is that coin PLUS")
        print("  whatever the strategy takes. None of the strategy's risk")
        print("  controls -- vol targeting, the kill switch -- cover the coin.")
        if on is False:
            print("\n  Multi-assets mode is off, so that balance is not usable as")
            print("  margin either. It is sitting there doing nothing for the")
            print("  strategy while still carrying full price risk.")
        if on is True:
            print("\n  Multi-assets mode is ON. The coin backs margin, but the")
            print("  runner still sizes off the USDT balance above, which is the")
            print("  figure it reads. If that is near zero it will not trade.")

    traded_open = [r for r in open_pos if r["symbol"] in TRADED]
    if traded_open:
        print("\n  You have an open position in a symbol this strategy trades:")
        for r in traded_open:
            print(f"    {r['symbol']} {float(r['positionAmt']):+.6f}")
        print("  The runner treats any position in these symbols as its own and")
        print("  will adjust or close it to match its target. If you want to keep")
        print("  it, close it before going live or move it to another account.")

    other_open = [r for r in open_pos if r["symbol"] not in TRADED]
    if other_open:
        print("\n  Positions in symbols the strategy does not trade are left")
        print("  alone, but they share the same margin pool, so a loss there can")
        print("  still trip this account's kill switch.")

    if not non_usdt and not open_pos:
        print("\n  Nothing to reconcile: the wallet holds USDT only and no")
        print("  positions are open. The runner starts from a clean slate.")


if __name__ == "__main__":
    main()
