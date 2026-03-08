## Autonomous Trend Optimizer Stage3 (Adaptive Trail Innovation)

- Date: 2026-03-05
- Objective: Increase total return by at least +1.0 from current baseline while keeping DD damage controlled, and raise both 2024/2025 yearly returns.
- Baseline source: `preset_regime_only_live` (before Stage3 adoption)

### Validation Note
- Repro runs were executed with local module path fixed to this workspace:
  - `C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\Project_4h\src`
- This avoids accidental imports from another external `quant` project on the machine.

### Stage Table
| Stage | Params | Total_Ret | Sharpe | MDD | Winrate | Result |
| --- | --- | --- | --- | --- | --- | --- |
| BASELINE_LOCAL | `{}` | 6.6630 | 1.9669 | -0.1632 | 0.2651 | Baseline |
| S5_R013_CAP0035_TW12_TV095 | `{"enable_adaptive_trail": true, "risk_per_trade": 0.013, "portfolio_risk_cap": 0.035, "trail_widen_mult": 1.2, "trail_vol_expand_mult": 0.95}` | 7.8961 | 1.9393 | -0.1799 | 0.2697 | Adopt |
| S5_R014_CAP0035_TW12_TV095 | `{"enable_adaptive_trail": true, "risk_per_trade": 0.014, "portfolio_risk_cap": 0.035, "trail_widen_mult": 1.2, "trail_vol_expand_mult": 0.95}` | 9.4892 | 1.9634 | -0.1939 | 0.2722 | Discard (DD increase larger) |
| S5_R013_CAP0040_TW12_TV095 | `{"enable_adaptive_trail": true, "risk_per_trade": 0.013, "portfolio_risk_cap": 0.04, "trail_widen_mult": 1.2, "trail_vol_expand_mult": 0.95}` | 8.0242 | 1.9411 | -0.1799 | 0.2667 | Discard (lower winrate vs adopted) |

### Yearly Returns
- Baseline: `2024=0.8201`, `2025=0.0188`
- Adopted Stage3: `2024=0.9545`, `2025=0.0267`

### Robustness Snapshot (Non-BTC basket)
- Symbols: `BNBUSDT`, `SOLUSDT`
- Baseline: `ret=0.5158`, `sharpe=0.7090`, `mdd=-0.1566`, `winrate=0.2613`
- Adopted Stage3: `ret=0.5270`, `sharpe=0.6687`, `mdd=-0.1894`, `winrate=0.2605`

### Artifact Paths
- Stage3 sweep CSV: `Project_4h/innov_strategy_stage3_adapttrail_risk_20260305.csv`
- Baseline verify run: `Project_4h/result_verify_baseline_local_20260305`
- Candidate verify run: `Project_4h/result_verify_candidate_local_20260305`
- Robustness baseline verify run: `Project_4h/result_verify_robust_baseline_bnb_sol_local_20260305`
- Robustness candidate verify run: `Project_4h/result_verify_robust_candidate_bnb_sol_local_20260305`
