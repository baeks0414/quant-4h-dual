## Autonomous Trend Optimizer Stage2 (Local Sweep)

- Sweep size: 48
- Constraint: total_return > 6.358687, max_drawdown > -0.181737

| Stage | Params | Total_Ret | Sharpe | MDD | Winrate | Result |
| --- | --- | --- | --- | --- | --- | --- |
| s2_adx13p0_buf0p02_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 13.0} | 6.6630 | 1.9669 | -0.1632 | 0.2651 | Adopt |
| s2_adx13p0_buf0p02_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 13.0} | 6.6528 | 1.9656 | -0.1641 | 0.2651 | Keep candidate |
| s2_adx14p0_buf0p02_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 14.0} | 6.6051 | 1.9644 | -0.1632 | 0.2651 | Keep candidate |
| s2_adx13p0_buf0p02_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 13.0} | 6.6298 | 1.9640 | -0.1632 | 0.2651 | Keep candidate |
| s2_adx14p0_buf0p02_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 14.0} | 6.5949 | 1.9630 | -0.1641 | 0.2651 | Keep candidate |
| s2_adx13p0_buf0p02_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 13.0} | 6.6199 | 1.9627 | -0.1641 | 0.2651 | Keep candidate |
| s2_adx14p0_buf0p02_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 14.0} | 6.5721 | 1.9614 | -0.1632 | 0.2651 | Keep candidate |
| s2_adx14p0_buf0p02_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 14.0} | 6.5623 | 1.9601 | -0.1641 | 0.2651 | Keep candidate |
| s2_adx15p0_buf0p02_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 15.0} | 5.7183 | 1.8929 | -0.1632 | 0.2651 | Discard |
| s2_adx15p0_buf0p02_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 15.0} | 5.7094 | 1.8916 | -0.1641 | 0.2651 | Discard |
| s2_adx15p0_buf0p02_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 15.0} | 5.6892 | 1.8899 | -0.1632 | 0.2651 | Discard |
| s2_adx15p0_buf0p02_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 15.0} | 5.6805 | 1.8885 | -0.1641 | 0.2651 | Discard |
| s2_adx13p0_buf0p025_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 13.0} | 6.4807 | 1.9595 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx12p0_buf0p02_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 12.0} | 6.5963 | 1.9591 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx13p0_buf0p025_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 13.0} | 6.4707 | 1.9582 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx12p0_buf0p02_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 12.0} | 6.5862 | 1.9578 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx14p0_buf0p025_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 14.0} | 6.4242 | 1.9569 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx13p0_buf0p025_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 13.0} | 6.4483 | 1.9566 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx12p0_buf0p02_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 12.0} | 6.5634 | 1.9562 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx14p0_buf0p025_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 14.0} | 6.4143 | 1.9556 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx13p0_buf0p025_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 13.0} | 6.4386 | 1.9553 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx12p0_buf0p02_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 12.0} | 6.5536 | 1.9549 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx14p0_buf0p025_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 14.0} | 6.3920 | 1.9540 | -0.1632 | 0.2643 | Keep candidate |
| s2_adx14p0_buf0p025_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 14.0} | 6.3824 | 1.9527 | -0.1641 | 0.2643 | Keep candidate |
| s2_adx15p0_buf0p025_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 15.0} | 5.5585 | 1.8851 | -0.1632 | 0.2643 | Discard |
| s2_adx15p0_buf0p025_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 15.0} | 5.5498 | 1.8837 | -0.1641 | 0.2643 | Discard |
| s2_adx15p0_buf0p025_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 15.0} | 5.5301 | 1.8820 | -0.1632 | 0.2643 | Discard |
| s2_adx15p0_buf0p025_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 15.0} | 5.5216 | 1.8807 | -0.1641 | 0.2643 | Discard |
| s2_adx13p0_buf0p015_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 13.0} | 6.5900 | 1.9583 | -0.1643 | 0.2635 | Keep candidate |
| s2_adx13p0_buf0p015_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 13.0} | 6.5799 | 1.9570 | -0.1652 | 0.2635 | Keep candidate |
| s2_adx14p0_buf0p015_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 14.0} | 6.5327 | 1.9557 | -0.1643 | 0.2635 | Keep candidate |
| s2_adx13p0_buf0p015_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 13.0} | 6.5572 | 1.9554 | -0.1643 | 0.2635 | Keep candidate |
| s2_adx14p0_buf0p015_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 14.0} | 6.5226 | 1.9544 | -0.1652 | 0.2635 | Keep candidate |
| s2_adx13p0_buf0p015_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 13.0} | 6.5473 | 1.9541 | -0.1652 | 0.2635 | Keep candidate |
| s2_adx14p0_buf0p015_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 14.0} | 6.5001 | 1.9528 | -0.1643 | 0.2635 | Keep candidate |
| s2_adx12p0_buf0p025_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 12.0} | 6.4156 | 1.9516 | -0.1632 | 0.2635 | Keep candidate |
| s2_adx14p0_buf0p015_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 14.0} | 6.4903 | 1.9515 | -0.1652 | 0.2635 | Keep candidate |
| s2_adx12p0_buf0p025_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 12.0} | 6.4057 | 1.9503 | -0.1641 | 0.2635 | Keep candidate |
| s2_adx12p0_buf0p025_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 12.0} | 6.3835 | 1.9487 | -0.1632 | 0.2635 | Keep candidate |
| s2_adx12p0_buf0p025_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.025, "vol_break_min_adx": 12.0} | 6.3739 | 1.9474 | -0.1641 | 0.2635 | Keep candidate |
| s2_adx15p0_buf0p015_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 15.0} | 5.6544 | 1.8841 | -0.1643 | 0.2635 | Discard |
| s2_adx15p0_buf0p015_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 15.0} | 5.6455 | 1.8827 | -0.1652 | 0.2635 | Discard |
| s2_adx15p0_buf0p015_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 15.0} | 5.6256 | 1.8810 | -0.1643 | 0.2635 | Discard |
| s2_adx15p0_buf0p015_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 15.0} | 5.6169 | 1.8797 | -0.1652 | 0.2635 | Discard |
| s2_adx12p0_buf0p015_mh2_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 12.0} | 6.5240 | 1.9505 | -0.1643 | 0.2627 | Keep candidate |
| s2_adx12p0_buf0p015_mh3_cd3 | {"flip_cooldown_bars": 3, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 12.0} | 6.5140 | 1.9492 | -0.1652 | 0.2627 | Keep candidate |
| s2_adx12p0_buf0p015_mh2_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 12.0} | 6.4914 | 1.9476 | -0.1643 | 0.2627 | Keep candidate |
| s2_adx12p0_buf0p015_mh3_cd4 | {"flip_cooldown_bars": 4, "min_hold_bars": 3, "trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 12.0} | 6.4817 | 1.9463 | -0.1652 | 0.2627 | Keep candidate |

### Best Stage2 Candidate
- run: s2_adx13p0_buf0p02_mh2_cd3
- params: {"flip_cooldown_bars": 3, "min_hold_bars": 2, "trend_entry_buffer_atr": 0.02, "vol_break_min_adx": 13.0}
- metrics: ret=6.662968, sharpe=1.966942, mdd=-0.163188, win=0.265060
- yearly_returns: {"2022": -0.04453460211028282, "2023": 3.325215292053077, "2024": 0.820112762126894, "2025": 0.018769696703226035}
- regime_bar_pnl: {"CHOP": -2216.98989608344, "STRONG_TREND": 54898.885697437734, "VOL_EXPAND": 13947.783276522901}