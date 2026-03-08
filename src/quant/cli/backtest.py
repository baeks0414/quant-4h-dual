# src/quant/cli/backtest.py
from __future__ import annotations

import argparse
import os
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import pandas as pd

from quant.config.presets import preset_regime_only_live, preset_mr_only, PortfolioBTConfig
from quant.core.engine import Engine
from quant.core.mr_engine import MREngine
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.core.metrics import build_benchmark_equity_curve, compute_metrics
from quant.data.binance_fetch import fetch_klines, fetch_funding_rates
from quant.data.loaders import add_features, intersect_timeline
from quant.data.features import df_to_feature_dict
from quant.execution.paper_broker import PaperBroker
from quant.reporting.artifacts import save_csvs
from quant.strategies.your_strategy import YourStrategy
from quant.strategies.mr_strategy import MRStrategy
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig


_BT_PREPARED_CACHE: dict[tuple, tuple] = {}


def _cache_enabled() -> bool:
    return os.environ.get("QUANT_BT_USE_MEM_CACHE", "1").strip() != "0"


def _progress_every() -> int:
    try:
        return max(0, int(os.environ.get("QUANT_BT_PROGRESS_EVERY", "500")))
    except Exception:
        return 500


def _prepared_cache_key(cfg: PortfolioBTConfig) -> tuple:
    # add_features() depends on these fields; strategy-only params do not require data rebuild.
    return (
        tuple(cfg.symbols),
        str(cfg.interval),
        str(cfg.start),
        str(cfg.end),
        int(cfg.ema_fast),
        int(cfg.ema_slow),
        float(cfg.adx_trend),
        float(cfg.atr_expand_ratio),
        int(cfg.donchian_window),
        int(getattr(cfg, "mr_window", 50)),
        int(getattr(cfg, "mr_bb_window", 14)),
        bool(getattr(cfg, "enable_bear_regime", False)),
    )


@dataclass
class _FundingCursor:
    ts_list: list
    rate_list: list
    idx: int = -1
    current: float | None = None

    def advance_to(self, t_py) -> float | None:
        i = self.idx
        n = len(self.ts_list)
        while (i + 1) < n and self.ts_list[i + 1] <= t_py:
            i += 1
            self.current = float(self.rate_list[i])
        self.idx = i
        return self.current


