# Autonomous Trend Optimizer Stage4 (MDD Constraint Refit)

- Date: 2026-03-05
- Objective: Keep strategy logs/artifacts reproducible and add graph-based comparison outputs.
- Constraint update: interpret MDD constraint as `max_drawdown > -0.20`.

## Stage Table
| Strategy | Total_Ret | Sharpe | MDD | Winrate | 2024 | 2025 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| stage3_reference | 6.6614 | 1.6968 | -0.2601 | 0.2384 | 0.8037 | -0.0280 |
| context_adaptive_general | 11.9102 | 1.4275 | -0.4016 | 0.1562 | 1.4381 | 0.2115 |
| mdd_gt_neg02_max_return | 3.0491 | 1.4873 | -0.1991 | 0.1882 | 0.8712 | -0.0079 |

## Decision
- For strict `MDD > -0.20`, adopted preset is `mdd_gt_neg02_max_return`.
- If priority shifts to higher return (allowing deeper DD), `context_adaptive_general` remains available.

## Artifacts
- Summary CSV: `Project_4h/stage4_strategy_comparison_20260305.csv`
- Summary JSON: `Project_4h/stage4_strategy_comparison_20260305.json`
- Equity Graph PNG: `Project_4h/graphs/stage4_equity_compare_20260305.png`
- Drawdown Graph PNG: `Project_4h/graphs/stage4_drawdown_compare_20260305.png`
- Yearly Returns Graph PNG: `Project_4h/graphs/stage4_yearly_returns_20260305.png`
- Reference Stage3 source: `Project_4h/result_verify_candidate_stage3_20260305`
