# Anti-Overfit Guardrail Report (20260305)

## Protocol
- Time diversification: 3 non-overlapping slices
- Universe diversification: BTC/ETH + BNB/SOL
- Parameter perturbation: risk/stop/trail/confirmation stress
- Acceptance: all numeric guardrails must pass

## Result
- pass_all: **True**
- checks:
  - cell_positive_ratio: True
  - worst_cell_return: True
  - worst_cell_mdd: True
  - median_cell_sharpe: True
  - perturb_pass_ratio: True
  - perturb_worst_drop: True

## Aggregate Metrics
- cell_positive_ratio: 0.833333
- worst_cell_return: -0.199709
- worst_cell_mdd: -0.467573
- median_cell_sharpe: 0.835209
- perturb_pass_ratio: 1.000000
- perturb_worst_drop: 0.465421

## Cell Metrics
```text
         basket               slice      start        end  total_return  max_drawdown    sharpe  winrate  num_round_trades
BTCUSDT_ETHUSDT slice_2022H1_2023H1 2022-01-01 2023-06-30      0.837565     -0.467573  0.961496 0.166023               259
BTCUSDT_ETHUSDT slice_2023H2_2024H1 2023-07-01 2024-06-30      3.196272     -0.360069  2.111998 0.168478               184
BTCUSDT_ETHUSDT slice_2024H2_2025Q1 2024-07-01 2025-04-12      0.494463     -0.255943  1.120646 0.235294               136
BNBUSDT_SOLUSDT slice_2022H1_2023H1 2022-01-01 2023-06-30      0.411259     -0.350030  0.708923 0.192157               255
BNBUSDT_SOLUSDT slice_2023H2_2024H1 2023-07-01 2024-06-30      0.081877     -0.287341  0.401328 0.250000               176
BNBUSDT_SOLUSDT slice_2024H2_2025Q1 2024-07-01 2025-04-12     -0.199709     -0.367194 -0.664200 0.226950               141
```

## Perturbation Metrics
```text
       variant  total_return  max_drawdown   sharpe  winrate  num_round_trades    y2024     y2025
          base     10.241306     -0.467573 1.396990 0.183533               583 0.962804  0.061538
   risk_-10pct      8.529776     -0.443459 1.376410 0.180103               583 1.055016  0.050616
   risk_+10pct      9.759152     -0.488539 1.345521 0.184165               581 0.808857  0.064581
   stop_-10pct      9.042532     -0.443827 1.389856 0.178082               584 1.076110  0.050291
   stop_+10pct      9.132125     -0.486999 1.328193 0.183849               582 0.770364  0.059402
  trail_-10pct     12.128179     -0.460595 1.484992 0.185374               588 1.216602  0.098277
  trail_+10pct     10.430072     -0.485108 1.397028 0.174825               572 1.053321  0.033478
 confirm_relax     11.366129     -0.528709 1.301321 0.154155               746 2.154448 -0.026350
confirm_strict      5.474783     -0.458601 1.268217 0.186475               488 0.562381  0.122244
```

## Evaluated Preset
```json
{
  "symbols": [
    "BTCUSDT",
    "ETHUSDT"
  ],
  "interval": "4h",
  "start": "2022-01-01",
  "end": "2025-04-12",
  "initial_equity": 10000.0,
  "risk_per_trade": 0.009,
  "portfolio_risk_cap": 0.08,
  "max_leverage": 5.0,
  "fee_rate": 0.0005,
  "slippage": 0.0003,
  "ema_fast": 20,
  "ema_slow": 45,
  "adx_trend": 30.0,
  "atr_expand_ratio": 1.2,
  "donchian_window": 30,
  "funding_extreme": 0.0005,
  "stop_atr_mult_trend": 1.6,
  "stop_atr_mult_vol": 1.4,
  "stop_atr_mult_funding": 1.0,
  "trail_atr_mult": 2.1,
  "enable_adaptive_trail": true,
  "trail_adx_widen_threshold": 38.0,
  "trail_widen_mult": 1.3,
  "trail_adx_tighten_threshold": 22.0,
  "trail_tighten_mult": 0.9,
  "trail_vol_expand_mult": 0.9,
  "vol_breakout_strict": false,
  "vol_break_near_atr_mult": 0.7,
  "enable_innov_trend_filter": false,
  "trend_min_ema_slope_atr": 0.0,
  "trend_min_adx_slope_3": 0.05,
  "trend_min_ema_spread_atr": 0.06,
  "trend_entry_buffer_atr": 0.02,
  "enable_trend_pullback_entry": true,
  "trend_pullback_max_gap_atr": 0.6,
  "trend_pullback_stop_atr_mult": 2.0,
  "vol_break_min_adx": 12.0,
  "vol_break_max_adx": 50.0,
  "vol_break_min_ema_spread_atr": 0.02,
  "vol_break_min_ema_slope_atr": 0.0,
  "enable_micro_trend": true,
  "micro_trend_min_adx": 18.0,
  "micro_trend_max_adx": 26.0,
  "micro_trend_min_ema_spread_atr": 0.0,
  "micro_trend_entry_buffer_atr": 0.0,
  "micro_trend_stop_atr_mult": 1.8,
  "enable_regime_gate": true,
  "market_symbol": "BTCUSDT",
  "allow_regimes": [
    "STRONG_TREND",
    "VOL_EXPAND",
    "STRONG_TREND_BEAR"
  ],
  "enable_vol_risk": true,
  "target_stop_pct": 0.028,
  "vol_min_scale": 0.4,
  "vol_max_scale": 2.5,
  "min_stop_pct_floor": 0.005,
  "risk_scale_strong_trend": 1.4,
  "risk_scale_vol_expand": 1.8,
  "risk_scale_chop": 0.8,
  "mr_window": 50,
  "mr_bb_window": 14,
  "mr_use_bb": true,
  "mr_entry_z": 1.5,
  "mr_exit_z": 0.3,
  "mr_stop_atr_mult": 2.0,
  "mr_max_hold_bars": 12,
  "enable_dual_portfolio": false,
  "trend_equity_ratio": 0.7,
  "mr_equity_ratio": 0.3,
  "enable_short": true,
  "enable_bear_regime": true,
  "min_hold_bars": 3,
  "flip_cooldown_bars": 3,
  "regime_confirm_bars": 3,
  "entry_confirm_bars": 2,
  "enable_pyramiding": true,
  "pyramid_max_adds": 4,
  "pyramid_min_profit_atr": 1.2,
  "pyramid_risk_scale": 0.6,
  "pyramid_min_adx": 12.0,
  "pyramid_min_ema_slope": 0.02,
  "pyramid_cooldown_bars": 1,
  "binance_api_key": "",
  "binance_api_secret": "",
  "binance_fapi_base_url": ""
}
```