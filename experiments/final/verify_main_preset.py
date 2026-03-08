"""
main 브랜치 preset_regime_only_live 파라미터 재현 검증
main 브랜치 코드에서 복사한 파라미터로 현재 엔진에서 실행
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"

from quant.config.presets import PortfolioBTConfig
from quant.cli.backtest import run_backtest


def preset_main_branch() -> PortfolioBTConfig:
    """
    main 브랜치의 preset_regime_only_live() 파라미터 그대로 재현
    (main 브랜치 코드: $96,482, Sharpe 1.942, MDD -19.90%)
    """
    return PortfolioBTConfig(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval="4h",
        start="2022-01-01",
        end="2025-04-12",
        initial_equity=10000.0,
        risk_per_trade=0.012,
        portfolio_risk_cap=0.03,
        max_leverage=5.0,
        fee_rate=0.0005,
        slippage=0.0003,
        enable_regime_gate=True,
        market_symbol="BTCUSDT",
        allow_regimes=("STRONG_TREND", "VOL_EXPAND"),
        enable_vol_risk=True,
        target_stop_pct=0.020,
        trend_min_ema_spread_atr=0.05,
        trend_entry_buffer_atr=0.0,
        enable_pyramiding=True,
        pyramid_max_adds=2,
        pyramid_min_profit_atr=1.2,
        pyramid_risk_scale=0.5,
        pyramid_min_adx=0.0,
        pyramid_min_ema_slope=0.0,
        pyramid_cooldown_bars=0,
        flip_cooldown_bars=3,
    )


def main():
    print("=" * 60)
    print("main 브랜치 preset 검증 (현재 엔진으로 실행)")
    print("=" * 60)

    cfg = preset_main_branch()
    print(f"\n파라미터:")
    print(f"  risk_per_trade     : {cfg.risk_per_trade}")
    print(f"  portfolio_risk_cap : {cfg.portfolio_risk_cap}")
    print(f"  enable_vol_risk    : {cfg.enable_vol_risk}")
    print(f"  target_stop_pct    : {cfg.target_stop_pct}")
    print(f"  trend_min_ema_spread_atr: {cfg.trend_min_ema_spread_atr}")
    print(f"  enable_pyramiding  : {cfg.enable_pyramiding}")
    print(f"  pyramid_min_profit_atr: {cfg.pyramid_min_profit_atr}")
    print(f"  flip_cooldown_bars : {cfg.flip_cooldown_bars}")
    print(f"  allow_regimes      : {cfg.allow_regimes}")

    res = run_backtest(cfg, outdir=str(ROOT / "results" / "final" / "result_verify_main_preset"))
    m = res["metrics"]

    print("\n===== 결과 =====")
    print(f"  총수익률  : {m.get('total_return', 0):.4f}x  ({m.get('total_return', 0)*100:.1f}%)")
    print(f"  BTC벤치마크: {m.get('benchmark_total_return', 0):.4f}x  ({m.get('benchmark_total_return', 0)*100:.1f}%)")
    print(f"  초과수익률: {m.get('excess_return', 0):+.4f} ({m.get('excess_return', 0)*100:+.1f}%p)")
    print(f"  정보비율  : {m.get('information_ratio', 0):.4f}")
    print(f"  알파(연율): {m.get('alpha_annualized', 0):.4f}")
    print(f"  베타      : {m.get('beta', 0):.4f}")
    print(f"  최종자산  : ${res['equity_curve']['equity'].iloc[-1]:,.0f}" if not res['equity_curve'].empty else "")
    print(f"  Sharpe    : {m.get('sharpe', 0):.4f}")
    print(f"  MDD       : {m.get('max_drawdown', 0):.4f} ({m.get('max_drawdown', 0)*100:.1f}%)")
    print(f"  승률      : {m.get('win_rate', 0):.2%}")
    print(f"  거래수    : {m.get('num_round_trades', 0)}")

    # 연도별 수익률
    ec = res["equity_curve"].copy()
    if not ec.empty:
        import pandas as pd
        ec.index = pd.to_datetime(ec.index, utc=True)
        print("\n  연도별 수익률:")
        for year in [2022, 2023, 2024, 2025]:
            yr = ec[ec.index.year == year]
            if not yr.empty:
                ret = (yr["equity"].iloc[-1] - yr["equity"].iloc[0]) / yr["equity"].iloc[0]
                print(f"    {year}: {ret:+.1%}")


if __name__ == "__main__":
    main()
