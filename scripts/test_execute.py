#!/usr/bin/env python3
"""
Exercise execute() against a programmable fake exchange.

    python scripts/test_execute.py

execute() is the only part of the runner that moves real money, and it is the
one part a dry run never reaches. The scenarios below stand in for what the
exchange can do to a resting post-only order: fill it, fill part of it, reject
it outright, or stop answering questions about it.

The property that matters throughout is that the total quantity sent never
exceeds what was asked for. Under-trading is a missed opportunity; over-trading
is an unwanted position bought with real money.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("BINANCE_API_KEY", "simulated")
os.environ.setdefault("BINANCE_API_SECRET", "simulated")
os.environ["DRY_RUN"] = "1"

import live_real as L  # noqa: E402

L.time.sleep = lambda *_: None          # do not actually wait 90 seconds
L.notify = lambda *a, **k: None

MID = 80000.0
RULES = {"tick": Decimal("0.10"), "step": Decimal("0.001"),
         "minq": Decimal("0.001"), "minn": Decimal("50")}


class Stub:
    """A fake exchange whose resting order behaves however a test needs."""

    def __init__(self, *, fill_after=None, fill_qty=0.0, final_status="NEW",
                 reject_post_only=False, status_raises=False,
                 cancel_raises=False, cancel_reports=None):
        self.fill_after = fill_after      # polls before the order goes terminal
        self.fill_qty = fill_qty          # quantity filled by then
        self.final_status = final_status
        self.reject_post_only = reject_post_only
        self.status_raises = status_raises
        self.cancel_raises = cancel_raises
        self.cancel_reports = cancel_reports
        self.polls = 0
        self.market_orders = []
        self.limit_orders = []
        self.cancels = []

    def book(self, sym):
        return MID - 0.5, MID + 0.5

    def limit_maker(self, sym, side, qty, price):
        if self.reject_post_only:
            raise RuntimeError("-2021 Order would immediately trigger")
        self.limit_orders.append((sym, side, qty, price))
        return {"orderId": 1, "status": "NEW", "executedQty": "0"}

    def order(self, sym, oid):
        if self.status_raises:
            raise RuntimeError("-1001 disconnected")
        self.polls += 1
        if self.fill_after is not None and self.polls >= self.fill_after:
            return {"orderId": oid, "status": self.final_status,
                    "executedQty": str(self.fill_qty)}
        return {"orderId": oid, "status": "NEW", "executedQty": "0"}

    def cancel(self, sym, oid):
        if self.cancel_raises:
            raise RuntimeError("-2011 Unknown order sent")
        self.cancels.append(oid)
        return self.cancel_reports or {"orderId": oid, "status": "CANCELED",
                                       "executedQty": "0"}

    def market(self, sym, side, qty):
        self.market_orders.append((sym, side, qty))
        return {"orderId": 99, "status": "FILLED", "executedQty": qty}


CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))


def total_sent(ex, want: Decimal) -> float:
    """Everything execute() committed us to, as a fraction of what was asked."""
    taken = sum(float(q) for _, _, q in ex.market_orders)
    # the maker leg only counts what actually filled
    made = ex.fill_qty if ex.fill_after is not None else 0.0
    return (taken + made) / float(want)


def scenario(name, want, ex, expect_market, expect_ratio_at_most=1.0):
    print(f"\n{name}")
    res = L.execute(ex, "BTCUSDT", "BUY", want, RULES)
    ratio = total_sent(ex, want)
    check("total sent never exceeds the target", ratio <= expect_ratio_at_most + 1e-9,
          f"{ratio:.1%} of {want}")
    check(f"market leg {'sent' if expect_market else 'not sent'}",
          bool(ex.market_orders) == expect_market,
          f"{ex.market_orders}" if ex.market_orders else "none")
    return res


def main() -> None:
    want = Decimal("0.007")

    scenario("1. the resting order fills completely",
             want, Stub(fill_after=1, fill_qty=0.007, final_status="FILLED"),
             expect_market=False)

    scenario("2. nothing fills -- the remainder is taken at market",
             want, Stub(fill_after=None), expect_market=True)

    ex = Stub(fill_after=1, fill_qty=0.004, final_status="CANCELED")
    scenario("3. partial fill -- only the remainder is taken",
             want, ex, expect_market=True)
    check("market leg is the remainder, not the whole order",
          ex.market_orders and abs(float(ex.market_orders[0][2]) - 0.003) < 1e-9,
          f"sent {ex.market_orders[0][2] if ex.market_orders else '-'}, expected 0.003")

    ex = Stub(reject_post_only=True)
    scenario("4. post-only rejected -- straight to market",
             want, ex, expect_market=True)
    check("no resting order was left behind", not ex.limit_orders)

    ex = Stub(fill_after=1, fill_qty=0.0069, final_status="CANCELED")
    scenario("5. remainder below the lot size -- nothing more is sent",
             want, ex, expect_market=False)

    # The dangerous one. The order rested, the exchange stopped answering, and
    # the cancel receipt is the only evidence of what filled.
    ex = Stub(status_raises=True,
              cancel_reports={"orderId": 1, "status": "CANCELED",
                              "executedQty": "0.005"})
    scenario("6. status queries fail; the cancel receipt reports a partial fill",
             want, ex, expect_market=True)
    check("did not re-buy the filled portion",
          ex.market_orders and float(ex.market_orders[0][2]) <= 0.002 + 1e-9,
          f"sent {ex.market_orders[0][2] if ex.market_orders else '-'}, "
          f"0.005 of 0.007 was already filled")

    ex = Stub(status_raises=True, cancel_raises=True)
    scenario("7. status and cancel both fail -- the fill is unknowable",
             want, ex, expect_market=False)
    check("refused to guess", not ex.market_orders,
          "an unknown fill must not be topped up at market")

    bad = [n for n, ok in CHECKS if not ok]
    print(f"\n{'=' * 62}\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    for n in bad:
        print(f"  FAILED: {n}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
