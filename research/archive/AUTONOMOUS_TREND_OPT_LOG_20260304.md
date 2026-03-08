## Autonomous Trend Optimizer Log

- Date tag: 20260304
- Mission: Trend-only autonomous optimization with Method2 baseline constraints.

### Baseline (Method2)
- total_return=6.358687, sharpe=1.796278, mdd=-0.181737, winrate=0.317814
- Constraints used: total_return > 6.358687, max_drawdown > -0.181737

### Stage Table
| Stage | Params | Total_Ret | Sharpe | MDD | Winrate | Result |
| --- | --- | --- | --- | --- | --- | --- |
| S0_BASELINE | {} | 6.5157 | 1.9489 | -0.1632 | 0.2643 | Adopt |
| S1_VOLADX14 | {"vol_break_min_adx": 14.0} | 6.6051 | 1.9644 | -0.1632 | 0.2651 | Adopt |
| S2_VOLADX16 | {"vol_break_min_adx": 16.0} | 5.6076 | 1.8780 | -0.1632 | 0.2651 | Discard (constraint fail) |
| S3_VOLADX18 | {"vol_break_min_adx": 18.0} | 5.4541 | 1.8600 | -0.1657 | 0.2620 | Discard (constraint fail) |
| S4_VOLADX16_SPREAD0015 | {"vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015} | 5.5298 | 1.8841 | -0.1634 | 0.2562 | Discard (constraint fail) |
| S5_VOLADX18_SPREAD0025 | {"vol_break_min_adx": 18.0, "vol_break_min_ema_spread_atr": 0.025} | 5.4994 | 1.8802 | -0.1634 | 0.2531 | Discard (constraint fail) |
| S6_VOLADX16_MAX28 | {"vol_break_max_adx": 28.0, "vol_break_min_adx": 16.0} | 4.8770 | 1.8514 | -0.1780 | 0.2394 | Discard (constraint fail) |
| S7_REGRISK_ST110_V085 | {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.85} | 6.2345 | 1.9255 | -0.1619 | 0.2635 | Discard (constraint fail) |
| S8_REGRISK_ST115_V080 | {"risk_scale_strong_trend": 1.15, "risk_scale_vol_expand": 0.8} | 6.7643 | 1.9255 | -0.2192 | 0.2605 | Discard (constraint fail) |
| S9_COMBO_FILTER_RISK | {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.85, "vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015} | 5.6673 | 1.8741 | -0.1554 | 0.2571 | Discard (constraint fail) |
| S10_COMBO_FILTER_RISK2 | {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.8, "vol_break_min_adx": 18.0, "vol_break_min_ema_spread_atr": 0.02} | 6.0255 | 1.9146 | -0.1536 | 0.2539 | Discard (constraint fail) |
| S11_TRENDBUF015_VOLADX16 | {"trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015} | 5.4676 | 1.8752 | -0.1634 | 0.2547 | Discard (constraint fail) |
| S12_FLIP4_VOLADX16 | {"flip_cooldown_bars": 4, "vol_break_min_adx": 16.0} | 5.5790 | 1.8750 | -0.1632 | 0.2651 | Discard (constraint fail) |
| S13_FUNDING_OFF | {"funding_extreme": 1.0} | 6.2781 | 1.9245 | -0.1821 | 0.2622 | Discard (constraint fail) |

### Stage Details
- S0_BASELINE
  - params: {}
  - metrics: ret=6.515660, sharpe=1.948895, mdd=-0.163188, win=0.264264
  - yearly_returns: {"2022": -0.04453460211028282, "2023": 3.2793013286616244, "2024": 0.8042771412510064, "2025": 0.0187696967032267}
  - regime_bar_pnl: {"CHOP": -2396.1019098534307, "STRONG_TREND": 54337.14213319599, "VOL_EXPAND": 13215.55507282678}
  - decision: Adopt
- S1_VOLADX14
  - params: {"vol_break_min_adx": 14.0}
  - metrics: ret=6.605076, sharpe=1.964350, mdd=-0.163188, win=0.265060
  - yearly_returns: {"2022": -0.04453460211028282, "2023": 3.2925393823417926, "2024": 0.8201127621268973, "2025": 0.018769696703225813}
  - regime_bar_pnl: {"CHOP": -2194.184912029261, "STRONG_TREND": 54564.56272324985, "VOL_EXPAND": 13680.38338496098}
  - decision: Adopt
- S2_VOLADX16
  - params: {"vol_break_min_adx": 16.0}
  - metrics: ret=5.607606, sharpe=1.878025, mdd=-0.163188, win=0.265060
  - yearly_returns: {"2022": -0.04453460211028282, "2023": 2.794167085251669, "2024": 0.8228183823445752, "2025": -7.064779326770854e-05}
  - regime_bar_pnl: {"CHOP": -1969.4745843650744, "STRONG_TREND": 48629.28061533123, "VOL_EXPAND": 9416.252998163225}
  - decision: Discard (constraint fail)
- S3_VOLADX18
  - params: {"vol_break_min_adx": 18.0}
  - metrics: ret=5.454056, sharpe=1.860020, mdd=-0.165747, win=0.262048
  - yearly_returns: {"2022": -0.047494633548485043, "2023": 2.723382220993176, "2024": 0.8073074293362816, "2025": 0.006921568956181012}
  - regime_bar_pnl: {"CHOP": -2637.9137714973112, "STRONG_TREND": 48323.92455040803, "VOL_EXPAND": 8854.549256294846}
  - decision: Discard (constraint fail)
- S4_VOLADX16_SPREAD0015
  - params: {"vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015}
  - metrics: ret=5.529775, sharpe=1.884099, mdd=-0.163396, win=0.256250
  - yearly_returns: {"2022": -0.015419051363798841, "2023": 2.750398311990185, "2024": 0.7662778404314505, "2025": 0.0011758301308326669}
  - regime_bar_pnl: {"CHOP": -1790.6444919597452, "STRONG_TREND": 48965.82436150379, "VOL_EXPAND": 8122.567523301157}
  - decision: Discard (constraint fail)
- S5_VOLADX18_SPREAD0025
  - params: {"vol_break_min_adx": 18.0, "vol_break_min_ema_spread_atr": 0.025}
  - metrics: ret=5.499378, sharpe=1.880184, mdd=-0.163396, win=0.253125
  - yearly_returns: {"2022": -0.01846928276710913, "2023": 2.7503983119901996, "2024": 0.7512480092382416, "2025": 0.008191054720335655}
  - regime_bar_pnl: {"CHOP": -2591.180279511693, "STRONG_TREND": 49419.630212683296, "VOL_EXPAND": 8165.328332741727}
  - decision: Discard (constraint fail)
- S6_VOLADX16_MAX28
  - params: {"vol_break_max_adx": 28.0, "vol_break_min_adx": 16.0}
  - metrics: ret=4.877010, sharpe=1.851402, mdd=-0.177954, win=0.239437
  - yearly_returns: {"2022": -0.065597721476498, "2023": 2.468003452296536, "2024": 0.8192762967746787, "2025": -0.0031166744048397588}
  - regime_bar_pnl: {"CHOP": 1000.1616087637249, "STRONG_TREND": 44005.64681536615, "VOL_EXPAND": 3764.287950596641}
  - decision: Discard (constraint fail)
- S7_REGRISK_ST110_V085
  - params: {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.85}
  - metrics: ret=6.234520, sharpe=1.925549, mdd=-0.161939, win=0.263473
  - yearly_returns: {"2022": -0.040107734976546405, "2023": 3.1317474799341944, "2024": 0.8086791303589609, "2025": 0.008537255667778076}
  - regime_bar_pnl: {"CHOP": -1851.578168582233, "STRONG_TREND": 53977.043834120166, "VOL_EXPAND": 10219.736770334668}
  - decision: Discard (constraint fail)
- S8_REGRISK_ST115_V080
  - params: {"risk_scale_strong_trend": 1.15, "risk_scale_vol_expand": 0.8}
  - metrics: ret=6.764324, sharpe=1.925538, mdd=-0.219235, win=0.260479
  - yearly_returns: {"2022": -0.10298969165013527, "2023": 3.627388450281037, "2024": 0.8547093217192954, "2025": 0.008542983183986497}
  - regime_bar_pnl: {"CHOP": -2205.9972057096384, "STRONG_TREND": 58313.89842210295, "VOL_EXPAND": 11535.340429101205}
  - decision: Discard (constraint fail)
- S9_COMBO_FILTER_RISK
  - params: {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.85, "vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015}
  - metrics: ret=5.667348, sharpe=1.874119, mdd=-0.155406, win=0.257053
  - yearly_returns: {"2022": -0.01532604582297703, "2023": 2.843063877684755, "2024": 0.7809982188648688, "2025": -0.010719159243787635}
  - regime_bar_pnl: {"CHOP": -1261.835780296511, "STRONG_TREND": 50888.8830647714, "VOL_EXPAND": 7046.434778423136}
  - decision: Discard (constraint fail)
- S10_COMBO_FILTER_RISK2
  - params: {"risk_scale_strong_trend": 1.1, "risk_scale_vol_expand": 0.8, "vol_break_min_adx": 18.0, "vol_break_min_ema_spread_atr": 0.02}
  - metrics: ret=6.025453, sharpe=1.914612, mdd=-0.153603, win=0.253918
  - yearly_returns: {"2022": -0.021362167756555417, "2023": 3.0339340462401747, "2024": 0.7827512443678608, "2025": -0.0017650130991133661}
  - regime_bar_pnl: {"CHOP": -1571.7707341108453, "STRONG_TREND": 53837.50527453089, "VOL_EXPAND": 7988.794957025846}
  - decision: Discard (constraint fail)
- S11_TRENDBUF015_VOLADX16
  - params: {"trend_entry_buffer_atr": 0.015, "vol_break_min_adx": 16.0, "vol_break_min_ema_spread_atr": 0.015}
  - metrics: ret=5.467629, sharpe=1.875163, mdd=-0.163396, win=0.254658
  - yearly_returns: {"2022": -0.016764783368266034, "2023": 2.7503983119901907, "2024": 0.7518620427300011, "2025": 0.001175830130833333}
  - regime_bar_pnl: {"CHOP": -1781.0717496871894, "STRONG_TREND": 48341.20170312483, "VOL_EXPAND": 8116.157018588565}
  - decision: Discard (constraint fail)
- S12_FLIP4_VOLADX16
  - params: {"flip_cooldown_bars": 4, "vol_break_min_adx": 16.0}
  - metrics: ret=5.578986, sharpe=1.874974, mdd=-0.163188, win=0.265060
  - yearly_returns: {"2022": -0.04453460211028282, "2023": 2.7978411710170334, "2024": 0.8183116113709126, "2025": -0.002899628193189341}
  - regime_bar_pnl: {"CHOP": -1681.6065898087581, "STRONG_TREND": 48557.734205869805, "VOL_EXPAND": 8913.730865174857}
  - decision: Discard (constraint fail)
- S13_FUNDING_OFF
  - params: {"funding_extreme": 1.0}
  - metrics: ret=6.278107, sharpe=1.924492, mdd=-0.182140, win=0.262195
  - yearly_returns: {"2022": -0.03241479145223436, "2023": 3.328221827017699, "2024": 0.7058612524213934, "2025": 0.018769696703226257}
  - regime_bar_pnl: {"CHOP": -4464.89490377979, "STRONG_TREND": 53641.80156040202, "VOL_EXPAND": 13604.166421337584}
  - decision: Discard (constraint fail)

### Final Selection
- Best stage: S1_VOLADX14
- Params: {"vol_break_min_adx": 14.0}
- Metrics: ret=6.605076, sharpe=1.964350, mdd=-0.163188, win=0.265060

### Robustness (Non-BTC symbols)
- BASELINE: symbols=BNBUSDT,SOLUSDT, ret=0.507640, sharpe=0.700473, mdd=-0.156622, win=0.260479
- BEST: symbols=BNBUSDT,SOLUSDT, ret=0.515805, sharpe=0.708958, mdd=-0.156622, win=0.261261

### Artifacts
- Stage table CSV: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\autonomous_trend_stage_table_20260304.csv
- Stage detail CSV: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\autonomous_trend_stage_detail_20260304.csv
- Robustness CSV: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\autonomous_trend_robustness_20260304.csv
### Stage2 Local Sweep (Winrate-first tie-break by Sharpe)
- Source CSV: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\Project_4h\autonomous_trend_stage2_sweep_20260304.csv
- Detail CSV (yearly/regime per run): C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\autonomous_trend_stage2_detail_20260304.csv
- Summary MD: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\AUTONOMOUS_TREND_OPT_STAGE2_20260304.md
- Best Stage2: `s2_adx13p0_buf0p02_mh2_cd3`
- Params: `vol_break_min_adx=13.0, trend_entry_buffer_atr=0.02, min_hold_bars=2, flip_cooldown_bars=3`
- Metrics: ret=6.662968, sharpe=1.966942, mdd=-0.163188, win=0.265060

### Stage2 Robustness (Non-BTC baskets)
- CSV: C:\Users\SAMSUNG\Downloads\Project_4h\Project_4h\Project_4h\autonomous_trend_robustness_stage2_20260304.csv
- basket_a(BNB,SOL): ADX13 and ADX14 tied.
- basket_b(XRP,BNB): ADX13 slightly better return/DD than ADX14.
- NOTE: Stage2 result supersedes Stage1 final selection; active preset now uses vol_break_min_adx=13.0.
