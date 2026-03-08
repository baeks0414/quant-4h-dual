# quant_4h_1

Cleaned 4h quant research workspace extracted from the broader `Project_4h` repository.

This folder keeps only:
- active source code under `src/quant`
- final verification scripts under `experiments/final`
- analysis scripts under `experiments/analysis`
- convenience PowerShell runners under `scripts`
- major research notes and robustness artifacts under `research`
- final benchmark and adopted result folders under `results/final`

Quick start:
- direct run without install:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\verify_dynamic_v2.ps1`
  - `powershell -ExecutionPolicy Bypass -File .\scripts\verify_dual_combo.ps1`
- editable install:
  - `powershell -ExecutionPolicy Bypass -File .\scripts\install_editable.ps1`
  - `python -m quant.cli.backtest --outdir results/final/result_cli_regime_only`

Canonical strategy references:
- `quant.config.presets.preset_dynamic_params_v2()`
- `quant.config.presets.preset_dynamic_bear_state_trend()`
- `quant.config.presets.preset_balanced_alpha_sleeve_aggressive()`

Key verification entrypoints:
- `experiments/final/verify_main_preset.py`
- `experiments/final/verify_dynamic_v2.py`
- `experiments/final/verify_state_gated_dual_combo.py`
- `experiments/final/validate_state_gated_dual_overfit.py`

Key analysis entrypoints:
- `experiments/analysis/adx_tier_analysis.py`
- `experiments/analysis/regime_pnl_report.py`
- `experiments/analysis/regime_pnl_2025_analysis.py`

Current adopted robust result:
- Dual sleeve: 70% state-gated bear trend + 30% balanced alpha sleeve
- Base verify: final equity about $112.3k, MDD about -15.75%
- 1.25x cost stress: final equity about $102.2k, MDD about -16.09%

See `research/00_index.md` for the retained study map.