def _build_price_funding(cfg: PortfolioBTConfig):
    """Shared price/funding loader with prepared-data memoization."""
    ckey = _prepared_cache_key(cfg)
    if _cache_enabled():
        cached = _BT_PREPARED_CACHE.get(ckey)
        if cached is not None:
            return cached

    start_ms = int(pd.Timestamp(cfg.start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(cfg.end, tz="UTC").timestamp() * 1000)

    price = {}
    funding = {}

    def _load_one_symbol(sym: str):
        df = fetch_klines(sym, cfg.interval, start_ms, end_ms)
        df = add_features(df, cfg)
        fdf = fetch_funding_rates(sym, start_ms, end_ms)
        return sym, df, fdf

    symbols = list(cfg.symbols)
    if len(symbols) >= 2:
        max_workers = min(4, len(symbols))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for sym, df, fdf in ex.map(_load_one_symbol, symbols):
                price[sym] = df
                funding[sym] = fdf
    else:
        for sym in symbols:
            _, df, fdf = _load_one_symbol(sym)
            price[sym] = df
            funding[sym] = fdf

    # funding map: {symbol: {datetime: rate}}
    funding_map = {}
    for sym in symbols:
        fmap = {}
        fdf = funding[sym]
        if not fdf.empty:
            for t, r in fdf["fundingRate"].items():
                fmap[pd.Timestamp(t).to_pydatetime()] = float(r)
        funding_map[sym] = fmap

    idx = intersect_timeline(price, cfg.symbols)
    feature_dicts = {sym: df_to_feature_dict(sym, price[sym]) for sym in symbols}
    sorted_funding = _build_funding_sorted(funding)

    prepared = (price, funding, funding_map, idx, feature_dicts, sorted_funding)
    if _cache_enabled():
        _BT_PREPARED_CACHE[ckey] = prepared
    return prepared

def _build_funding_sorted(funding: dict) -> dict:
    """
    funding DataFrame??(sorted_timestamps, rates_list) ?띿쑝濡?蹂??
    留?諛붾쭏??loc[:t] ?щ씪?댁떛 ???bisect濡?O(log n) 留덉?留?funding rate 議고쉶.
    """
    result = {}
    for sym, fdf in funding.items():
        if fdf.empty:
            result[sym] = ([], [])
        else:
            ts_list = [t.to_pydatetime() for t in fdf.index]
            rate_list = fdf["fundingRate"].tolist()
            result[sym] = (ts_list, rate_list)
    return result


def run_backtest(cfg: PortfolioBTConfig, outdir: str = "result"):
    price, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(cfg)

    # strategy + wrappers
    base = YourStrategy(cfg)
    if getattr(cfg, "enable_regime_gate", False):
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
                entry_block_only=getattr(cfg, "regime_entry_block_only", False),
            ),
        )
    else:
        strategy = base

    risk = VolScaledRiskManager(cfg) if getattr(cfg, "enable_vol_risk", False) else RiskManager(cfg)

    portfolio = Portfolio(symbols=list(cfg.symbols), initial_cash=cfg.initial_equity)
    broker = PaperBroker(cfg)
    engine = Engine(cfg, strategy, broker, risk, portfolio)

    funding_cursor = {
        sym: _FundingCursor(sorted_funding[sym][0], sorted_funding[sym][1]) for sym in cfg.symbols
    }
    progress_every = _progress_every()

    # monitoring
    mkt_on_count = 0
    mkt_total = 0
    for t in idx:
        t_py = t.to_pydatetime()

        # 1) funding apply
        for sym in cfg.symbols:
            rate = funding_map[sym].get(t_py)
            if rate is not None:
                close_px = feature_dicts[sym][t].close
                portfolio.update_close(sym, close_px)
                portfolio.apply_funding(t_py, sym, rate)

        # 2) market regime update (wrapper)
        if getattr(cfg, "enable_regime_gate", False) and isinstance(strategy, MarketRegimeGate):
            mkt = cfg.market_symbol
            mkt_row = feature_dicts[mkt][t]   # O(1) dict 議고쉶
            strategy.update_market(mkt_row, equity=portfolio.equity)

            mkt_total += 1
            if strategy.market_on:
                mkt_on_count += 1

        # 3) symbols on_bar
        for sym in cfg.symbols:
            fr = funding_cursor[sym].advance_to(t_py)
            row = feature_dicts[sym][t]  # O(1)
            engine.on_bar(row, funding_rate=fr)

        engine.snapshot_curve(t_py)

        if progress_every > 0 and (len(engine.curve_rows) % progress_every) == 0:
            ratio = (mkt_on_count / mkt_total) if mkt_total else float("nan")
            print(f"[BACKTEST] bars={len(engine.curve_rows)} equity={portfolio.equity:,.2f} mktON={ratio:.2%}")

    res = engine.result()
    benchmark_curve = build_benchmark_equity_curve(
        res.equity_curve.index if not res.equity_curve.empty else idx,
        price[cfg.market_symbol]["close"],
        cfg.initial_equity,
    )
    metrics = compute_metrics(
        res.equity_curve,
        res.trades,
        cfg.initial_equity,
        cfg.interval,
        benchmark_curve=benchmark_curve,
    )

    # tag
    sym_tag = "_".join(cfg.symbols)
    tag = f"{sym_tag}_{cfg.interval}_{cfg.start}_{cfg.end}".replace(":", "")
    if getattr(cfg, "enable_regime_gate", False):
        tag += "_regimeOnly"
    if getattr(cfg, "enable_vol_risk", False):
        tag += f"_pct{cfg.target_stop_pct:.3f}"
    tag += f"_cap{cfg.portfolio_risk_cap:.3f}"
    tag = tag.replace(".", "p")

    save_artifacts = os.environ.get("QUANT_BT_SAVE_ARTIFACTS", "1").strip() != "0"
    if save_artifacts:
        eq_path, tr_path = save_csvs(res.equity_curve, res.trades, outdir, tag)
    else:
        eq_path, tr_path = "", ""

    print("\n===== BACKTEST METRICS =====")
    for k, v in metrics.items():
        print(f"{k:18s}: {v:.6f}" if isinstance(v, float) else f"{k:18s}: {v}")

    if save_artifacts:
        print("\nSaved:")
        print(" -", eq_path)
        print(" -", tr_path)

    return {
        "equity_curve": res.equity_curve,
        "trades": res.trades,
        "benchmark_equity_curve": benchmark_curve,
        "metrics": metrics,
        "paths": {"equity": eq_path, "trades": tr_path},
    }


