# src/quant/core/runner.py
from __future__ import annotations

import os
import time
from collections import Counter
from datetime import datetime
from typing import Optional, Dict, Any

import pandas as pd

from quant.config.presets import PortfolioBTConfig
from quant.core.engine import Engine
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.core.metrics import build_benchmark_equity_curve, compute_metrics

from quant.data.binance_fetch import fetch_klines, fetch_funding_rates, interval_to_ms
from quant.data.loaders import add_features, to_feature_rows
from quant.reporting.artifacts import save_csvs
from quant.strategies.your_strategy import YourStrategy

from quant.util.state import load_state, save_state_atomic
from quant.core.clock import BarClock
from quant.core.market import update_market_regime_gate
from quant.execution.broker_base import SupportsPositions, SupportsBalance
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def update_price_cache(
    symbol: str,
    interval: str,
    cache: pd.DataFrame,
    keep_rows: int,
    initial_days: int,
) -> pd.DataFrame:
    end = pd.Timestamp.now("UTC")

    if cache is None or cache.empty:
        start = end - pd.Timedelta(days=initial_days)
        df = fetch_klines(symbol, interval, _ms(start), _ms(end))
    else:
        last = cache.index[-1]
        start = last - pd.Timedelta(milliseconds=interval_to_ms(interval) * 5)  # buffer
        df_new = fetch_klines(symbol, interval, _ms(start), _ms(end))
        df = pd.concat([cache, df_new], axis=0)

    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df) > keep_rows:
        df = df.iloc[-keep_rows:]
    return df


def fetch_funding_recent(symbol: str, days: int = 7) -> pd.DataFrame:
    end = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(days=days)
    return fetch_funding_rates(symbol, _ms(start), _ms(end))


def _side_str(side: Any) -> str:
    if side == 0:
        return "FLAT"
    if side > 0:
        return "LONG"
    return "SHORT"


def _read_env_float(name: str) -> Optional[float]:
    v = os.getenv(name, "").strip()
    if not v:
        return None
    try:
        return float(v)
    except Exception as e:
        raise ValueError(f"Invalid float env var {name}={v!r}") from e


