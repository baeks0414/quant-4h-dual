#!/usr/bin/env python3
"""
실시간 스테이트풀 페이퍼 트레이딩 - GitHub Actions 원샷 버전

paper_live_run.py 와의 차이:
- 바이낸스에서 최근 WARMUP_BARS봉을 실시간 fetch (과거 2025-04-12부터 전체 재계산 X)
- state.json 으로 포지션/마지막 봉 시간을 유지 → 실행 간 연속성
- 새 봉에서 발생한 거래만 incremental하게 기록

실행:
    python scripts/paper_live_stateful.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# GitHub Actions 환경: 캐시 완전 비활성화 → 항상 Binance 실시간 데이터
os.environ["QUANT_MEM_CACHE"]           = "0"
os.environ["QUANT_BT_USE_MEM_CACHE"]   = "0"
os.environ["QUANT_BT_PROGRESS_EVERY"]  = "0"
os.environ["QUANT_BT_SAVE_ARTIFACTS"]  = "0"

import pandas as pd

from quant.config.presets import (
    preset_dynamic_bear_state_trend,
    preset_balanced_alpha_sleeve_aggressive,
)
from quant.core.engine import Engine
from quant.core.market import update_market_regime_gate
from quant.core.metrics import compute_metrics
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.data.binance_fetch import fetch_klines, fetch_funding_rates, interval_to_ms
from quant.data.features import add_features, to_feature_rows
from quant.execution.paper_broker import PaperBroker
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy
from quant.util.state import load_state, save_state_atomic

# ── 상수 ─────────────────────────────────────────────────────────────
INITIAL_EQUITY = 10_000.0
TREND_WEIGHT   = 0.70
SLEEVE_WEIGHT  = 0.30
WARMUP_BARS    = 500          # 지표 초기화용 봉 수 (4h × 500 ≈ 83일)
OUTDIR         = ROOT / "results" / "paper_live_rt"
STATE_PATH     = OUTDIR / "state.json"
TRADES_PATH    = OUTDIR / "trades.csv"
EQUITY_PATH    = OUTDIR / "equity_curve.csv"
LOG_PATH       = OUTDIR / "run_log.csv"


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def _build_strategy(cfg):
    base = YourStrategy(cfg)
    if not cfg.enable_regime_gate:
        return base
    return MarketRegimeGate(
        base,
        MarketRegimeGateConfig(
            market_symbol=cfg.market_symbol,
            allow_regimes=cfg.allow_regimes,
            market_off_allow_symbol_regimes=getattr(cfg, "market_off_allow_symbol_regimes", ()),
            state_gate_symbol_regimes=getattr(cfg, "state_gate_symbol_regimes", ()),
            state_gate_allowed_market_regimes=getattr(cfg, "state_gate_allowed_market_regimes", ()),
            state_gate_min_drawdown=float(getattr(cfg, "state_gate_min_drawdown", -1.0)),
            state_gate_max_drawdown=float(getattr(cfg, "state_gate_max_drawdown", 0.0)),
            state_gate_min_market_adx=float(getattr(cfg, "state_gate_min_market_adx", 0.0)),
            state_gate_max_market_adx=float(getattr(cfg, "state_gate_max_market_adx", 100.0)),
            state_gate_min_market_ema_spread_atr=float(getattr(cfg, "state_gate_min_market_ema_spread_atr", 0.0)),
            state_gate_min_market_regime_streak=int(getattr(cfg, "state_gate_min_market_regime_streak", 1)),
            state_gate_max_market_regime_streak=int(getattr(cfg, "state_gate_max_market_regime_streak", 10_000)),
            bear_short_gate_allowed_market_regimes=getattr(cfg, "bear_short_gate_allowed_market_regimes", ()),
            bear_short_gate_min_market_adx=float(getattr(cfg, "bear_short_gate_min_market_adx", 0.0)),
            enable_conditional_trend_long_guard=bool(getattr(cfg, "enable_conditional_trend_long_guard", False)),
            trend_long_guard_allowed_market_regimes=getattr(cfg, "trend_long_guard_allowed_market_regimes", ("STRONG_TREND",)),
            trend_long_guard_symbol_spread_atr_min=float(getattr(cfg, "trend_long_guard_symbol_spread_atr_min", 0.0)),
            trend_long_guard_market_spread_atr_min=float(getattr(cfg, "trend_long_guard_market_spread_atr_min", 0.0)),
            trend_long_guard_market_regime_streak_min=int(getattr(cfg, "trend_long_guard_market_regime_streak_min", 0)),
            trend_long_guard_market_adx_max=float(getattr(cfg, "trend_long_guard_market_adx_max", 100.0)),
            entry_block_only=True,
        ),
    )


def fetch_live_bars(symbol: str, interval: str, n_bars: int) -> pd.DataFrame:
    """바이낸스에서 최근 n_bars봉을 실시간 fetch (캐시 없음)."""
    end   = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(milliseconds=interval_to_ms(interval) * (n_bars + 10))
    return fetch_klines(symbol, interval, _ms(start), _ms(end), use_cache=False)


def fetch_live_funding(symbol: str, days: int = 7) -> pd.DataFrame:
    end   = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(days=days)
    return fetch_funding_rates(symbol, _ms(start), _ms(end))


def main() -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print(f"  [PAPER RT] {now_utc}")
    print(f"  Trend({TREND_WEIGHT:.0%}) + Sleeve({SLEEVE_WEIGHT:.0%})")
    print(f"  최근 {WARMUP_BARS}봉 바이낸스 실시간 fetch")
    print("=" * 65)

    # ── 설정 ──────────────────────────────────────────────────────────
    trend_cfg  = preset_dynamic_bear_state_trend()
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    trend_cfg.initial_equity  = INITIAL_EQUITY * TREND_WEIGHT
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    symbols  = list(trend_cfg.symbols)
    interval = trend_cfg.interval

    # ── 이전 상태 로드 ────────────────────────────────────────────────
    state          = load_state(str(STATE_PATH))
    last_bar_time: pd.Timestamp | None = None
    if state.get("last_bar_time"):
        try:
            last_bar_time = pd.Timestamp(state["last_bar_time"]).tz_convert("UTC")
        except Exception:
            pass

    # ── 바이낸스 실시간 데이터 fetch ──────────────────────────────────
    print("\n[FETCH] 바이낸스에서 실시간 데이터 로딩 중...")
    price: dict[str, pd.DataFrame] = {}
    feat_t: dict[str, pd.DataFrame] = {}
    feat_s: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        price[sym] = fetch_live_bars(sym, interval, WARMUP_BARS)
        feat_t[sym] = add_features(price[sym], trend_cfg)
        feat_s[sym] = add_features(price[sym], sleeve_cfg)
        print(f"  {sym}: {len(price[sym])}봉  ({price[sym].index[0]} ~ {price[sym].index[-1]})")

    funding: dict[str, pd.DataFrame] = {s: fetch_live_funding(s) for s in symbols}

    # 마지막 봉 (아직 확정 안 된 현재 봉은 제외)
    # 가장 최근 완성 봉 = index[-2] (현재 진행중인 봉 = index[-1])
    # 단, 실행 직후라서 최신 봉이 방금 닫혔을 수도 있음 → index[-1] 사용
    latest_bar = feat_t[symbols[0]].index[-1]
    print(f"\n[BAR] 최신 확정 봉: {latest_bar}")

    if last_bar_time is not None and latest_bar <= last_bar_time:
        print(f"[SKIP] 이미 처리된 봉 ({latest_bar}). 새 봉 없음.")
        return

    # ── 엔진 구성 ─────────────────────────────────────────────────────
    t_strat  = _build_strategy(trend_cfg)
    s_strat  = _build_strategy(sleeve_cfg)
    t_risk   = VolScaledRiskManager(trend_cfg)  if trend_cfg.enable_vol_risk  else RiskManager(trend_cfg)
    s_risk   = VolScaledRiskManager(sleeve_cfg) if sleeve_cfg.enable_vol_risk else RiskManager(sleeve_cfg)
    t_port   = Portfolio(symbols=symbols, initial_cash=trend_cfg.initial_equity)
    s_port   = Portfolio(symbols=symbols, initial_cash=sleeve_cfg.initial_equity)
    t_engine = Engine(trend_cfg,  t_strat, PaperBroker(trend_cfg),  t_risk, t_port)
    s_engine = Engine(sleeve_cfg, s_strat, PaperBroker(sleeve_cfg), s_risk, s_port)

    # ── 전체 봉 replay (웜업 + 라이브) ───────────────────────────────
    print(f"\n[REPLAY] {WARMUP_BARS}봉 replay 중 (웜업 포함)...")
    mkt = trend_cfg.market_symbol
    all_times = feat_t[symbols[0]].index

    for t_idx, bar_t in enumerate(all_times):
        t_py = bar_t.to_pydatetime()

        # 마켓 레짐 업데이트
        if trend_cfg.enable_regime_gate:
            update_market_regime_gate(t_strat, mkt, feat_t[mkt], bar_t, equity=t_port.equity)
        if sleeve_cfg.enable_regime_gate:
            update_market_regime_gate(s_strat, mkt, feat_s[mkt], bar_t, equity=s_port.equity)

        # 펀딩 적용
        for sym in symbols:
            fdf = funding[sym]
            if fdf is not None and not fdf.empty:
                fdf_sub = fdf.loc[:bar_t]
                if not fdf_sub.empty:
                    rate = float(fdf_sub["fundingRate"].iloc[-1])
                    close_px = float(feat_t[sym].loc[bar_t, "close"])
                    t_port.update_close(sym, close_px)
                    t_port.apply_funding(t_py, sym, rate)
                    s_port.update_close(sym, close_px)
                    s_port.apply_funding(t_py, sym, rate)

        # on_bar
        for sym in symbols:
            fdf = funding[sym]
            fr = None
            if fdf is not None and not fdf.empty:
                fdf_sub = fdf.loc[:bar_t]
                if not fdf_sub.empty:
                    fr = float(fdf_sub["fundingRate"].iloc[-1])

            t_row = to_feature_rows(sym, feat_t[sym].loc[[bar_t]])[0]
            s_row = to_feature_rows(sym, feat_s[sym].loc[[bar_t]])[0]
            t_engine.on_bar(t_row, funding_rate=fr)
            s_engine.on_bar(s_row, funding_rate=fr)

        t_engine.snapshot_curve(t_py)
        s_engine.snapshot_curve(t_py)

    print("  replay 완료.")

    # ── 결과 추출 ─────────────────────────────────────────────────────
    t_res = t_engine.result()
    s_res = s_engine.result()

    all_trades = pd.concat([t_res.trades, s_res.trades], ignore_index=True)
    if not all_trades.empty and "time" in all_trades.columns:
        all_trades = all_trades.sort_values("time").reset_index(drop=True)

    # 이번 실행에서 새로 발생한 거래만 필터
    if last_bar_time is not None and not all_trades.empty and "time" in all_trades.columns:
        new_trades = all_trades[pd.to_datetime(all_trades["time"], utc=True) > last_bar_time]
    else:
        new_trades = all_trades

    # ── equity curve 합산 ─────────────────────────────────────────────
    t_ec = t_res.equity_curve[["equity"]].copy()
    s_ec = s_res.equity_curve[["equity"]].copy()
    t_ec.index = pd.to_datetime(t_ec.index, utc=True)
    s_ec.index = pd.to_datetime(s_ec.index, utc=True)
    idx = t_ec.index.intersection(s_ec.index)
    combined = pd.DataFrame(index=idx)
    combined["equity"] = t_ec.loc[idx, "equity"] + s_ec.loc[idx, "equity"]
    combined["drawdown"] = combined["equity"] / combined["equity"].cummax() - 1.0

    # ── 현재 포지션 ───────────────────────────────────────────────────
    def side_str(side: int) -> str:
        return {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(side, "FLAT")

    t_positions = {sym: side_str(t_port.positions[sym].side) for sym in symbols}
    s_positions = {sym: side_str(s_port.positions[sym].side) for sym in symbols}
    t_regime = getattr(t_strat, "last_market_regime", None)

    # ── 지표 계산 ─────────────────────────────────────────────────────
    metrics = compute_metrics(combined, all_trades, INITIAL_EQUITY, interval)
    final_eq  = metrics.get("final_equity", combined["equity"].iloc[-1])
    total_ret = metrics.get("total_return", 0.0)
    mdd       = metrics.get("max_drawdown", 0.0)
    sharpe    = metrics.get("sharpe", 0.0)

    # ── CSV 저장 (누적) ───────────────────────────────────────────────
    # trades: 이전 기록 + 신규 거래 누적
    if TRADES_PATH.exists() and not new_trades.empty:
        old_trades = pd.read_csv(TRADES_PATH)
        combined_trades = pd.concat([old_trades, new_trades], ignore_index=True)
        combined_trades.to_csv(TRADES_PATH, index=False)
    elif not new_trades.empty:
        new_trades.to_csv(TRADES_PATH, index=False)
    elif not TRADES_PATH.exists() and not all_trades.empty:
        all_trades.to_csv(TRADES_PATH, index=False)

    # equity curve: 최신 전체 저장
    combined.to_csv(EQUITY_PATH)

    # run_log: 매 실행마다 한 줄 추가
    log_row = {
        "run_time":        now_utc,
        "latest_bar":      str(latest_bar),
        "total_return":    round(total_ret, 6),
        "final_equity":    round(final_eq, 2),
        "max_drawdown":    round(mdd, 6),
        "sharpe":          round(sharpe, 6),
        "num_trades":      len(all_trades),
        "new_trades":      len(new_trades),
        "trend_pos_BTC":   t_positions.get("BTCUSDT", "FLAT"),
        "trend_pos_ETH":   t_positions.get("ETHUSDT", "FLAT"),
        "sleeve_pos_BTC":  s_positions.get("BTCUSDT", "FLAT"),
        "sleeve_pos_ETH":  s_positions.get("ETHUSDT", "FLAT"),
        "market_regime":   str(t_regime),
    }
    log_df = pd.DataFrame([log_row])
    if LOG_PATH.exists():
        log_df = pd.concat([pd.read_csv(LOG_PATH), log_df], ignore_index=True)
    log_df.to_csv(LOG_PATH, index=False)

    # ── state.json 업데이트 ───────────────────────────────────────────
    state["last_bar_time"]    = str(latest_bar)
    state["trend_positions"]  = t_positions
    state["sleeve_positions"] = s_positions
    state["market_regime"]    = str(t_regime)
    state["final_equity"]     = round(final_eq, 2)
    state["total_return"]     = round(total_ret, 6)
    save_state_atomic(str(STATE_PATH), state)

    # ── 출력 ─────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  [결과]")
    print(f"  최신 봉     : {latest_bar}")
    print(f"  BTC 레짐    : {t_regime}")
    print(f"  Trend 포지션: {t_positions}")
    print(f"  Sleeve 포지션: {s_positions}")
    print(f"  ─────────────────────────────────────────────────────")
    print(f"  총수익률    : {total_ret*100:+.2f}%")
    print(f"  최종자산    : ${final_eq:>10,.2f}")
    print(f"  MDD         : {mdd*100:.2f}%")
    print(f"  Sharpe      : {sharpe:.4f}")
    print(f"  전체 거래수 : {len(all_trades)}건  (이번 실행 신규: {len(new_trades)}건)")
    print(f"\n  저장: {OUTDIR}/")


if __name__ == "__main__":
    main()
