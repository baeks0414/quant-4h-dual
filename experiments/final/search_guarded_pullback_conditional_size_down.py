#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
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
from quant.data.models import FeatureRow
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy


OUTDIR = ROOT / "results" / "final" / "result_search_guarded_pullback_conditional_size_down_20260308"
TRAIN_START = "2022-01-01"
TRAIN_END = "2026-01-01"
TEST_START = "2026-01-01"
TEST_END = "2026-03-08"
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT = 0.70
ALPHA_WEIGHT = 0.30


@dataclass(frozen=True)
class ConditionalSizeSpec:
    name: str
    stale_streak_min: int | None = None
    symbol_spread_min: float | None = None
    conditional_size_scale: float = 0.5


@contextlib.contextmanager
def silence_stdout():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield


class ConditionalGuardedPullbackSizeGate(MarketRegimeGate):
    def __init__(self, base, cfg: MarketRegimeGateConfig, spec: ConditionalSizeSpec):
        super().__init__(base, cfg)
        self.spec = spec

    def _conditional_size_scale(self, row: FeatureRow) -> float | None:
        atr_v = float(getattr(row, "atr14", float("nan")))
        if not pd.notna(atr_v) or atr_v <= 0.0:
            return None
        spread_atr = abs(float(row.ema_fast) - float(row.ema_slow)) / atr_v

        checks: list[bool] = []
        if self.spec.stale_streak_min is not None:
            checks.append(int(self.last_market_regime_streak) >= int(self.spec.stale_streak_min))
        if self.spec.symbol_spread_min is not None:
            checks.append(float(spread_atr) >= float(self.spec.symbol_spread_min))
        if not checks or not all(checks):
            return None
        return float(self.spec.conditional_size_scale)

    def _guarded_pullback_signal(self, row: FeatureRow):
        sig = super()._guarded_pullback_signal(row)
        if sig is None:
            return None
        note = str(getattr(sig, "note", ""))
        if "guarded trend pullback long" not in note:
            return sig

        scale = self._conditional_size_scale(row)
        if scale is None:
            return sig

        base_scale = float(getattr(self.base.cfg, "trend_long_guard_size_down_scale", 1.0))
        if scale >= base_scale - 1e-9:
            return sig

        marker = "guard_size_down="
        if marker in note:
            prefix, rest = note.split(marker, 1)
            suffix = ""
            if "|" in rest:
                _, suffix = rest.split("|", 1)
                suffix = "|" + suffix
            note = f"{prefix}{marker}{scale:.3f}{suffix}"
        else:
            note = f"{note}|guard_size_down={scale:.3f}"
        return sig.__class__(sig.symbol, sig.action, sig.stop_price, note)


def build_trend_strategy(cfg: PortfolioBTConfig, spec: ConditionalSizeSpec | None):
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
        enable_conditional_trend_long_guard=bool(getattr(cfg, "enable_conditional_trend_long_guard", False)),
        trend_long_guard_allowed_market_regimes=getattr(
            cfg, "trend_long_guard_allowed_market_regimes", ("STRONG_TREND",)
        ),
        trend_long_guard_symbol_spread_atr_min=float(getattr(cfg, "trend_long_guard_symbol_spread_atr_min", 0.0)),
        trend_long_guard_market_spread_atr_min=float(getattr(cfg, "trend_long_guard_market_spread_atr_min", 0.0)),
        trend_long_guard_market_regime_streak_min=int(getattr(cfg, "trend_long_guard_market_regime_streak_min", 0)),
        trend_long_guard_market_adx_max=float(getattr(cfg, "trend_long_guard_market_adx_max", 100.0)),
        entry_block_only=False,
    )
    if spec is None:
        return MarketRegimeGate(base, gate_cfg)
    return ConditionalGuardedPullbackSizeGate(base, gate_cfg, spec)


def run_custom_trend_backtest(cfg: PortfolioBTConfig, spec: ConditionalSizeSpec | None) -> dict:
    price, _, funding_map, idx, feature_dicts, sorted_funding = _build_price_funding(cfg)
    strategy = build_trend_strategy(cfg, spec)
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


def yearly_returns(ec: pd.DataFrame) -> dict[int, float]:
    view = ec.copy()
    view.index = pd.to_datetime(view.index, utc=True)
    out: dict[int, float] = {}
    for year in sorted(set(view.index.year)):
        sample = view[view.index.year == year]
        if not sample.empty:
            out[year] = float(sample["equity"].iloc[-1] / sample["equity"].iloc[0] - 1.0)
    return out


def count_guarded_scales(trades: pd.DataFrame) -> tuple[int, int]:
    if trades.empty:
        return 0, 0
    entry_mask = trades["type"].astype(str).isin(("ENTRY_LONG", "PYRAMID_LONG"))
    notes = trades.loc[entry_mask, "note"].astype(str)
    guarded = notes.str.contains("guarded trend pullback long", regex=False)
    stronger = notes.str.contains("guard_size_down=0.350", regex=False) | notes.str.contains(
        "guard_size_down=0.400", regex=False
    ) | notes.str.contains("guard_size_down=0.450", regex=False)
    return int(guarded.sum()), int((guarded & stronger).sum())


