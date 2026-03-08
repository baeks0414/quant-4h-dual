#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QUANT_BT_PROGRESS_EVERY", "0")
os.environ.setdefault("QUANT_BT_SAVE_ARTIFACTS", "0")
os.environ.setdefault("QUANT_BT_USE_MEM_CACHE", "1")

from quant.cli.backtest import _FundingCursor, _build_price_funding, run_backtest
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
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy


OUTDIR = ROOT / "results" / "final" / "result_search_train_only_conditional_trend_long_guards_20260308"
TRAIN_START = "2022-01-01"
TRAIN_END = "2026-01-01"


@dataclass(frozen=True)
class TrendLongGuardSpec:
    name: str
    symbol_spread_min: float | None = None
    market_spread_min: float | None = None
    market_regime_streak_min: int | None = None
    market_adx_max: float | None = None
    allowed_market_regimes: tuple[str, ...] = ("STRONG_TREND",)


class ConditionalTrendLongGuard(MarketRegimeGate):
    def __init__(self, base, cfg: MarketRegimeGateConfig, guard: TrendLongGuardSpec):
        super().__init__(base, cfg)
        self.guard = guard

    def _should_block_direct_trend_long(self, row) -> bool:
        if self.guard.allowed_market_regimes and self.last_market_regime not in set(self.guard.allowed_market_regimes):
            return False

        atr = float(getattr(row, "atr14", float("nan")))
        if not pd.notna(atr) or atr <= 0.0:
            return False
        symbol_spread = abs(float(row.ema_fast) - float(row.ema_slow)) / atr

        checks: list[bool] = []
        if self.guard.symbol_spread_min is not None:
            checks.append(symbol_spread >= float(self.guard.symbol_spread_min))
        if self.guard.market_spread_min is not None:
            if self.last_market_ema_spread_atr is None:
                return False
            checks.append(float(self.last_market_ema_spread_atr) >= float(self.guard.market_spread_min))
        if self.guard.market_regime_streak_min is not None:
            checks.append(int(self.last_market_regime_streak) >= int(self.guard.market_regime_streak_min))
        if self.guard.market_adx_max is not None:
            if self.last_market_adx is None:
                return False
            checks.append(float(self.last_market_adx) <= float(self.guard.market_adx_max))
        return bool(checks) and all(checks)

    def on_bar(self, row, funding_rate=None):
        sig = super().on_bar(row, funding_rate)
        if sig is None:
            return None
        if sig.action == "LONG" and str(getattr(sig, "note", "")) == "trend long":
            if self._should_block_direct_trend_long(row):
                return sig.__class__(
                    row.symbol,
                    "HOLD",
                    None,
                    (
                        "train_only_cond_guard("
                        f"mkt={self.last_market_regime}|"
                        f"adx={self.last_market_adx}|"
                        f"spread={self.last_market_ema_spread_atr}|"
                        f"streak={self.last_market_regime_streak})"
                    ),
                )
        return sig


def build_trend_strategy(cfg: PortfolioBTConfig, guard: TrendLongGuardSpec | None):
    base = YourStrategy(cfg)
    gate_cfg = MarketRegimeGateConfig(
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
        entry_block_only=False,
    )
    if guard is None:
        return MarketRegimeGate(base, gate_cfg)
    return ConditionalTrendLongGuard(base, gate_cfg, guard)


