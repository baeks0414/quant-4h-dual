#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_SAVE_ARTIFACTS", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from quant.config.presets import (
    PortfolioBTConfig,
    preset_balanced_alpha_sleeve_aggressive,
    preset_dynamic_bear_state_trend,
)
from quant.core.engine import Engine
from quant.core.metrics import build_benchmark_equity_curve, compute_metrics
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.data.binance_fetch import fetch_funding_rates, fetch_klines
from quant.data.features import adx, atr, df_to_feature_dict, intersect_timeline
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy


OUTDIR = ROOT / "results" / "final" / "result_compare_ma_kernel_variants_20260308"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
ALPHA_WEIGHT = 0.30


@dataclass(frozen=True)
class MAVariant:
    name: str
    fast_mode: str
    slow_mode: str


@dataclass(frozen=True)
class Case:
    name: str
    start: str
    end: str
    symbols: tuple[str, ...]
    market_symbol: str


def moving_average(s: pd.Series, n: int, mode: str) -> pd.Series:
    if mode == "ema":
        return s.ewm(span=n, adjust=False).mean()
    if mode == "sma":
        return s.rolling(n).mean()
    raise ValueError(f"Unsupported MA mode: {mode}")


def add_features_variant(df: pd.DataFrame, cfg: PortfolioBTConfig, fast_mode: str, slow_mode: str) -> pd.DataFrame:
    df = df.copy()
    df["ema_fast"] = moving_average(df["close"], cfg.ema_fast, fast_mode)
    df["ema_slow"] = moving_average(df["close"], cfg.ema_slow, slow_mode)
    df["atr14"] = atr(df, 14)
    df["atr30"] = atr(df, 30)
    df["adx14"] = adx(df, 14)
    df["ema_fast_slope_3"] = (df["ema_fast"] - df["ema_fast"].shift(3)) / df["atr14"].replace(0.0, np.nan)
    df["adx_slope_3"] = df["adx14"] - df["adx14"].shift(3)

    w = cfg.donchian_window
    df["donchian_hh"] = df["high"].shift(1).rolling(w).max()
    df["donchian_ll"] = df["low"].shift(1).rolling(w).min()

    mr_w = int(getattr(cfg, "mr_window", 50))
    df["mr_mean"] = df["close"].rolling(mr_w).mean()
    df["mr_std"] = df["close"].rolling(mr_w).std(ddof=0)

    bb_w = int(getattr(cfg, "mr_bb_window", 14))
    df["bb_mean"] = df["close"].rolling(bb_w).mean()
    df["bb_std"] = df["close"].rolling(bb_w).std(ddof=0)

    adx14 = df["adx14"].values
    atr14 = df["atr14"].values
    atr30 = df["atr30"].values
    ema_f = df["ema_fast"].values
    ema_s = df["ema_slow"].values

    no_data = np.isnan(adx14) | np.isnan(atr14) | np.isnan(atr30)
    strong_trend_bull = (~no_data) & (adx14 >= cfg.adx_trend) & (ema_f > ema_s)
    strong_trend_bear = (~no_data) & (adx14 >= cfg.adx_trend) & (ema_f <= ema_s)
    strong_trend = strong_trend_bull | strong_trend_bear
    vol_expand = (~no_data) & ~strong_trend & ((atr14 / np.where(atr30 == 0, np.nan, atr30)) >= cfg.atr_expand_ratio)

    use_bear = bool(getattr(cfg, "enable_bear_regime", False))
    if use_bear:
        regime_arr = np.where(
            no_data,
            "NO_DATA",
            np.where(
                strong_trend_bull,
                "STRONG_TREND",
                np.where(strong_trend_bear, "STRONG_TREND_BEAR", np.where(vol_expand, "VOL_EXPAND", "CHOP")),
            ),
        )
    else:
        vol_expand_orig = (~no_data) & ~strong_trend_bull & (
            (atr14 / np.where(atr30 == 0, np.nan, atr30)) >= cfg.atr_expand_ratio
        )
        regime_arr = np.where(
            no_data,
            "NO_DATA",
            np.where(strong_trend_bull, "STRONG_TREND", np.where(vol_expand_orig, "VOL_EXPAND", "CHOP")),
        )
    df["regime"] = regime_arr
    return df