def run_combo(spec: ConditionalSizeSpec | None, start: str, end: str) -> dict[str, object]:
    trend_cfg = preset_dynamic_bear_state_trend()
    trend_cfg.start = start
    trend_cfg.end = end
    trend_cfg.initial_equity = INITIAL_EQUITY * TREND_WEIGHT
    trend = run_custom_trend_backtest(trend_cfg, spec)

    alpha_cfg = preset_balanced_alpha_sleeve_aggressive()
    alpha_cfg.start = start
    alpha_cfg.end = end
    alpha_cfg.initial_equity = INITIAL_EQUITY * ALPHA_WEIGHT
    with silence_stdout():
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
    benchmark_curve["equity"] = benchmark_curve["equity"] / (INITIAL_EQUITY * TREND_WEIGHT) * INITIAL_EQUITY
    benchmark_curve = benchmark_curve.loc[idx]
    peak_b = benchmark_curve["equity"].cummax()
    benchmark_curve["drawdown"] = benchmark_curve["equity"] / peak_b - 1.0

    combo_metrics = compute_metrics(combined, trades, INITIAL_EQUITY, "4h", benchmark_curve=benchmark_curve)
    guarded_total, guarded_stronger = count_guarded_scales(trend["trades"])
    return {
        "metrics": combo_metrics,
        "yearly": yearly_returns(combined),
        "guarded_total_entries": guarded_total,
        "guarded_stronger_entries": guarded_stronger,
    }


def build_specs() -> list[ConditionalSizeSpec | None]:
    specs: list[ConditionalSizeSpec | None] = [None]
    for streak in (20, 25, 30, 35):
        for spread in (1.0, 1.2, 1.4):
            for scale in (0.35, 0.40, 0.45):
                specs.append(
                    ConditionalSizeSpec(
                        name=f"st{streak}_spr{str(spread).replace('.', 'p')}_sz{str(scale).replace('.', 'p')}",
                        stale_streak_min=streak,
                        symbol_spread_min=spread,
                        conditional_size_scale=scale,
                    )
                )
    return specs


def main() -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    baseline_train: dict[str, object] | None = None
    baseline_test: dict[str, object] | None = None

    for spec in build_specs():
        label = "baseline" if spec is None else spec.name
        train = run_combo(spec, TRAIN_START, TRAIN_END)
        test = run_combo(spec, TEST_START, TEST_END)

        if spec is None:
            baseline_train = train
            baseline_test = test

        assert baseline_train is not None
        assert baseline_test is not None

        train_metrics = train["metrics"]
        test_metrics = test["metrics"]

        rows.append(
            {
                "candidate": label,
                "stale_streak_min": None if spec is None else spec.stale_streak_min,
                "symbol_spread_min": None if spec is None else spec.symbol_spread_min,
                "conditional_size_scale": None if spec is None else spec.conditional_size_scale,
                "train_total_return": float(train_metrics["total_return"]),
                "train_max_drawdown": float(train_metrics["max_drawdown"]),
                "train_sharpe": float(train_metrics["sharpe"]),
                "train_excess_return": float(train_metrics.get("excess_return", float("nan"))),
                "train_information_ratio": float(train_metrics.get("information_ratio", float("nan"))),
                "train_y2022": float(train["yearly"].get(2022, float("nan"))),
                "train_y2023": float(train["yearly"].get(2023, float("nan"))),
                "train_y2024": float(train["yearly"].get(2024, float("nan"))),
                "train_y2025": float(train["yearly"].get(2025, float("nan"))),
                "train_guarded_total_entries": int(train["guarded_total_entries"]),
                "train_guarded_stronger_entries": int(train["guarded_stronger_entries"]),
                "test_total_return": float(test_metrics["total_return"]),
                "test_max_drawdown": float(test_metrics["max_drawdown"]),
                "test_sharpe": float(test_metrics["sharpe"]),
                "test_excess_return": float(test_metrics.get("excess_return", float("nan"))),
                "test_information_ratio": float(test_metrics.get("information_ratio", float("nan"))),
                "test_y2026": float(test["yearly"].get(2026, float("nan"))),
                "test_guarded_total_entries": int(test["guarded_total_entries"]),
                "test_guarded_stronger_entries": int(test["guarded_stronger_entries"]),
                "delta_train_total_return": float(train_metrics["total_return"]) - float(baseline_train["metrics"]["total_return"]),
                "delta_train_max_drawdown": float(train_metrics["max_drawdown"]) - float(baseline_train["metrics"]["max_drawdown"]),
                "delta_train_sharpe": float(train_metrics["sharpe"]) - float(baseline_train["metrics"]["sharpe"]),
                "delta_test_total_return": float(test_metrics["total_return"]) - float(baseline_test["metrics"]["total_return"]),
                "delta_test_max_drawdown": float(test_metrics["max_drawdown"]) - float(baseline_test["metrics"]["max_drawdown"]),
                "delta_test_sharpe": float(test_metrics["sharpe"]) - float(baseline_test["metrics"]["sharpe"]),
            }
        )

    df = pd.DataFrame(rows).sort_values(
        by=["delta_train_sharpe", "delta_train_total_return", "delta_test_sharpe"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    df.to_csv(OUTDIR / "candidate_summary.csv", index=False)
    print(df.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
