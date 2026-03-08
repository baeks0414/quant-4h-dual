# Research Index

## Purpose

This workspace is the reduced research set for the BTC/ETH 4h project. It preserves the code and files needed to understand:
- how `Dynamic v2` evolved
- why the state-gated bear overlay was introduced
- why the final adopted candidate is the more robust 70/30 dual sleeve

## Final adopted baseline

- `preset_dynamic_params_v2()`
  - optimized single-engine trend preset
  - target area: about `8.0x` return with MDD inside `-20%`
- `preset_dynamic_bear_state_trend()`
  - state-gated bear-overlay trend sleeve
  - strong 2024/2025 capture, weak standalone 2022
- `preset_balanced_alpha_sleeve_aggressive()`
  - positive-2022 balancing sleeve

## Final adopted robust combo

- allocation: `70% trend sleeve + 30% alpha sleeve`
- verify result:
  - final equity about `$112,338`
  - total return about `10.2338x`
  - MDD about `-15.75%`
  - `2022 +9.41%`
  - `2024 +112.67%`
  - `2025 +32.77%`
- 1.25x cost stress:
  - final equity about `$102,221`
  - MDD about `-16.09%`
  - `2022 +6.60%`
  - `2024 +107.54%`
  - `2025 +31.54%`

## Kept scripts

- `experiments/final/verify_main_preset.py`
  - recheck the main preset baseline
- `experiments/final/verify_dynamic_v2.py`
  - reproduces the current Dynamic v2 baseline
- `experiments/final/verify_state_gated_dual_combo.py`
  - reproduces the adopted robust dual-sleeve result
- `experiments/final/validate_state_gated_dual_overfit.py`
  - overfit and cost-stress validation for the adopted family
- `experiments/analysis/adx_tier_analysis.py`
  - ADX tier / regime / hold-duration breakdown
- `experiments/analysis/regime_pnl_report.py`
  - regime PnL decomposition
- `experiments/analysis/regime_pnl_2025_analysis.py`
  - 2025-specific weakness analysis

## Kept research notes

- `research/archive/AUTONOMOUS_TREND_OPT_LOG_20260304.md`
- `research/archive/AUTONOMOUS_TREND_OPT_STAGE2_20260304.md`
- `research/archive/AUTONOMOUS_TREND_OPT_STAGE3_20260305.md`
- `research/archive/AUTONOMOUS_TREND_OPT_STAGE4_20260305.md`
- `research/archive/CHANGE_SUMMARY_2026-03-04.md`
- `research/archive/ANTI_OVERFIT_GUARDRAIL_20260305.md`
- `research/archive/STATE_GATED_DUAL_OVERFIT_20260307.md`
- `research/archive/optimization_log.md`
- `research/archive/YEAR_SPECIFIC_STRATEGY_OPT_20260305.md`

## Kept research data

- `research/data/anti_overfit_guardrail_20260305.csv`
- `research/data/anti_overfit_guardrail_20260305.json`
- `research/data/state_gated_dual_cost_recheck_20260307.csv`
- `research/data/state_gated_dual_overfit_20260307.json`

## Kept result folders

- `results/final/result_verify_baseline_current_20260305`
- `results/final/result_validate_state_gated_dual_overfit_20260307`
- `results/final/result_verify_state_gated_dual_combo_robust_20260307`

## Intentionally excluded from this workspace

- bulk sweep scripts such as `dynamic_v2_sweep*.py`
- temporary result trees such as `result_tmp_*`
- large search result families such as `result_target_*`, `result_innov_*`, `result_autonomous_*`
- dead or duplicate files such as `your_strategy(MR CHOP).py`

The original repository remains untouched outside this folder.
