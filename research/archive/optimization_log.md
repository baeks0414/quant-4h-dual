## Autonomous Quant Optimization Log

Objective constraints:
- Total Return >= 5.285
- Sharpe >= 1.6745
- |MDD| <= 0.2303 (reported as `max_drawdown` negative, so closer to 0 is better)
- Optimize Winrate under constraints

### Baseline (current code preset)

- Source run: `results/optimization_run_baseline`
- Metrics: Total_Ret=6.4981, Sharpe=1.9464, MDD=-0.1697, Winrate=0.2691
- Yearly returns: 2022=-0.0473, 2023=3.3005, 2024=0.7958, 2025=0.0191
- Regime PnL (bar-attributed): STRONG_TREND=53,668.81, VOL_EXPAND=13,223.85, CHOP=-1,911.96

### Experiment Table

| Stage | Params (single hypothesis) | Total_Ret | Sharpe | MDD | Winrate | Result |
|---|---|---:|---:|---:|---:|---|
| E1 | `vol_breakout_strict=true` | 6.0855 | 1.9226 | -0.1670 | 0.2647 | Discard |
| E2 | `vol_break_near_atr_mult=0.3` | 6.1019 | 1.9077 | -0.1772 | 0.2586 | Discard |
| E3 | `trail_atr_mult=2.6` | 6.4648 | 1.9320 | -0.1723 | 0.2669 | Discard |
| E4 | `trail_atr_mult=2.4` | 4.6228 | 1.7602 | -0.1784 | 0.2663 | Discard (return↓) |
| E5 | `stop_atr_mult_vol=1.9` | 6.3000 | 1.9433 | -0.1669 | 0.2661 | Discard |
| E6 | `enable_short=false` | 4.1462 | 1.7368 | -0.2038 | 0.2426 | Discard (return↓) |
| E7 | `allow_regimes=(STRONG_TREND,)` | 4.5531 | 1.8330 | -0.1950 | 0.2337 | Discard (return↓) |
| E8 | `trend_entry_buffer_atr=0.05` | 6.0224 | 1.9060 | -0.1867 | 0.2625 | Discard |
| E9 | `trend_min_ema_spread_atr=0.08` | 6.1663 | 1.9102 | -0.1563 | 0.2646 | Discard |
| E10 | `vol_require_ema_alignment=true` (temp code) | 6.3321 | 1.9426 | -0.1675 | 0.2603 | Discard |
| E11 | `flip_cooldown_bars=5` | 6.2180 | 1.9132 | -0.1697 | 0.2669 | Discard |
| E12 | `flip_cooldown_bars=7` | 6.1756 | 1.9068 | -0.1696 | 0.2638 | Discard |
| E13 | `trend_entry_buffer_atr=0.02` | 6.5014 | 1.9475 | -0.1632 | 0.2635 | Discard (winrate↓) |
| E14 | `trend_entry_buffer_atr=0.01` | 6.4907 | 1.9455 | -0.1664 | 0.2651 | Discard |
| E15 | `vol_align=true + entry_buffer=0.02` | 6.3354 | 1.9437 | -0.1634 | 0.2547 | Discard |
| E16 | `min_hold_bars=2` | **6.5123** | **1.9478** | -0.1697 | **0.2699** | **Adopt** |
| E17 | `min_hold_bars=3` | 6.5023 | 1.9465 | -0.1706 | 0.2699 | Discard (MDD slightly worse than E16) |
| E18 | `vol_align=true` recheck | 6.3321 | 1.9426 | -0.1675 | 0.2603 | Discard (consistency check) |

### Adopted candidate

- Adopted hypothesis: `min_hold_bars=2`
- Why:
  - Best winrate among tested runs while satisfying all hard constraints.
  - Also improved total return and sharpe over baseline.
  - MDD remains within constraint and equal to baseline level.

### Overfitting guard note

- Multiple structurally different hypotheses were tested (entry strictness, regime gate, stop/trail, direction filters, cooldown, hold-time).
- Selection criterion prioritized constraint satisfaction + winrate, not single-metric maximization only.
- Candidate `min_hold_bars=2` was compared against neighboring value (`min_hold_bars=3`) to avoid isolated-point selection.

### Artifacts

- Summary: `results/optimization_summary.csv`
- Baseline regime analysis:
  - `results/optimization_run_baseline/regime_bar_stats_LATEST.csv`
  - `results/optimization_run_baseline/regime_trade_stats_LATEST.csv`
- E10 regime analysis:
  - `results/optimization_run_e10_volalign_on/regime_bar_stats_LATEST.csv`
  - `results/optimization_run_e10_volalign_on/regime_trade_stats_LATEST.csv`


### Stage3 (2026-03-05) Adaptive Trail Innovation

- Goal: `total_return +1.0` vs current baseline, while avoiding large DD damage, and improving both 2024/2025 returns.
- Detailed log: `AUTONOMOUS_TREND_OPT_STAGE3_20260305.md`
- Sweep CSV: `Project_4h/innov_strategy_stage3_adapttrail_risk_20260305.csv`

| Stage | Params | Total_Ret | Sharpe | MDD | Winrate | Result |
|---|---|---:|---:|---:|---:|---|
| BASELINE_LOCAL | `{}` | 6.6630 | 1.9669 | -0.1632 | 0.2651 | Baseline |
| S5_R013_CAP0035_TW12_TV095 | `enable_adaptive_trail=true, risk_per_trade=0.013, portfolio_risk_cap=0.035, trail_widen_mult=1.2, trail_vol_expand_mult=0.95` | 7.8961 | 1.9393 | -0.1799 | 0.2697 | Adopt |
| S5_R014_CAP0035_TW12_TV095 | `enable_adaptive_trail=true, risk_per_trade=0.014, portfolio_risk_cap=0.035, trail_widen_mult=1.2, trail_vol_expand_mult=0.95` | 9.4892 | 1.9634 | -0.1939 | 0.2722 | Discard (DD increase larger) |

### Stage4 (2026-03-05) MDD Sign Clarification + Graph Artifacts

- Constraint clarified by user: `max_drawdown > -0.20` (not `< -0.20`).
- Detailed log: `AUTONOMOUS_TREND_OPT_STAGE4_20260305.md`
- Comparison summary: `Project_4h/stage4_strategy_comparison_20260305.csv`

| Strategy | Total_Ret | Sharpe | MDD | Winrate | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|
| stage3_reference | 6.6614 | 1.6968 | -0.2601 | 0.2384 | 0.8037 | -0.0280 |
| context_adaptive_general | 11.9102 | 1.4275 | -0.4016 | 0.1562 | 1.4381 | 0.2115 |
| mdd_gt_neg02_max_return | 3.0491 | 1.4873 | -0.1991 | 0.1882 | 0.8712 | -0.0079 |

Artifacts (for later review / graph view):
- `Project_4h/stage4_strategy_comparison_20260305.csv`
- `Project_4h/stage4_strategy_comparison_20260305.json`
- `Project_4h/graphs/stage4_equity_compare_20260305.png`
- `Project_4h/graphs/stage4_drawdown_compare_20260305.png`
- `Project_4h/graphs/stage4_yearly_returns_20260305.png`