def build_strategy(cfg: PortfolioBTConfig):
    base = YourStrategy(cfg)
    if getattr(cfg, "enable_regime_gate", False):
        return MarketRegimeGate(
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
                state_gate_min_market_ema_spread_atr=float(
                    getattr(cfg, "state_gate_min_market_ema_spread_atr", 0.0)
                ),
                state_gate_min_market_regime_streak=int(getattr(cfg, "state_gate_min_market_regime_streak", 1)),
                state_gate_max_market_regime_streak=int(
                    getattr(cfg, "state_gate_max_market_regime_streak", 10_000)
                ),
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
                entry_block_only=False,
            ),
        )
    return base


def build_risk(cfg: PortfolioBTConfig):
    return VolScaledRiskManager(cfg) if getattr(cfg, "enable_vol_risk", False) else RiskManager(cfg)


def run_custom_backtest(cfg: PortfolioBTConfig, variant: MAVariant) -> dict[str, object]:
    start_ms = int(pd.Timestamp(cfg.start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(cfg.end, tz="UTC").timestamp() * 1000)

    price: dict[str, pd.DataFrame] = {}
    funding: dict[str, pd.DataFrame] = {}
    for sym in cfg.symbols:
        df = fetch_klines(sym, cfg.interval, start_ms, end_ms)
        price[sym] = add_features_variant(df, cfg, variant.fast_mode, variant.slow_mode)
        funding[sym] = fetch_funding_rates(sym, start_ms, end_ms)

    funding_map: dict[str, dict] = {}
    for sym in cfg.symbols:
        fmap = {}
        fdf = funding[sym]
        if not fdf.empty:
            for t, r in fdf["fundingRate"].items():
                fmap[pd.Timestamp(t).to_pydatetime()] = float(r)
        funding_map[sym] = fmap

    idx = intersect_timeline(price, cfg.symbols)
    feature_dicts = {sym: df_to_feature_dict(sym, price[sym]) for sym in cfg.symbols}

    sorted_funding = {}
    for sym, fdf in funding.items():
        if fdf.empty:
            sorted_funding[sym] = ([], [])
        else:
            sorted_funding[sym] = ([t.to_pydatetime() for t in fdf.index], fdf["fundingRate"].tolist())

    strategy = build_strategy(cfg)
    risk = build_risk(cfg)
    portfolio = Portfolio(symbols=list(cfg.symbols), initial_cash=cfg.initial_equity)
    broker = PaperBroker(cfg)
    engine = Engine(cfg, strategy, broker, risk, portfolio)

    funding_cursor = {
        sym: _FundingCursor(sorted_funding[sym][0], sorted_funding[sym][1]) for sym in cfg.symbols
    }

    for t in idx:
        t_py = t.to_pydatetime()

        for sym in cfg.symbols:
            rate = funding_map[sym].get(t_py)
            if rate is not None:
                close_px = feature_dicts[sym][t].close
                portfolio.update_close(sym, close_px)
                portfolio.apply_funding(t_py, sym, rate)

        if getattr(cfg, "enable_regime_gate", False):
            mkt_row = feature_dicts[cfg.market_symbol][t]
            strategy.update_market(mkt_row, equity=portfolio.equity)

        for sym in cfg.symbols:
            fr = funding_cursor[sym].advance_to(t_py)
            row = feature_dicts[sym][t]
            engine.on_bar(row, funding_rate=fr)

        engine.snapshot_curve(t_py)

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
    return {
        "equity_curve": res.equity_curve,
        "trades": res.trades,
        "metrics": metrics,
        "benchmark_equity_curve": benchmark_curve,
    }


class _FundingCursor:
    def __init__(self, ts_list: list, rate_list: list):
        self.ts_list = ts_list
        self.rate_list = rate_list
        self.idx = -1
        self.current = None

    def advance_to(self, t_py):
        i = self.idx
        n = len(self.ts_list)
        while (i + 1) < n and self.ts_list[i + 1] <= t_py:
            i += 1
            self.current = float(self.rate_list[i])
        self.idx = i
        return self.current


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def run_combo(case: Case, variant: MAVariant) -> dict[str, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = case.start
    trend_cfg.end = case.end
    trend_cfg.symbols = case.symbols
    trend_cfg.market_symbol = case.market_symbol
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    trend = run_custom_backtest(trend_cfg, variant)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.start = case.start
    alpha_cfg.end = case.end
    alpha_cfg.symbols = case.symbols
    alpha_cfg.market_symbol = case.market_symbol
    alpha_cfg.initial_equity = INITIAL_EQUITY * ALPHA_WEIGHT
    alpha = run_custom_backtest(alpha_cfg, variant)

    trend_ec = trend["equity_curve"][["equity"]].copy()
    alpha_ec = alpha["equity_curve"][["equity"]].copy()
    trend_ec.index = pd.to_datetime(trend_ec.index, utc=True)
    alpha_ec.index = pd.to_datetime(alpha_ec.index, utc=True)

    idx = trend_ec.index.intersection(alpha_ec.index)
    combined = pd.DataFrame(index=idx)
    combined["equity"] = trend_ec.loc[idx, "equity"] + alpha_ec.loc[idx, "equity"]
    peak = combined["equity"].cummax()
    combined["drawdown"] = combined["equity"] / peak - 1.0

    trades = pd.concat([trend["trades"], alpha["trades"]], ignore_index=True)
    if not trades.empty and "time" in trades.columns:
        trades = trades.sort_values("time").reset_index(drop=True)

    benchmark_curve = trend["benchmark_equity_curve"][["equity"]].copy()
    benchmark_curve.index = pd.to_datetime(benchmark_curve.index, utc=True)
    benchmark_curve["equity"] = benchmark_curve["equity"] / (INITIAL_EQUITY * TREND_WEIGHT) * INITIAL_EQUITY
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    return {"metrics": metrics, "yearly": yearly_returns(combined)}


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    variants = [
        MAVariant("ema_ema", "ema", "ema"),
        MAVariant("sma_sma", "sma", "sma"),
        MAVariant("ema_sma", "ema", "sma"),
        MAVariant("sma_ema", "sma", "ema"),
    ]
    cases = [
        Case("full_btc_eth", "2022-01-01", "2026-03-08", ("BTCUSDT", "ETHUSDT"), "BTCUSDT"),
        Case("train_btc_eth", "2022-01-01", "2026-01-01", ("BTCUSDT", "ETHUSDT"), "BTCUSDT"),
        Case("test2026_btc_eth", "2026-01-01", "2026-03-08", ("BTCUSDT", "ETHUSDT"), "BTCUSDT"),
        Case("full_btc_only", "2022-01-01", "2026-03-08", ("BTCUSDT",), "BTCUSDT"),
        Case("full_eth_only", "2022-01-01", "2026-03-08", ("ETHUSDT",), "ETHUSDT"),
    ]

    rows: list[dict[str, object]] = []
    for case in cases:
        baseline_metrics = None
        for variant in variants:
            result = run_combo(case, variant)
            metrics = result["metrics"]
            row = {
                "case": case.name,
                "variant": variant.name,
                "fast_mode": variant.fast_mode,
                "slow_mode": variant.slow_mode,
                "total_return": float(metrics["total_return"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "sharpe": float(metrics["sharpe"]),
                "excess_return": float(metrics.get("excess_return", float("nan"))),
                "information_ratio": float(metrics.get("information_ratio", float("nan"))),
                "alpha_annualized": float(metrics.get("alpha_annualized", float("nan"))),
                "final_equity": float(metrics["final_equity"]),
            }
            for year, value in result["yearly"].items():
                row[f"y{year}"] = float(value)
            if variant.name == "ema_ema":
                baseline_metrics = metrics
                row["delta_ret_vs_ema"] = 0.0
                row["delta_mdd_vs_ema"] = 0.0
                row["delta_sharpe_vs_ema"] = 0.0
            else:
                assert baseline_metrics is not None
                row["delta_ret_vs_ema"] = float(metrics["total_return"]) - float(baseline_metrics["total_return"])
                row["delta_mdd_vs_ema"] = float(metrics["max_drawdown"]) - float(baseline_metrics["max_drawdown"])
                row["delta_sharpe_vs_ema"] = float(metrics["sharpe"]) - float(baseline_metrics["sharpe"])
            rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(OUTDIR / "summary.csv", index=False)

    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