def run_live(
    cfg: PortfolioBTConfig,
    broker,
    poll_seconds: int = 30,
    outdir: str = "result",
    state_path: str = "result/state_live.json",
    keep_rows: int = 2500,
    initial_days: int = 120,
    save_every_bars: int = 50,
    # 실전 안전장치
    min_usdt_balance_to_run: float = 1.0,
    deploy_capital_usdt: Optional[float] = None,
) -> None:
    """
    paper/real 공통 라이브 러너.
    차이는 broker 주입만 다르게.

    - broker가 SupportsPositions / SupportsBalance 제공하면 실전 가드 동작
    - BarClock으로 봉 확정(마지막 close된 바) 안정화
    """

    # Strategy (+ optional regime gate wrapper)
    base = YourStrategy(cfg)
    if cfg.enable_regime_gate:
        strategy = MarketRegimeGate(
            base,
            MarketRegimeGateConfig(
                market_symbol=cfg.market_symbol,
                allow_regimes=cfg.allow_regimes,
                market_off_allow_symbol_regimes=getattr(cfg, "market_off_allow_symbol_regimes", ()),
                state_gate_symbol_regimes=getattr(cfg, "state_gate_symbol_regimes", ()),
                state_gate_allowed_market_regimes=getattr(cfg, "state_gate_allowed_market_regimes", ()),
                state_gate_min_drawdown=float(getattr(cfg, "state_gate_min_drawdown", -1.0)),
                state_gate_max_drawdown=float(getattr(cfg, "state_gate_max_drawdown", 0.0)),
                state_gate_min_market_adx=float(getattr(cfg, "state_gate_min_market_adx", 0.0)),
                state_gate_max_market_adx=float(getattr(cfg, "state_gate_max_market_adx", 100.0)),
                state_gate_min_market_ema_spread_atr=float(getattr(cfg, "state_gate_min_market_ema_spread_atr", 0.0)),
                state_gate_min_market_regime_streak=int(getattr(cfg, "state_gate_min_market_regime_streak", 1)),
                state_gate_max_market_regime_streak=int(getattr(cfg, "state_gate_max_market_regime_streak", 10_000)),
                bear_short_gate_allowed_market_regimes=getattr(cfg, "bear_short_gate_allowed_market_regimes", ()),
                bear_short_gate_min_market_adx=float(getattr(cfg, "bear_short_gate_min_market_adx", 0.0)),
                enable_conditional_trend_long_guard=bool(
                    getattr(cfg, "enable_conditional_trend_long_guard", False)
                ),
                trend_long_guard_allowed_market_regimes=getattr(
                    cfg, "trend_long_guard_allowed_market_regimes", ("STRONG_TREND",)
                ),
                trend_long_guard_symbol_spread_atr_min=float(
                    getattr(cfg, "trend_long_guard_symbol_spread_atr_min", 0.0)
                ),
                trend_long_guard_market_spread_atr_min=float(
                    getattr(cfg, "trend_long_guard_market_spread_atr_min", 0.0)
                ),
                trend_long_guard_market_regime_streak_min=int(
                    getattr(cfg, "trend_long_guard_market_regime_streak_min", 0)
                ),
                trend_long_guard_market_adx_max=float(
                    getattr(cfg, "trend_long_guard_market_adx_max", 100.0)
                ),
                entry_block_only=True,
            ),
        )
    else:
        strategy = base

    # Risk
    risk = VolScaledRiskManager(cfg) if cfg.enable_vol_risk else RiskManager(cfg)

    # -----------------------------
    # STARTUP SAFETY GUARDS
    # -----------------------------
    if isinstance(broker, SupportsPositions):
        open_pos = broker.get_open_positions()
        open_pos = {s: q for s, q in open_pos.items() if s in set(cfg.symbols) and abs(q) > 0}
        if open_pos:
            print("[LIVE][GUARD] Exchange has open positions. Stopping to prevent double-entry.")
            print("[LIVE][GUARD] open_positions =", open_pos)
            raise SystemExit(2)

    initial_cash = float(cfg.initial_equity)
    usdt_bal: Optional[float] = None

    if isinstance(broker, SupportsBalance):
        try:
            usdt_bal = float(broker.get_usdt_wallet_balance())

            if usdt_bal < float(min_usdt_balance_to_run):
                print("[LIVE][GUARD] USDT-M walletBalance too low to run safely.")
                print(f"[LIVE][GUARD] walletBalance={usdt_bal:.6f} < min_required={min_usdt_balance_to_run:.6f}")
                raise SystemExit(2)

            if deploy_capital_usdt is None:
                deploy_capital_usdt = _read_env_float("BOT_DEPLOY_CAPITAL")

            if deploy_capital_usdt is not None:
                if deploy_capital_usdt <= 0:
                    raise ValueError(f"deploy_capital_usdt must be > 0. got={deploy_capital_usdt}")
                if usdt_bal < deploy_capital_usdt:
                    print("[LIVE][GUARD] walletBalance < deploy_capital.")
                    print(f"[LIVE][GUARD] walletBalance={usdt_bal:.6f} < deploy_capital={deploy_capital_usdt:.6f}")
                    raise SystemExit(2)
                initial_cash = float(deploy_capital_usdt)
            else:
                initial_cash = usdt_bal

        except Exception as e:
            print("[LIVE][WARN] Failed to fetch USDT-M balance from broker:", repr(e))
            print("[LIVE][WARN] Using cfg.initial_equity as initial_cash:", initial_cash)

    # Portfolio/Engine
    portfolio = Portfolio(symbols=list(cfg.symbols), initial_cash=initial_cash)
    engine = Engine(cfg, strategy, broker, risk, portfolio)

    # Monitoring
    mkt_on_count = 0
    mkt_total = 0
    mkt_regime_counts = Counter()
    bar_count = 0

    price_cache: Dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in cfg.symbols}
    feat_cache: Dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in cfg.symbols}
    funding_cache: Dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in cfg.symbols}

    # State restore
    state = load_state(state_path)

    last_bar_time: Optional[pd.Timestamp] = None
    if state.get("last_bar_time"):
        try:
            last_bar_time = pd.Timestamp(state["last_bar_time"]).tz_convert("UTC")
        except Exception:
            last_bar_time = None

    last_funding_ts: Dict[str, Optional[pd.Timestamp]] = {s: None for s in cfg.symbols}
    if isinstance(state.get("last_funding_ts"), dict):
        for s in cfg.symbols:
            v = state["last_funding_ts"].get(s)
            if v:
                try:
                    last_funding_ts[s] = pd.Timestamp(v).tz_convert("UTC")
                except Exception:
                    last_funding_ts[s] = None

    # Clock (봉 확정)
    clock = BarClock(interval=cfg.interval, symbols=cfg.symbols, settle_lag_seconds=3)

    print(f"[LIVE] poll={poll_seconds}s interval={cfg.interval} symbols={cfg.symbols}")
    print(f"[LIVE] state_path={state_path} last_bar_time={last_bar_time}")
    if usdt_bal is None:
        print(f"[LIVE] initial_cash={initial_cash:,.6f} (cfg.initial_equity={float(cfg.initial_equity):,.6f})")
    else:
        print(f"[LIVE] walletBalance(USDT-M)={usdt_bal:,.6f} | deploy(initial_cash)={initial_cash:,.6f}")
    print("[LIVE] incremental mode ON")

    # Initial cache load
    for s in cfg.symbols:
        price_cache[s] = update_price_cache(
            s, cfg.interval, pd.DataFrame(), keep_rows=keep_rows, initial_days=initial_days
        )
        feat_cache[s] = add_features(price_cache[s], cfg)

    while True:
        try:
            # 1) Confirm last CLOSED bar time (common across symbols)
            t = clock.confirm_closed_bar_time()
            if t is None:
                time.sleep(poll_seconds)
                continue

            # dedup/restart guard
            if last_bar_time is not None and t <= last_bar_time:
                time.sleep(poll_seconds)
                continue

            last_bar_time = t
            t_py: datetime = t.to_pydatetime()
            bar_count += 1

            state["last_bar_time"] = str(last_bar_time)
            state.setdefault("last_funding_ts", {})
            save_state_atomic(state_path, state)

            # 2) Update caches (price -> features)
            for s in cfg.symbols:
                price_cache[s] = update_price_cache(
                    s, cfg.interval, price_cache[s], keep_rows=keep_rows, initial_days=initial_days
                )
                feat_cache[s] = add_features(price_cache[s], cfg)

            # 3) Funding refresh (once per new bar)
            for s in cfg.symbols:
                funding_cache[s] = fetch_funding_recent(s, days=7)

            # 4) Apply funding since last_funding_ts
            for s in cfg.symbols:
                fdf = funding_cache[s]
                if fdf is None or fdf.empty:
                    continue

                if last_funding_ts[s] is None:
                    to_apply = fdf.loc[:t]
                else:
                    to_apply = fdf.loc[(fdf.index > last_funding_ts[s]) & (fdf.index <= t)]

                if to_apply is not None and not to_apply.empty:
                    close_px = float(feat_cache[s].loc[t, "close"])
                    portfolio.update_close(s, close_px)

                    for fts, rowf in to_apply.iterrows():
                        rate = float(rowf["fundingRate"])
                        portfolio.apply_funding(fts.to_pydatetime(), s, rate)

                    last_funding_ts[s] = to_apply.index[-1]
                    state["last_funding_ts"][s] = str(last_funding_ts[s])
                    save_state_atomic(state_path, state)

            # 5) Market regime update (standardized)
            if cfg.enable_regime_gate:
                # feat_cache contains features already
                update_market_regime_gate(
                    strategy,
                    cfg.market_symbol,
                    feat_cache[cfg.market_symbol],
                    t,
                    equity=portfolio.equity,
                )

                mkt_total += 1
                if getattr(strategy, "market_on", False):
                    mkt_on_count += 1
                if getattr(strategy, "last_market_regime", None) is not None:
                    mkt_regime_counts[str(getattr(strategy, "last_market_regime"))] += 1

            # 6) on_bar for each symbol
            for s in cfg.symbols:
                fr = None
                fdf = funding_cache[s]
                if fdf is not None and not fdf.empty:
                    fdf2 = fdf.loc[:t]
                    if not fdf2.empty:
                        fr = float(fdf2["fundingRate"].iloc[-1])

                row = to_feature_rows(s, feat_cache[s].loc[[t]])[0]
                engine.on_bar(row, funding_rate=fr)

            engine.snapshot_curve(t_py)

            ratio = (mkt_on_count / mkt_total) if mkt_total else float("nan")
            pos = {s: _side_str(portfolio.positions[s].side) for s in cfg.symbols}
            print(
                f"[LIVE] {t} bar#{bar_count} equity={portfolio.equity:,.2f} "
                f"mktON={ratio:.2%} pos={pos} mktReg={getattr(strategy,'last_market_regime',None)}"
            )

            if save_every_bars > 0 and (bar_count % save_every_bars) == 0:
                res = engine.result()
                tag = f"{cfg.symbols[0]}_{cfg.symbols[1]}_{cfg.interval}_LIVE"
                if cfg.enable_regime_gate:
                    tag += "_regimeOnly"
                if cfg.enable_vol_risk:
                    tag += f"_pct{cfg.target_stop_pct:.3f}"
                tag += f"_cap{cfg.portfolio_risk_cap:.3f}"
                tag = tag.replace(".", "p").replace(":", "")
                save_csvs(res.equity_curve, res.trades, outdir, tag)
                print(f"[LIVE] saved -> {outdir} (every {save_every_bars} bars)")

            time.sleep(poll_seconds)

        except KeyboardInterrupt:
            print("\n[LIVE] stopped by user. Saving final...")
            break
        except Exception as e:
            print("[LIVE][ERROR]", repr(e))
            time.sleep(poll_seconds)

    res = engine.result()
    benchmark_curve = build_benchmark_equity_curve(
        res.equity_curve.index if not res.equity_curve.empty else pd.DatetimeIndex([], tz="UTC"),
        feat_cache[cfg.market_symbol]["close"] if cfg.market_symbol in feat_cache else pd.Series(dtype=float),
        cfg.initial_equity,
    )
    metrics = compute_metrics(
        res.equity_curve,
        res.trades,
        cfg.initial_equity,
        cfg.interval,
        benchmark_curve=benchmark_curve,
    )

    tag = f"{cfg.symbols[0]}_{cfg.symbols[1]}_{cfg.interval}_LIVE_FINAL"
    if cfg.enable_regime_gate:
        tag += "_regimeOnly"
    if cfg.enable_vol_risk:
        tag += f"_pct{cfg.target_stop_pct:.3f}"
    tag += f"_cap{cfg.portfolio_risk_cap:.3f}"
    tag = tag.replace(".", "p").replace(":", "")

    eq_path, tr_path = save_csvs(res.equity_curve, res.trades, outdir, tag)

    print("\n===== LIVE FINAL METRICS =====")
    for k, v in metrics.items():
        print(f"{k:18s}: {v:.6f}" if isinstance(v, float) else f"{k:18s}: {v}")
    print("\nSaved:")
    print(" -", eq_path)
    print(" -", tr_path)
