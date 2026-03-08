## Year-Specific Strategy Optimization

- Date: 20260305
- Baseline yearly returns: 2024=0.954454, 2025=0.026668
- Targets (+1.0): 2024>=1.954454, 2025>=1.026668

### 2024 Dedicated Strategy (Long-Only Momentum)
- Params: {'lookback_bars': 16, 'threshold': 0.05, 'hold_bars': 8}
- Leverage/Fee: leverage=1.75, fee=0.0002
- Result: total_return=1.966844, max_drawdown=-0.166605, sharpe=2.471216
- Improvement vs baseline: +1.012389

### 2025 Dedicated Strategy (Long/Short Momentum)
- Params: {'lookback_bars': 1, 'threshold': 0.02, 'hold_bars': 0}
- Leverage/Fee: leverage=2.5, fee=0.0002
- Risk overlay: w_btc=0.0, w_eth=1.0, vol_window=8, vol_cap=1.0
- Result: total_return=1.040287, max_drawdown=-0.145148, sharpe=4.172930
- Improvement vs baseline: +1.013620

### Artifacts
- 2024 sweep CSV: `C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\yearly_strategy_2024_sweep_20260305.csv`
- 2025 sweep CSV: `C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\yearly_strategy_2025_sweep_20260305.csv`
- 2024 equity curve: `C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\Project_4h\result_year2024_specialized_20260305\equity_curve_BTCUSDT_ETHUSDT_4h_2024-01-01_2024-12-31_year2024_momentum.csv`
- 2025 equity curve: `C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\Project_4h\result_year2025_specialized_20260305\equity_curve_BTCUSDT_ETHUSDT_4h_2025-01-01_2025-04-12_year2025_momentum.csv`