def run_dual_backtest(outdir: str = "result_dual"):
    """
    諛⑸쾿 1: Dual Portfolio 諛깊뀒?ㅽ듃
    
    異붿꽭 ?꾨왂怨?MR ?꾨왂???꾩쟾??遺꾨━???ы듃?대━?ㅻ줈 ?댁쁺:
    - 異붿꽭 ?붿쭊: initial_equity * trend_equity_ratio, STRONG_TREND + VOL_EXPAND留?
    - MR ?붿쭊:   initial_equity * mr_equity_ratio,   CHOP?먯꽌留?BB Z-score MR
    - 理쒖쥌 equity = 異붿꽭 equity + MR equity (?꾩쟾 ?낅┰ ?댁쁺)
    
    ?댁젏:
    - MR ?꾨왂??異붿꽭 ?꾨왂???ъ???由ъ뒪?ъ벙???뚮퉬?섏? ?딆쓬
    - 媛??꾨왂???낅┰?곸쑝濡?compound ?④낵 ?꾨┝
    - 異붿꽭 ?꾨왂???쇰씪誘몃뵫??諛⑺빐諛쏆? ?딆쓬
    """
    # === 怨듯넻 ?ㅼ젙 ===
    INITIAL_EQUITY = 10_000.0
    TREND_RATIO = 0.7   # 70%: 異붿꽭 ?꾨왂
    MR_RATIO    = 0.3   # 30%: MR ?꾨왂

    trend_equity = INITIAL_EQUITY * TREND_RATIO   # $7,000
    mr_equity    = INITIAL_EQUITY * MR_RATIO       # $3,000

    # === 異붿꽭 ?꾨왂 cfg ===
    trend_cfg = preset_regime_only_live()
    trend_cfg.initial_equity = trend_equity

    # === MR ?꾨왂 cfg ===
    mr_cfg = preset_mr_only()
    mr_cfg.initial_equity = mr_equity
    mr_cfg.start = trend_cfg.start
    mr_cfg.end   = trend_cfg.end

    print(f"[DUAL] Trend equity: ${trend_equity:,.0f} | MR equity: ${mr_equity:,.0f}")
    print(f"[DUAL] Loading price data...")

    # === 怨듯넻 ?곗씠??濡쒕뱶 (???붿쭊???숈씪 bar ?곗씠??怨듭쑀) ===
    # trend_cfg 湲곗??쇰줈 濡쒕뱶 (媛숈? ?щ낵, 湲곌컙)
    _, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(trend_cfg)
    funding_cursor = {
        sym: _FundingCursor(sorted_funding[sym][0], sorted_funding[sym][1]) for sym in trend_cfg.symbols
    }
    progress_every = _progress_every()

    # === 異붿꽭 ?붿쭊 ?ㅼ젙 ===
    trend_base = YourStrategy(trend_cfg)
    trend_strategy = MarketRegimeGate(
        trend_base,
        MarketRegimeGateConfig(
            market_symbol=trend_cfg.market_symbol,
            allow_regimes=trend_cfg.allow_regimes,
            market_off_allow_symbol_regimes=getattr(trend_cfg, "market_off_allow_symbol_regimes", ()),
            state_gate_symbol_regimes=getattr(trend_cfg, "state_gate_symbol_regimes", ()),
            state_gate_allowed_market_regimes=getattr(trend_cfg, "state_gate_allowed_market_regimes", ()),
            state_gate_min_drawdown=float(getattr(trend_cfg, "state_gate_min_drawdown", -1.0)),
            state_gate_max_drawdown=float(getattr(trend_cfg, "state_gate_max_drawdown", 0.0)),
            state_gate_min_market_adx=float(getattr(trend_cfg, "state_gate_min_market_adx", 0.0)),
            state_gate_max_market_adx=float(getattr(trend_cfg, "state_gate_max_market_adx", 100.0)),
            state_gate_min_market_ema_spread_atr=float(getattr(trend_cfg, "state_gate_min_market_ema_spread_atr", 0.0)),
            state_gate_min_market_regime_streak=int(getattr(trend_cfg, "state_gate_min_market_regime_streak", 1)),
            state_gate_max_market_regime_streak=int(getattr(trend_cfg, "state_gate_max_market_regime_streak", 10_000)),
            bear_short_gate_allowed_market_regimes=getattr(trend_cfg, "bear_short_gate_allowed_market_regimes", ()),
            bear_short_gate_min_market_adx=float(getattr(trend_cfg, "bear_short_gate_min_market_adx", 0.0)),
            enable_conditional_trend_long_guard=bool(
                getattr(trend_cfg, "enable_conditional_trend_long_guard", False)
            ),
            trend_long_guard_allowed_market_regimes=getattr(
                trend_cfg, "trend_long_guard_allowed_market_regimes", ("STRONG_TREND",)
            ),
            trend_long_guard_symbol_spread_atr_min=float(
                getattr(trend_cfg, "trend_long_guard_symbol_spread_atr_min", 0.0)
            ),
            trend_long_guard_market_spread_atr_min=float(
                getattr(trend_cfg, "trend_long_guard_market_spread_atr_min", 0.0)
            ),
            trend_long_guard_market_regime_streak_min=int(
                getattr(trend_cfg, "trend_long_guard_market_regime_streak_min", 0)
            ),
            trend_long_guard_market_adx_max=float(
                getattr(trend_cfg, "trend_long_guard_market_adx_max", 100.0)
            ),
            entry_block_only=False,
        ),
    )
    trend_risk = VolScaledRiskManager(trend_cfg) if trend_cfg.enable_vol_risk else RiskManager(trend_cfg)
    trend_portfolio = Portfolio(symbols=list(trend_cfg.symbols), initial_cash=trend_equity)
    trend_broker = PaperBroker(trend_cfg)
    trend_engine = Engine(trend_cfg, trend_strategy, trend_broker, trend_risk, trend_portfolio)

    # === MR ?붿쭊 ?ㅼ젙 ===
    mr_strategy = MRStrategy(mr_cfg)
    mr_risk = VolScaledRiskManager(mr_cfg) if mr_cfg.enable_vol_risk else RiskManager(mr_cfg)
    mr_portfolio = Portfolio(symbols=list(mr_cfg.symbols), initial_cash=mr_equity)
    mr_broker = PaperBroker(mr_cfg)
    mr_engine = MREngine(mr_cfg, mr_strategy, mr_broker, mr_risk, mr_portfolio)

    # === 諛깊뀒?ㅽ듃 猷⑦봽 ===
    mkt_on_count = 0
    mkt_total = 0
    mkt_regime_counts = Counter()

    for t in idx:
        t_py = t.to_pydatetime()

        # 1) funding apply (???ы듃?대━??紐⑤몢)
        for sym in trend_cfg.symbols:
            rate = funding_map[sym].get(t_py)
            if rate is not None:
                close_px = feature_dicts[sym][t].close
                trend_portfolio.update_close(sym, close_px)
                trend_portfolio.apply_funding(t_py, sym, rate)
                mr_portfolio.update_close(sym, close_px)
                mr_portfolio.apply_funding(t_py, sym, rate)

        # 2) 異붿꽭 ?붿쭊 market regime ?낅뜲?댄듃
        mkt = trend_cfg.market_symbol
        mkt_row = feature_dicts[mkt][t]   # O(1)
        trend_strategy.update_market(mkt_row, equity=trend_portfolio.equity)

        mkt_total += 1
        if trend_strategy.market_on:
            mkt_on_count += 1
        if trend_strategy.last_market_regime is not None:
            mkt_regime_counts[trend_strategy.last_market_regime] += 1

        # 3) ?щ낵蹂?on_bar (???붿쭊 ?낅┰ ?ㅽ뻾)
        for sym in trend_cfg.symbols:
            fr = funding_cursor[sym].advance_to(t_py)
            row = feature_dicts[sym][t]  # O(1)

            # 異붿꽭 ?붿쭊
            trend_engine.on_bar(row, funding_rate=fr)

            # MR ?붿쭊
            mr_engine.on_bar(row, funding_rate=fr)

        # 4) equity ?ㅻ깄??
        trend_engine.snapshot_curve(t_py)
        mr_engine.snapshot_curve(t_py)

        if progress_every > 0 and (len(trend_engine.curve_rows) % progress_every) == 0:
            ratio = (mkt_on_count / mkt_total) if mkt_total else float("nan")
            combined = trend_portfolio.equity + mr_portfolio.equity
            print(f"[DUAL] bars={len(trend_engine.curve_rows)} "
                  f"trend={trend_portfolio.equity:,.0f} "
                  f"mr={mr_portfolio.equity:,.0f} "
                  f"combined={combined:,.0f} "
                  f"mktON={ratio:.2%}")

    # === 寃곌낵 ?섏쭛 ===
    trend_res = trend_engine.result()
    mr_res    = mr_engine.result()

    # ?⑹궛 equity curve
    combined_eq = trend_res.equity_curve.copy()
    combined_eq["equity"] = (
        trend_res.equity_curve["equity"].values
        + mr_res.equity_curve["equity"].values
    )
    # drawdown ?ш퀎??
    peak = combined_eq["equity"].cummax()
    combined_eq["drawdown"] = combined_eq["equity"] / peak - 1.0

    # 紐⑤뱺 trades ?⑹궛
    all_trades = pd.concat([trend_res.trades, mr_res.trades], ignore_index=True)
    if not all_trades.empty:
        all_trades = all_trades.sort_values("time").reset_index(drop=True)

    # 硫뷀듃由?怨꾩궛
    benchmark_close = price[trend_cfg.market_symbol]["close"]
    trend_benchmark = build_benchmark_equity_curve(trend_res.equity_curve.index, benchmark_close, trend_equity)
    mr_benchmark = build_benchmark_equity_curve(mr_res.equity_curve.index, benchmark_close, mr_equity)
    combined_benchmark = build_benchmark_equity_curve(combined_eq.index, benchmark_close, INITIAL_EQUITY)

    trend_metrics = compute_metrics(
        trend_res.equity_curve,
        trend_res.trades,
        trend_equity,
        trend_cfg.interval,
        benchmark_curve=trend_benchmark,
    )
    mr_metrics = compute_metrics(
        mr_res.equity_curve,
        mr_res.trades,
        mr_equity,
        mr_cfg.interval,
        benchmark_curve=mr_benchmark,
    )
    combined_metrics = compute_metrics(
        combined_eq,
        all_trades,
        INITIAL_EQUITY,
        trend_cfg.interval,
        benchmark_curve=combined_benchmark,
    )

    # === 寃곌낵 ???===
    import os
    os.makedirs(outdir, exist_ok=True)

    tag = f"dual_BTCUSDT_ETHUSDT_4h_{trend_cfg.start}_{trend_cfg.end}_trend{int(TREND_RATIO*100)}_mr{int(MR_RATIO*100)}"

    save_artifacts = os.environ.get("QUANT_BT_SAVE_ARTIFACTS", "1").strip() != "0"
    if save_artifacts:
        trend_eq_path, trend_tr_path = save_csvs(trend_res.equity_curve, trend_res.trades, outdir, f"trend_{tag}")
        mr_eq_path, mr_tr_path = save_csvs(mr_res.equity_curve, mr_res.trades, outdir, f"mr_{tag}")
        comb_eq_path, comb_tr_path = save_csvs(combined_eq, all_trades, outdir, f"combined_{tag}")
    else:
        trend_eq_path = trend_tr_path = ""
        mr_eq_path = mr_tr_path = ""
        comb_eq_path = comb_tr_path = ""

    # === 異쒕젰 ===
    print("\n" + "="*60)
    print("  DUAL PORTFOLIO BACKTEST RESULTS")
    print("="*60)

    print(f"\n[TREND ENGINE] Initial: ${trend_equity:,.0f} ({int(TREND_RATIO*100)}%)")
    trend_final = trend_res.equity_curve["equity"].iloc[-1] if not trend_res.equity_curve.empty else trend_equity
    print(f"  Final equity : ${trend_final:,.2f}")
    for k, v in trend_metrics.items():
        print(f"  {k:18s}: {v:.4f}" if isinstance(v, float) else f"  {k:18s}: {v}")

    print(f"\n[MR ENGINE] Initial: ${mr_equity:,.0f} ({int(MR_RATIO*100)}%)")
    mr_final = mr_res.equity_curve["equity"].iloc[-1] if not mr_res.equity_curve.empty else mr_equity
    print(f"  Final equity : ${mr_final:,.2f}")
    for k, v in mr_metrics.items():
        print(f"  {k:18s}: {v:.4f}" if isinstance(v, float) else f"  {k:18s}: {v}")

    print(f"\n[COMBINED] Initial: ${INITIAL_EQUITY:,.0f}")
    combined_final = trend_final + mr_final
    print(f"  Final equity : ${combined_final:,.2f}")
    print(f"  (Trend: ${trend_final:,.2f} + MR: ${mr_final:,.2f})")
    for k, v in combined_metrics.items():
        print(f"  {k:18s}: {v:.4f}" if isinstance(v, float) else f"  {k:18s}: {v}")

    mkt_on_ratio = mkt_on_count / mkt_total if mkt_total else 0.0
    print(f"\n  Trend mktON  : {mkt_on_ratio:.2%}")
    print(f"  BTC regimes  : {dict(mkt_regime_counts)}")

    if save_artifacts:
        print("\nSaved:")
        print(f"  Trend  : {trend_eq_path}")
        print(f"           {trend_tr_path}")
        print(f"  MR     : {mr_eq_path}")
        print(f"           {mr_tr_path}")
        print(f"  Combined: {comb_eq_path}")
        print(f"            {comb_tr_path}")

    return {
        "trend": {"equity_curve": trend_res.equity_curve, "trades": trend_res.trades, "metrics": trend_metrics},
        "mr":    {"equity_curve": mr_res.equity_curve,    "trades": mr_res.trades,    "metrics": mr_metrics},
        "combined": {"equity_curve": combined_eq,          "trades": all_trades,       "metrics": combined_metrics},
        "combined_final_equity": combined_final,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("quant-backtest")
    p.add_argument("--outdir", default="result")
    p.add_argument("--interval", default=None, help="override cfg.interval (e.g. 1m, 4h)")
    p.add_argument("--start", default=None, help="override cfg.start (YYYY-MM-DD)")
    p.add_argument("--end", default=None, help="override cfg.end (YYYY-MM-DD)")
    p.add_argument("--dual", action="store_true", help="run dual portfolio backtest (Method 1)")
    p.add_argument("--stop-atr-mult-trend", type=float, default=None, help="override stop_atr_mult_trend")
    p.add_argument("--stop-atr-mult-vol", type=float, default=None, help="override stop_atr_mult_vol")
    p.add_argument("--trail-atr-mult", type=float, default=None, help="override trail_atr_mult")
    p.add_argument("--vol-break-near-atr-mult", type=float, default=None, help="override vol_break_near_atr_mult")
    p.add_argument("--vol-breakout-strict", choices=["true", "false"], default=None, help="override vol_breakout_strict")
    args = p.parse_args(argv)

    if args.dual:
        outdir = args.outdir if args.outdir != "result" else "result_dual"
        run_dual_backtest(outdir=outdir)
        return 0

    cfg = preset_regime_only_live()
    if args.interval:
        cfg.interval = args.interval
    if args.start:
        cfg.start = args.start
    if args.end:
        cfg.end = args.end
    if args.stop_atr_mult_trend is not None:
        cfg.stop_atr_mult_trend = args.stop_atr_mult_trend
    if args.stop_atr_mult_vol is not None:
        cfg.stop_atr_mult_vol = args.stop_atr_mult_vol
    if args.trail_atr_mult is not None:
        cfg.trail_atr_mult = args.trail_atr_mult
    if args.vol_break_near_atr_mult is not None:
        cfg.vol_break_near_atr_mult = args.vol_break_near_atr_mult
    if args.vol_breakout_strict is not None:
        cfg.vol_breakout_strict = (args.vol_breakout_strict.lower() == "true")
    run_backtest(cfg, outdir=args.outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