def run_custom_trend_backtest(cfg: PortfolioBTConfig, guard: TrendLongGuardSpec | None) -> dict:
    price, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(cfg)
    strategy = build_trend_strategy(cfg, guard)
    risk = VolScaledRiskManager(cfg) if getattr(cfg, "enable_vol_risk", False) else RiskManager(cfg)
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
            mkt = cfg.market_symbol
            mkt_row = feature_dicts[mkt][t]
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


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def run_combo(guard: TrendLongGuardSpec | None) -> dict:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = TRAIN_START
    trend_cfg.end = TRAIN_END
    trend_cfg.initial_equity = 7_000.0
    trend = run_custom_trend_backtest(trend_cfg, guard)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.start = TRAIN_START
    alpha_cfg.end = TRAIN_END
    alpha_cfg.initial_equity = 3_000.0
    alpha = run_backtest(alpha_cfg, outdir=str(OUTDIR / "tmp_alpha"))

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
    benchmark_curve["equity"] = benchmark_curve["equity"] / trend_cfg.initial_equity * 10_000.0
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    combo_metrics = compute_metrics(combined, trades, 10_000.0, "4h", benchmark_curve=benchmark_curve)
    combo_yearly = yearly_returns(combined)
    return {
        "combo_metrics": combo_metrics,
        "combo_yearly": combo_yearly,
        "trend_metrics": trend["metrics"],
        "trend_yearly": yearly_returns(trend["equity_curve"]),
    }


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    candidates = [
        None,
        TrendLongGuardSpec("sym0p8_st7", symbol_spread_min=0.8, market_regime_streak_min=7),
        TrendLongGuardSpec("sym0p8_st10", symbol_spread_min=0.8, market_regime_streak_min=10),
        TrendLongGuardSpec("sym1p0_st10", symbol_spread_min=1.0, market_regime_streak_min=10),
        TrendLongGuardSpec("sym1p2_st10", symbol_spread_min=1.2, market_regime_streak_min=10),
        TrendLongGuardSpec("mkt0p9_st7", market_spread_min=0.9, market_regime_streak_min=7),
        TrendLongGuardSpec("mkt0p9_st10", market_spread_min=0.9, market_regime_streak_min=10),
        TrendLongGuardSpec("mkt1p1_st10", market_spread_min=1.1, market_regime_streak_min=10),
        TrendLongGuardSpec("sym0p8_st7_adx40", symbol_spread_min=0.8, market_regime_streak_min=7, market_adx_max=40.0),
        TrendLongGuardSpec("sym0p8_st10_adx40", symbol_spread_min=0.8, market_regime_streak_min=10, market_adx_max=40.0),
        TrendLongGuardSpec("sym1p0_st10_adx40", symbol_spread_min=1.0, market_regime_streak_min=10, market_adx_max=40.0),
        TrendLongGuardSpec("sym0p8_mkt0p9", symbol_spread_min=0.8, market_spread_min=0.9),
        TrendLongGuardSpec("sym1p0_mkt1p0", symbol_spread_min=1.0, market_spread_min=1.0),
    ]

    rows: list[dict] = []
    for guard in candidates:
        name = "baseline" if guard is None else guard.name
        result = run_combo(guard)
        combo = result["combo_metrics"]
        trend = result["trend_metrics"]
        yearly = result["combo_yearly"]
        row = {
            "candidate": name,
            "combo_total_return": float(combo.get("total_return", 0.0)),
            "combo_max_drawdown": float(combo.get("max_drawdown", 0.0)),
            "combo_sharpe": float(combo.get("sharpe", 0.0)),
            "combo_excess_return": float(combo.get("excess_return", 0.0)),
            "combo_alpha_annualized": float(combo.get("alpha_annualized", 0.0)),
            "trend_total_return": float(trend.get("total_return", 0.0)),
            "trend_max_drawdown": float(trend.get("max_drawdown", 0.0)),
            "trend_sharpe": float(trend.get("sharpe", 0.0)),
        }
        for year in (2022, 2023, 2024, 2025):
            row[f"combo_y{year}"] = float(yearly.get(year, 0.0))
        if guard is not None:
            row.update(
                {
                    "symbol_spread_min": guard.symbol_spread_min,
                    "market_spread_min": guard.market_spread_min,
                    "market_regime_streak_min": guard.market_regime_streak_min,
                    "market_adx_max": guard.market_adx_max,
                }
            )
        rows.append(row)
        print(
            f"{name:18s} "
            f"ret={row['combo_total_return']:+.4%} "
            f"mdd={row['combo_max_drawdown']:+.4%} "
            f"sharpe={row['combo_sharpe']:.3f}"
        )

    df = pd.DataFrame(rows).sort_values(
        ["combo_total_return", "combo_sharpe", "combo_max_drawdown"],
        ascending=[False, False, False],
    )
    df.to_csv(OUTDIR / "candidate_summary.csv", index=False)

    baseline = df.loc[df["candidate"] == "baseline"].iloc[0]
    improved = df[
        (df["candidate"] != "baseline")
        & (df["combo_total_return"] > baseline["combo_total_return"])
        & (df["combo_sharpe"] >= baseline["combo_sharpe"])
        & (df["combo_max_drawdown"] >= baseline["combo_max_drawdown"])
    ].copy()

    print("\nBASELINE")
    print(baseline.to_string())
    print("\nSTRICTLY_IMPROVED")
    if improved.empty:
        print("NONE")
    else:
        print(improved.to_string(index=False))


if __name__ == "__main__":
    main()
