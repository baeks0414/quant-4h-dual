#!/usr/bin/env python3
"""
Real-money runner for the 4h dual-sleeve strategy — target-position reconciliation.

WHY NOT JUST SWAP IN THE REAL BROKER
    paper_live_stateful.py replays the whole history through the Engine on every
    run. Handing that Engine a live broker would re-place every historical order.
    So the replay stays on PaperBroker and is used only to derive the DESIRED
    position. This script compares that desire against what the exchange actually
    holds and trades only the difference. A crash, a restart or a missed bar
    therefore cannot duplicate orders: the diff is recomputed from real exchange
    state every time, never from a local ledger.

EXECUTION
    Limit-first, market-fallback. The strategy was measured to be insensitive to
    execution timing (a full 4h delay moved CAGR by 0.2 points), so resting as a
    maker is close to free. GTX (post-only) guarantees the maker fee of 0.020%
    instead of the 0.050% taker. Anything unfilled after LIMIT_WAIT_SEC is taken
    at market so a runaway price cannot leave the book unhedged.

SIZING
    Quantities round to the NEAREST lot. floor() biases every position smaller
    than intended; measured over 495 round trips at 700 USD it cost 1.8 points of
    total return and dropped 10 trades, versus 0.5 points and 1 trade for
    round-to-nearest.

SAFETY
    DRY_RUN defaults to "1". Nothing is sent until you set DRY_RUN=0 yourself.
    Every guard refuses to trade rather than guessing. The kill switch latches:
    once tripped it will not resume on its own.

Env:
    BINANCE_API_KEY / BINANCE_API_SECRET   futures trading only, NO withdrawal
    DRY_RUN            "1" (default) logs orders without sending. "0" trades.
    REAL_CAPITAL       ceiling on the notional the strategy sizes against.
                       Sizing follows the wallet and never exceeds it, so this
                       only matters when you want to commit part of the account.
                       Default: the wallet balance.
    KILL_DRAWDOWN      fraction below the starting wallet that halts trading,
                       measured from a baseline recorded on the first live run.
                       Default 0.35
    MAX_ORDER_MULT     refuse any single order above this multiple of the
                       capital in use. Default 2.0 -- a full reversal is 2x.
    MAX_GROSS_MULT     refuse to trade if the target book exceeds this multiple
                       of the capital in use. Default 3.0.
    MAX_ORDER_USD      absolute override for MAX_ORDER_MULT, in USD. Unset by
    MAX_GROSS_USD      default; a fixed cap stops scaling once capital moves.
    LIMIT_WAIT_SEC     how long to rest as a maker before taking. Default 90.
    TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ["QUANT_MEM_CACHE"] = "0"
os.environ["QUANT_BT_USE_MEM_CACHE"] = "0"
os.environ["QUANT_BT_PROGRESS_EVERY"] = "0"
os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"

import pandas as pd
import requests

DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
KILL_DRAWDOWN = float(os.environ.get("KILL_DRAWDOWN", "0.35"))
# Order caps are read inside main(), because they are derived from the capital
# actually in use. A fixed dollar cap looks prudent and is not: this strategy
# holds up to about 100% of capital in one leg, so a 300 USD cap on a 700 USD
# account refused every entry it ever tried to make, silently, forever.
MAX_ORDER_MULT = 2.0    # a reversal is twice the position, so 2x is the floor
MAX_GROSS_MULT = 3.0
LIMIT_WAIT_SEC = int(os.environ.get("LIMIT_WAIT_SEC", "90"))
POLL_SEC = 5

RESULTS = ROOT / "results" / "live_real"
RESULTS.mkdir(parents=True, exist_ok=True)
STATE = RESULTS / "state.json"
FAPI = "https://fapi.binance.com"


def log(m):
    print(f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}] {m}", flush=True)


def notify(text: str) -> None:
    tok = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": text, "parse_mode": "HTML"},
                      timeout=15)
    except Exception as exc:  # noqa: BLE001
        log(f"telegram failed: {exc}")


# ───────────────────────── desired position ─────────────────────────
# The replay below mirrors paper_live_stateful.py. It is duplicated rather than
# imported because that script is a single 400-line main() with no reusable
# entry point, and refactoring a runner that is currently live is the riskier of
# the two options. Everything that defines the STRATEGY (presets, Engine,
# RiskManager, features) is imported from the same package, so only the
# orchestration loop is duplicated. scripts/verify_target.py checks that this
# reproduces the paper runner's reported positions.

from quant.config.presets import (                                # noqa: E402
    preset_dynamic_bear_state_trend, preset_balanced_alpha_sleeve_aggressive)
from quant.core.engine import Engine                              # noqa: E402
from quant.core.market import update_market_regime_gate           # noqa: E402
from quant.core.portfolio import Portfolio                        # noqa: E402
from quant.core.risk import RiskManager                           # noqa: E402
from quant.core.risk_vol import VolScaledRiskManager              # noqa: E402
from quant.data.features import add_features, to_feature_rows     # noqa: E402
from quant.execution.paper_broker import PaperBroker              # noqa: E402
from quant.strategies.wrappers import (                           # noqa: E402
    MarketRegimeGate, MarketRegimeGateConfig)
from quant.strategies.your_strategy import YourStrategy           # noqa: E402

INITIAL_EQUITY = 10_000.0
TREND_WEIGHT, SLEEVE_WEIGHT = 0.70, 0.30
WARMUP_BARS = 500


def _build_strategy(cfg):
    return MarketRegimeGate(
        YourStrategy(cfg),
        MarketRegimeGateConfig(
            market_symbol=cfg.market_symbol,
            allow_regimes=tuple(cfg.allow_regimes),
        ),
    )


def _fetch_bars(sym: str, interval: str, n: int) -> pd.DataFrame:
    ms = {"4h": 4 * 3600_000}[interval]
    end = int(time.time() * 1000)
    d = requests.get(f"{FAPI}/fapi/v1/klines",
                     params={"symbol": sym, "interval": interval,
                             "startTime": end - ms * (n + 2), "limit": n + 2},
                     timeout=25)
    d.raise_for_status()
    df = pd.DataFrame(d.json(), columns=["open_time", "open", "high", "low",
                                         "close", "volume", "ct", "qav", "n",
                                         "tb", "tq", "ig"])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("open_time")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df[["open", "high", "low", "close", "volume"]].iloc[:-1]


def _fetch_funding(sym: str, days: int = 7) -> pd.DataFrame:
    start = int((time.time() - days * 86400) * 1000)
    r = requests.get(f"{FAPI}/fapi/v1/fundingRate",
                     params={"symbol": sym, "startTime": start, "limit": 1000},
                     timeout=25)
    r.raise_for_status()
    d = pd.DataFrame(r.json())
    if d.empty:
        return pd.DataFrame()
    d["fundingTime"] = pd.to_datetime(d["fundingTime"].astype("int64"),
                                      unit="ms", utc=True)
    d["fundingRate"] = d["fundingRate"].astype(float)
    return d.set_index("fundingTime")[["fundingRate"]].sort_index()


def desired_positions():
    """Replay and read off the position the strategy wants, as a signed fraction
    of its own equity so it rescales to whatever real capital is in use."""
    trend_cfg = preset_dynamic_bear_state_trend()
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT
    symbols, interval = list(trend_cfg.symbols), trend_cfg.interval

    log("fetching bars for the replay ...")
    price, feat_t, feat_s = {}, {}, {}
    for sym in symbols:
        price[sym] = _fetch_bars(sym, interval, WARMUP_BARS)
        feat_t[sym] = add_features(price[sym], trend_cfg)
        feat_s[sym] = add_features(price[sym], sleeve_cfg)
    funding = {s: _fetch_funding(s) for s in symbols}

    t_strat, s_strat = _build_strategy(trend_cfg), _build_strategy(sleeve_cfg)
    t_risk = (VolScaledRiskManager(trend_cfg) if trend_cfg.enable_vol_risk
              else RiskManager(trend_cfg))
    s_risk = (VolScaledRiskManager(sleeve_cfg) if sleeve_cfg.enable_vol_risk
              else RiskManager(sleeve_cfg))
    t_port = Portfolio(symbols=symbols, initial_cash=trend_cfg.initial_equity)
    s_port = Portfolio(symbols=symbols, initial_cash=sleeve_cfg.initial_equity)
    # PaperBroker on purpose: the replay must never touch the exchange
    t_eng = Engine(trend_cfg, t_strat, PaperBroker(trend_cfg), t_risk, t_port)
    s_eng = Engine(sleeve_cfg, s_strat, PaperBroker(sleeve_cfg), s_risk, s_port)

    mkt = trend_cfg.market_symbol
    log(f"replaying {len(feat_t[symbols[0]])} bars ...")
    for bar_t in feat_t[symbols[0]].index:
        t_py = bar_t.to_pydatetime()
        if trend_cfg.enable_regime_gate:
            update_market_regime_gate(t_strat, mkt, feat_t[mkt], bar_t,
                                      equity=t_port.equity)
        if sleeve_cfg.enable_regime_gate:
            update_market_regime_gate(s_strat, mkt, feat_s[mkt], bar_t,
                                      equity=s_port.equity)
        for sym in symbols:
            fdf = funding[sym]
            if fdf is not None and not fdf.empty:
                sub = fdf.loc[:bar_t]
                if not sub.empty:
                    rate = float(sub["fundingRate"].iloc[-1])
                    px = float(feat_t[sym].loc[bar_t, "close"])
                    t_port.update_close(sym, px)
                    t_port.apply_funding(t_py, sym, rate)
                    s_port.update_close(sym, px)
                    s_port.apply_funding(t_py, sym, rate)
        for sym in symbols:
            fdf = funding[sym]
            fr = None
            if fdf is not None and not fdf.empty:
                sub = fdf.loc[:bar_t]
                if not sub.empty:
                    fr = float(sub["fundingRate"].iloc[-1])
            t_eng.on_bar(to_feature_rows(sym, feat_t[sym].loc[[bar_t]])[0],
                         funding_rate=fr)
            s_eng.on_bar(to_feature_rows(sym, feat_s[sym].loc[[bar_t]])[0],
                         funding_rate=fr)
        t_eng.snapshot_curve(t_py)
        s_eng.snapshot_curve(t_py)

    bar = feat_t[symbols[0]].index[-1]
    total = t_port.equity + s_port.equity
    frac, detail = {}, {}
    for name, port in (("trend", t_port), ("sleeve", s_port)):
        for sym, p in port.positions.items():
            detail[f"{name}:{sym}"] = ("FLAT" if p.side == 0
                                       else ("LONG" if p.side > 0 else "SHORT"))
            if p.side == 0 or p.qty <= 0:
                continue
            frac[sym] = frac.get(sym, 0.0) + p.side * p.qty * port.last_close[sym] / total
    return frac, bar, detail


# ───────────────────────── exchange access ─────────────────────────
class Futures:
    """Thin Binance USDT-M client. Only the endpoints this runner needs."""

    def __init__(self, key: str, secret: str):
        import hashlib
        import hmac
        import urllib.parse
        self._h, self._hm, self._url = hashlib, hmac, urllib.parse
        self.key, self.secret = key, secret
        self.s = requests.Session()
        self.s.headers.update({"X-MBX-APIKEY": key})

    def _signed(self, method, path, params=None):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000)
        p["recvWindow"] = 10_000
        qs = self._url.urlencode(p, doseq=True)
        p["signature"] = self._hm.new(self.secret.encode(), qs.encode(),
                                      self._h.sha256).hexdigest()
        r = self.s.request(method, FAPI + path, params=p, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.text}")
        return r.json()

    def public(self, path, params=None):
        r = self.s.get(FAPI + path, params=params or {}, timeout=20)
        r.raise_for_status()
        return r.json()

    def positions(self) -> dict:
        out = {}
        for row in self._signed("GET", "/fapi/v2/positionRisk"):
            amt = float(row.get("positionAmt") or 0)
            if abs(amt) > 0:
                out[row["symbol"]] = amt
        return out

    def risk(self) -> dict:
        """Leverage and margin mode per symbol, from the same endpoint as
        positions(). A symbol left on 1x cannot post margin for a position the
        size of the account, and the only sign of it is a rejected order."""
        return {row["symbol"]: {"leverage": float(row.get("leverage") or 1),
                                "margin": row.get("marginType", "?")}
                for row in self._signed("GET", "/fapi/v2/positionRisk")}

    def _account(self) -> dict:
        if getattr(self, "_acct", None) is None:
            self._acct = self._signed("GET", "/fapi/v2/account")
        return self._acct

    def _asset_usdt(self, field: str) -> float:
        for a in self._account().get("assets", []):
            if a.get("asset") == "USDT":
                return float(a.get(field) or 0)
        return 0.0

    def available_usdt(self) -> float:
        return self._asset_usdt("availableBalance")

    def wallet_usdt(self) -> float:
        return self._asset_usdt("walletBalance")

    def rules(self) -> dict:
        out = {}
        for s in self.public("/fapi/v1/exchangeInfo")["symbols"]:
            d = {}
            for f in s.get("filters", []):
                if f["filterType"] == "LOT_SIZE":
                    d["step"] = Decimal(f["stepSize"])
                    d["minq"] = Decimal(f["minQty"])
                if f["filterType"] == "PRICE_FILTER":
                    d["tick"] = Decimal(f["tickSize"])
                if f["filterType"] == "MIN_NOTIONAL":
                    d["minn"] = Decimal(str(f.get("notional", "0")))
            out[s["symbol"]] = d
        return out

    def open_orders(self, sym: str | None = None) -> list:
        return self._signed("GET", "/fapi/v1/openOrders",
                            {"symbol": sym} if sym else {})

    def cancel_all(self, sym: str):
        return self._signed("DELETE", "/fapi/v1/allOpenOrders", {"symbol": sym})

    def book(self, sym: str):
        d = self.public("/fapi/v1/ticker/bookTicker", {"symbol": sym})
        return float(d["bidPrice"]), float(d["askPrice"])

    def limit_maker(self, sym, side, qty, price):
        """GTX = post-only. Rejected outright if it would cross, so the maker
        fee is guaranteed."""
        return self._signed("POST", "/fapi/v1/order", {
            "symbol": sym, "side": side, "type": "LIMIT", "quantity": qty,
            "price": price, "timeInForce": "GTX",
            "newClientOrderId": _cid(sym, side, "L")})

    def market(self, sym, side, qty):
        return self._signed("POST", "/fapi/v1/order", {
            "symbol": sym, "side": side, "type": "MARKET", "quantity": qty,
            "newOrderRespType": "RESULT",
            "newClientOrderId": _cid(sym, side, "M")})

    def order(self, sym, order_id):
        return self._signed("GET", "/fapi/v1/order",
                            {"symbol": sym, "orderId": order_id})

    def cancel(self, sym, order_id):
        return self._signed("DELETE", "/fapi/v1/order",
                            {"symbol": sym, "orderId": order_id})


def _cid(sym: str, side: str, kind: str) -> str:
    return f"D4H{kind}{side[0]}{sym[:4]}{int(time.time() * 1000) % 10 ** 9}"[:36]


MAX_ROUND_UP = float(os.environ.get("MAX_ROUND_UP", "0.25"))


def q_round(qty: float, step: Decimal) -> Decimal:
    """
    Round to the NEAREST lot, but never inflate a position by more than
    MAX_ROUND_UP.

    Nearest beats floor on average (see the SIZING note above), but near the
    minimum lot it can double the intended size: a target of 0.00051 BTC rounds
    to 0.001, which is 96% more risk than the strategy asked for. Rounding up is
    therefore capped, and anything that would still overshoot is rounded down
    instead -- usually to zero, i.e. the trade is skipped. Taking no position is
    always safer than taking one twice the intended size.
    """
    want = Decimal(str(abs(qty)))
    up = (want / step).to_integral_value(rounding=ROUND_HALF_UP) * step
    if want > 0 and up > want and (up - want) / want > Decimal(str(MAX_ROUND_UP)):
        return (want / step).to_integral_value(rounding=ROUND_DOWN) * step
    return up


def p_round(px: float, tick: Decimal, up: bool) -> Decimal:
    p = Decimal(str(px)) / tick
    p = p.to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
    return p * tick


def fmt(d: Decimal) -> str:
    return format(d, "f").rstrip("0").rstrip(".") or "0"


# ───────────────────────────── execution ─────────────────────────────
def execute(ex: Futures, sym: str, side: str, qty: Decimal, r: dict) -> dict:
    """Rest as a maker first, take whatever is left at market."""
    qs = fmt(qty)
    bid, ask = ex.book(sym)
    px = p_round(bid if side == "BUY" else ask, r["tick"], up=(side != "BUY"))

    try:
        o = ex.limit_maker(sym, side, qs, fmt(px))
    except Exception as exc:  # noqa: BLE001
        log(f"    post-only rejected ({exc}); taking at market")
        return {"mode": "market", "resp": ex.market(sym, side, qs)}

    oid = o.get("orderId")
    log(f"    limit {side} {qs} @ {fmt(px)} (id {oid}), resting up to {LIMIT_WAIT_SEC}s")
    st, waited = o, 0
    while waited < LIMIT_WAIT_SEC:
        time.sleep(POLL_SEC)
        waited += POLL_SEC
        try:
            st = ex.order(sym, oid)
        except Exception as exc:  # noqa: BLE001
            log(f"    status check failed: {exc}")
            continue
        if st.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
            break

    filled = float(st.get("executedQty") or 0)
    known = True
    if st.get("status") not in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
        try:
            receipt = ex.cancel(sym, oid)
            try:
                st = ex.order(sym, oid)
                filled = float(st.get("executedQty") or 0)
            except Exception as exc:  # noqa: BLE001
                # The cancel receipt carries executedQty as well, and it is the
                # only record of the fill left when the status endpoint is
                # unreachable. Ignoring it and taking the full size at market
                # buys the filled portion a second time.
                log(f"    status unreadable after cancel ({exc}); "
                    f"using the cancel receipt")
                st = receipt
                filled = float(receipt.get("executedQty") or 0)
        except Exception as exc:  # noqa: BLE001
            log(f"    cancel failed: {exc}")
            known = False

    if not known:
        # Neither the status nor the cancel could be read, so the fill could be
        # anything from nothing to the whole order. Topping up at market would
        # risk doubling the position. Doing nothing cannot: the next run
        # reconciles against the actual exchange position and closes the gap.
        log("    FILL UNKNOWN -- order status and cancel both failed. Sending "
            "nothing further; the next run reconciles from the real position.")
        notify(f"{sym} {side}: fill unknown, nothing further sent. "
               f"Check for a resting order.")
        return {"mode": "unknown", "maker_qty": None, "status": "UNKNOWN"}

    if filled > 0:
        log(f"    maker filled {filled}")
    remain = q_round(float(qty) - filled, r["step"])
    mid = (bid + ask) / 2
    if remain >= r["minq"] and float(remain) * mid >= float(r.get("minn", 0)):
        log(f"    taking remaining {fmt(remain)} at market")
        return {"mode": "limit+market", "maker_qty": filled,
                "taker": ex.market(sym, side, fmt(remain))}
    return {"mode": "limit", "maker_qty": filled, "status": st.get("status")}


# ───────────────────────────── main ─────────────────────────────
def main() -> None:
    key = os.environ.get("BINANCE_API_KEY", "").strip()
    sec = os.environ.get("BINANCE_API_SECRET", "").strip()
    if not key or not sec:
        raise SystemExit("BINANCE_API_KEY / BINANCE_API_SECRET not set")

    ex = Futures(key, sec)
    wallet = ex.wallet_usdt()

    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    # The baseline is recorded once, on the first live run, so the kill switch
    # measures drawdown from where trading began rather than from a moving
    # reference that resets after every loss.
    #
    # It is read from the WALLET, never from REAL_CAPITAL. Those are different
    # quantities: REAL_CAPITAL is the notional the strategy sizes against, while
    # the wallet is what the account actually holds. An account that has not been
    # funded yet has a small wallet and a large REAL_CAPITAL, and taking the
    # baseline from the latter made that look like a 96% loss -- latching the
    # kill switch before a single order had ever been placed.
    baseline = float(st.get("baseline_equity") or wallet)
    capital = float(os.environ.get("REAL_CAPITAL", wallet))
    floor_equity = baseline * (1.0 - KILL_DRAWDOWN)

    # REAL_CAPITAL is a CEILING, not a fixed notional. The backtest compounds --
    # position size follows equity -- so the wallet is the honest figure to size
    # against, and REAL_CAPITAL only lets you commit a part of the account.
    #
    # Letting it exceed the wallet would be leverage taken by accident: a 700 USD
    # book on a 29 USD wallet is 23x. Clamping rather than refusing matters after
    # a loss, too. A fixed 700 with a wallet at 500 would refuse every order,
    # freezing the book at exactly the point where it most needs to de-risk.
    if capital > wallet:
        if capital > wallet * 1.05:
            log(f"NOTE: REAL_CAPITAL {capital:.2f} exceeds the futures wallet "
                f"{wallet:.2f}; sizing against the wallet. Legs below the exchange "
                f"minimum will be skipped. Transfer USDT if you meant {capital:.0f}.")
        capital = wallet

    max_order = float(os.environ.get("MAX_ORDER_USD") or MAX_ORDER_MULT * capital)
    max_gross = float(os.environ.get("MAX_GROSS_USD") or MAX_GROSS_MULT * capital)

    log(f"mode={'DRY RUN' if DRY_RUN else 'LIVE'}  wallet={wallet:.2f} USDT  "
        f"baseline={baseline:.2f}  floor={floor_equity:.2f}  sizing={capital:.2f}")
    log(f"caps: order {max_order:.2f} USD, gross {max_gross:.2f} USD")
    if max_order < capital:
        log(f"WARNING: the order cap {max_order:.2f} is below the capital "
            f"{capital:.2f}. This strategy takes positions near 100% of capital, "
            f"so entries will be refused. Raise or unset MAX_ORDER_USD.")

    if st.get("killed_at"):
        log(f"kill switch tripped at {st['killed_at']}; refusing to resume. "
            f"Clear 'killed_at' in {STATE} to restart deliberately.")
        return
    if wallet < floor_equity:
        msg = (f"wallet {wallet:.2f} below the {KILL_DRAWDOWN:.0%} drawdown floor "
               f"{floor_equity:.2f} (baseline {baseline:.2f})")
        if DRY_RUN:
            # A rehearsal must leave no trace. Latching here would halt the live
            # system on the strength of a run that never sent an order.
            log(f"KILL SWITCH would trip: {msg}  (dry run, not latched)")
            return
        log(f"KILL SWITCH: {msg}")
        notify(f"KILL SWITCH TRIPPED\n{msg}\nNo further orders will be placed.")
        st["killed_at"] = str(pd.Timestamp.now(tz="UTC"))
        st["baseline_equity"] = baseline
        STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")
        return

    frac, bar, detail = desired_positions()
    log(f"decision bar {bar}   target "
        f"{ {k: round(v, 4) for k, v in frac.items()} or 'flat'}")

    rules = ex.rules()
    actual = ex.positions()
    plan, gross = [], 0.0

    for sym in sorted(set(frac) | set(actual)):
        r = rules.get(sym)
        if not r:
            log(f"  {sym}: no exchange rules, skipping")
            continue
        bid, ask = ex.book(sym)
        mid = (bid + ask) / 2
        want_qty = frac.get(sym, 0.0) * capital / mid
        have_qty = actual.get(sym, 0.0)
        gross += abs(want_qty * mid)
        delta = want_qty - have_qty
        q = q_round(delta, r["step"])
        notional = float(q) * mid
        if q <= 0:
            continue
        if q < r["minq"]:
            log(f"  {sym}: delta {delta:+.6f} below minQty {r['minq']}, skipping")
            continue
        if notional < float(r.get("minn", 0)):
            log(f"  {sym}: {notional:.2f} below minNotional {r.get('minn')}, skipping")
            continue
        if notional > max_order:
            log(f"  {sym}: REFUSED, {notional:.2f} over the order cap {max_order:.2f}")
            notify(f"order refused {sym} ${notional:.0f} over cap ${max_order:.0f}")
            continue
        plan.append({"symbol": sym, "side": "BUY" if delta > 0 else "SELL",
                     "qty": q, "notional": notional, "rules": r,
                     "have": have_qty, "want": want_qty})

    if gross > max_gross:
        msg = f"target gross {gross:.0f} over the gross cap {max_gross:.0f}"
        log(f"REFUSED: {msg}")
        notify(f"refused: {msg}")
        return

    log(f"target gross {gross:.2f} USD, {len(plan)} order(s)")
    for p in plan:
        log(f"  {p['side']:<4} {p['symbol']:<10} qty={fmt(p['qty']):<12} "
            f"~${p['notional']:8.2f}   (have {p['have']:+.6f} -> want {p['want']:+.6f})")

    # An order is only placeable if the account can post its initial margin,
    # which depends on the leverage configured for that symbol. Nothing else
    # here would notice a symbol left on 1x: the order just comes back rejected
    # at the one moment it matters.
    margin_short = None
    if plan:
        risk = ex.risk()
        avail = ex.available_usdt()
        need = 0.0
        for p in plan:
            info = risk.get(p["symbol"], {})
            lev = info.get("leverage") or 1.0
            m = p["notional"] / lev
            need += m
            log(f"  {p['symbol']}: {lev:g}x {info.get('margin', '?')}, "
                f"margin {m:.2f} USD")
        log(f"margin required {need:.2f} USDT, available {avail:.2f}")
        if need > avail:
            margin_short = (f"the plan needs {need:.2f} USDT of margin, "
                            f"{avail:.2f} available")

    sent = []
    if DRY_RUN:
        log("DRY RUN — nothing sent. Set DRY_RUN=0 to trade.")
        if margin_short:
            log(f"NOTE: a live run would refuse -- {margin_short}")
    elif margin_short:
        log(f"NOT TRADING: {margin_short}. Raise the leverage on the "
            f"symbol(s) above, add margin, or reduce size.")
        notify("not trading, insufficient margin -- " + margin_short)
    else:
        # A resting order left by an earlier run would fill on top of the
        # position this plan was computed from, which is exactly the assumption
        # reconciliation depends on. Clear the slate before sending anything.
        try:
            stale = {o["symbol"] for o in ex.open_orders()}
            for sym in sorted(stale):
                ex.cancel_all(sym)
                log(f"  cleared resting order(s) on {sym}")
        except Exception as exc:  # noqa: BLE001
            log(f"  ABORTING: could not verify open orders are clear: {exc}")
            notify("aborted: could not clear resting orders -- " + str(exc))
            return

        for p in plan:
            try:
                res = execute(ex, p["symbol"], p["side"], p["qty"], p["rules"])
                log(f"  {p['symbol']} done via {res.get('mode')}")
                sent.append({"symbol": p["symbol"], "side": p["side"], **res})
            except Exception as exc:  # noqa: BLE001
                log(f"  ORDER FAILED {p['side']} {p['symbol']}: {exc}")
                notify(f"order failed {p['symbol']} {p['side']}\n{exc}")

    stamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S")
    (RESULTS / f"run_{stamp}.json").write_text(json.dumps({
        "bar": str(bar), "dry_run": DRY_RUN, "wallet": wallet,
        "baseline": baseline, "capital": capital, "kill_floor": floor_equity,
        "max_order": max_order, "max_gross": max_gross,
        "target_fraction": frac, "detail": detail, "actual": actual,
        "plan": [{k: (fmt(v) if isinstance(v, Decimal) else v)
                  for k, v in p.items() if k != "rules"} for p in plan],
        "sent": sent,
    }, indent=2, default=str), encoding="utf-8")

    if DRY_RUN:
        # A rehearsal records nothing. In particular it must not record a
        # baseline: that number anchors the kill switch for the life of the
        # account, and a dry run made before the wallet is funded would anchor
        # it to the wrong figure permanently.
        log(f"state.json left untouched (dry run); plan saved as run_{stamp}.json")
    else:
        st.update({"baseline_equity": baseline, "last_bar": str(bar),
                   "last_wallet": wallet, "last_run": stamp})
        STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")

    dd = wallet / baseline - 1.0 if baseline > 0 else 0.0
    notify(f"<b>DUAL 4H {'DRY' if DRY_RUN else 'LIVE'}</b>\n{bar}\n"
           f"wallet ${wallet:,.2f} ({dd:+.1%} vs baseline)\n"
           f"orders {len(plan)}" + (f" | sent {len(sent)}" if not DRY_RUN else ""))
    log("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        notify(f"live_real failed: {type(exc).__name__}: {exc}")
        raise
