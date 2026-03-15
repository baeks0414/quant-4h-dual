#!/usr/bin/env python3
"""
실시간 스테이트풀 페이퍼 트레이딩 - GitHub Actions 원샷 버전

동작 방식:
- 바이낸스에서 최근 WARMUP_BARS봉을 live fetch → 지표(EMA/ATR/ADX) 웜업용
- 수익/거래 추적은 첫 실행 시점(live_start)부터만 집계
- state.json에 live_start, last_bar_time, 포지션 등을 저장 → 실행 간 연속성
- 바이낸스 API 장애 시 최대 3회 재시도 (지수 백오프)
- 실행 완료/실패 시 텔레그램 알림

환경변수:
    TELEGRAM_TOKEN    텔레그램 봇 토큰 (GitHub Secret)
    TELEGRAM_CHAT_ID  텔레그램 채팅 ID (GitHub Secret)

실행:
    python scripts/paper_live_stateful.py
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# GitHub Actions 환경: 캐시 완전 비활성화 → 항상 Binance 실시간 데이터
os.environ["QUANT_MEM_CACHE"]          = "0"
os.environ["QUANT_BT_USE_MEM_CACHE"]  = "0"
os.environ["QUANT_BT_PROGRESS_EVERY"] = "0"
os.environ["QUANT_BT_SAVE_ARTIFACTS"] = "0"

import requests
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
MAX_RETRIES    = 3            # 바이낸스 API 재시도 횟수
RETRY_DELAY    = 10           # 재시도 초기 대기 시간 (초, 지수 백오프)
OUTDIR         = ROOT / "results" / "paper_live_rt"
STATE_PATH     = OUTDIR / "state.json"
STATE_BACKUP   = OUTDIR / "state_backup.json"   # live_start 유실 대비 백업
TRADES_PATH    = OUTDIR / "trades.csv"
EQUITY_PATH    = OUTDIR / "equity_curve.csv"
LOG_PATH       = OUTDIR / "run_log.csv"

# ── 텔레그램 ─────────────────────────────────────────────────────────
TG_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def tg_send(text: str) -> None:
    """텔레그램 메시지 전송. 실패해도 전체 스크립트를 중단하지 않음."""
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        print(f"[TG] 알림 전송 실패 (무시): {e}")


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
    """바이낸스에서 최근 n_bars봉을 실시간 fetch. 실패 시 최대 MAX_RETRIES 재시도."""
    end   = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(milliseconds=interval_to_ms(interval) * (n_bars + 10))
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_klines(symbol, interval, _ms(start), _ms(end), use_cache=False)
        except Exception as e:
            last_exc = e
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            print(f"  [RETRY {attempt}/{MAX_RETRIES}] {symbol} fetch 실패: {e} → {wait}초 후 재시도")
            time.sleep(wait)
    raise RuntimeError(f"{symbol} 데이터 fetch 실패 ({MAX_RETRIES}회 재시도): {last_exc}")


def fetch_live_funding(symbol: str, days: int = 7) -> pd.DataFrame:
    end   = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(days=days)
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return fetch_funding_rates(symbol, _ms(start), _ms(end))
        except Exception as e:
            last_exc = e
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            print(f"  [RETRY {attempt}/{MAX_RETRIES}] {symbol} funding fetch 실패: {e} → {wait}초 후 재시도")
            time.sleep(wait)
    print(f"  [WARN] {symbol} funding fetch 최종 실패 → 빈 DataFrame 사용")
    return pd.DataFrame()


def main() -> None:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUTDIR.mkdir(parents=True, exist_ok=True)

    # ── 설정 ──────────────────────────────────────────────────────────
    trend_cfg  = preset_dynamic_bear_state_trend()
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()
    trend_cfg.initial_equity  = INITIAL_EQUITY * TREND_WEIGHT
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    symbols  = list(trend_cfg.symbols)
    interval = trend_cfg.interval

    # ── 이전 상태 로드 (백업에서 복구 포함) ──────────────────────────
    state = load_state(str(STATE_PATH))

    # state.json이 비어있거나 live_start가 없으면 백업에서 복구 시도
    if "live_start" not in state and STATE_BACKUP.exists():
        backup = load_state(str(STATE_BACKUP))
        if "live_start" in backup:
            print("[RECOVER] state.json에 live_start 없음 → 백업에서 복구")
            state["live_start"] = backup["live_start"]
            tg_send(
                f"⚠️ <b>상태 복구</b>\n"
                f"state.json 손상 감지 → 백업에서 live_start 복구\n"
                f"live_start: {backup['live_start']}"
            )

    last_bar_time: pd.Timestamp | None = None
    live_start:    pd.Timestamp | None = None
    is_first_run  = "live_start" not in state

    if state.get("last_bar_time"):
        try:
            last_bar_time = pd.Timestamp(state["last_bar_time"]).tz_convert("UTC")
        except Exception:
            pass
    if state.get("live_start"):
        try:
            live_start = pd.Timestamp(state["live_start"]).tz_convert("UTC")
        except Exception:
            pass

    print("=" * 65)
    print(f"  [PAPER RT] {now_utc}{'  [첫 실행 - 시작점 설정]' if is_first_run else ''}")
    print(f"  Trend({TREND_WEIGHT:.0%}) + Sleeve({SLEEVE_WEIGHT:.0%})")
    if live_start:
        print(f"  live_start : {live_start}")
    print("=" * 65)

    # ── 바이낸스 실시간 데이터 fetch (재시도 포함) ────────────────────
    print("\n[FETCH] 바이낸스에서 실시간 데이터 로딩 중...")
    try:
        price: dict[str, pd.DataFrame] = {}
        feat_t: dict[str, pd.DataFrame] = {}
        feat_s: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            price[sym]  = fetch_live_bars(sym, interval, WARMUP_BARS)
            feat_t[sym] = add_features(price[sym], trend_cfg)
            feat_s[sym] = add_features(price[sym], sleeve_cfg)
            print(f"  {sym}: {len(price[sym])}봉  ({price[sym].index[0]} ~ {price[sym].index[-1]})")
        funding: dict[str, pd.DataFrame] = {s: fetch_live_funding(s) for s in symbols}
    except Exception as e:
        err_msg = f"❌ [Paper Trading] 데이터 fetch 실패\n{now_utc}\n{e}"
        print(err_msg)
        tg_send(err_msg)
        raise

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

    # ── 전체 봉 replay (웜업 포함) ────────────────────────────────────
    print(f"\n[REPLAY] {WARMUP_BARS}봉 replay 중 (지표 웜업)...")
    mkt       = trend_cfg.market_symbol
    all_times = feat_t[symbols[0]].index

    for bar_t in all_times:
        t_py = bar_t.to_pydatetime()

        if trend_cfg.enable_regime_gate:
            update_market_regime_gate(t_strat, mkt, feat_t[mkt], bar_t, equity=t_port.equity)
        if sleeve_cfg.enable_regime_gate:
            update_market_regime_gate(s_strat, mkt, feat_s[mkt], bar_t, equity=s_port.equity)

        for sym in symbols:
            fdf = funding[sym]
            if fdf is not None and not fdf.empty:
                fdf_sub = fdf.loc[:bar_t]
                if not fdf_sub.empty:
                    rate     = float(fdf_sub["fundingRate"].iloc[-1])
                    close_px = float(feat_t[sym].loc[bar_t, "close"])
                    t_port.update_close(sym, close_px)
                    t_port.apply_funding(t_py, sym, rate)
                    s_port.update_close(sym, close_px)
                    s_port.apply_funding(t_py, sym, rate)

        for sym in symbols:
            fdf = funding[sym]
            fr  = None
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

    # ── live_start 설정 (첫 실행이면 현재 봉으로 고정) ───────────────
    if is_first_run:
        live_start = latest_bar
        state["live_start"] = str(live_start)
        print(f"\n[INIT] 페이퍼 트레이딩 시작점 설정: {live_start}")

    # ── 결과 추출 (live_start 이후만) ────────────────────────────────
    t_res = t_engine.result()
    s_res = s_engine.result()

    t_trades_df = t_res.trades.copy()
    s_trades_df = s_res.trades.copy()
    t_trades_df["strategy"] = "Trend"
    s_trades_df["strategy"] = "Sleeve"
    all_trades = pd.concat([t_trades_df, s_trades_df], ignore_index=True)
    if not all_trades.empty and "time" in all_trades.columns:
        all_trades["time"] = pd.to_datetime(all_trades["time"], utc=True)
        all_trades = all_trades.sort_values("time").reset_index(drop=True)

    if live_start is not None and not all_trades.empty and "time" in all_trades.columns:
        live_trades = all_trades[all_trades["time"] > live_start].copy()
    else:
        live_trades = pd.DataFrame()

    if last_bar_time is not None and not live_trades.empty:
        new_trades = live_trades[live_trades["time"] > last_bar_time]
    else:
        new_trades = live_trades

    # ── equity curve: live_start 기준으로 정규화 ──────────────────────
    t_ec = t_res.equity_curve[["equity"]].copy()
    s_ec = s_res.equity_curve[["equity"]].copy()
    t_ec.index = pd.to_datetime(t_ec.index, utc=True)
    s_ec.index = pd.to_datetime(s_ec.index, utc=True)
    idx      = t_ec.index.intersection(s_ec.index)
    combined = pd.DataFrame(index=idx)
    combined["equity"] = t_ec.loc[idx, "equity"] + s_ec.loc[idx, "equity"]

    if live_start is not None:
        live_ec = combined[combined.index >= live_start].copy()
        if not live_ec.empty:
            scale = INITIAL_EQUITY / live_ec["equity"].iloc[0]
            live_ec["equity"] = live_ec["equity"] * scale
        else:
            live_ec = combined.copy()
            live_ec["equity"] = INITIAL_EQUITY
    else:
        live_ec = combined.copy()
        live_ec["equity"] = live_ec["equity"] / live_ec["equity"].iloc[0] * INITIAL_EQUITY

    live_ec["drawdown"] = live_ec["equity"] / live_ec["equity"].cummax() - 1.0

    # ── 지표 계산 ─────────────────────────────────────────────────────
    if not live_trades.empty:
        metrics   = compute_metrics(live_ec, live_trades, INITIAL_EQUITY, interval)
        total_ret = metrics.get("total_return", 0.0)
        mdd       = metrics.get("max_drawdown", 0.0)
        sharpe    = metrics.get("sharpe", 0.0)
    else:
        total_ret = float(live_ec["equity"].iloc[-1]) / INITIAL_EQUITY - 1.0
        mdd       = float(live_ec["drawdown"].min())
        sharpe    = 0.0

    final_eq = float(live_ec["equity"].iloc[-1])

    # ── 현재 포지션 ───────────────────────────────────────────────────
    def side_str(side: int) -> str:
        return {1: "LONG", -1: "SHORT", 0: "FLAT"}.get(side, "FLAT")

    t_positions = {sym: side_str(t_port.positions[sym].side) for sym in symbols}
    s_positions = {sym: side_str(s_port.positions[sym].side) for sym in symbols}
    t_regime    = getattr(t_strat, "last_market_regime", None)

    # ── CSV 저장 ──────────────────────────────────────────────────────
    if not live_trades.empty:
        live_trades.to_csv(TRADES_PATH, index=False)
    live_ec.to_csv(EQUITY_PATH)

    log_row = {
        "run_time":        now_utc,
        "live_start":      str(live_start),
        "latest_bar":      str(latest_bar),
        "total_return":    round(total_ret, 6),
        "final_equity":    round(final_eq, 2),
        "max_drawdown":    round(mdd, 6),
        "sharpe":          round(sharpe, 6),
        "num_live_trades": len(live_trades),
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

    # live_start 백업 (절대 변하지 않는 값만 저장)
    backup = load_state(str(STATE_BACKUP))
    if "live_start" not in backup and live_start:
        backup["live_start"] = str(live_start)
        save_state_atomic(str(STATE_BACKUP), backup)
        print(f"[BACKUP] live_start 백업 저장: {live_start}")

    # ── 콘솔 출력 ─────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print(f"  [결과]{'  [첫 실행 - 앞으로 이 시점부터 추적]' if is_first_run else ''}")
    print(f"  페이퍼 시작 : {live_start}")
    print(f"  최신 봉     : {latest_bar}")
    print(f"  BTC 레짐    : {t_regime}")
    print(f"  Trend 포지션: {t_positions}")
    print(f"  Sleeve 포지션: {s_positions}")
    print(f"  ─────────────────────────────────────────────────────")
    if is_first_run:
        print(f"  수익률/MDD  : (다음 봉부터 집계 시작)")
    else:
        print(f"  총수익률    : {total_ret*100:+.2f}%  ($10,000 → ${final_eq:,.2f})")
        print(f"  MDD         : {mdd*100:.2f}%")
        print(f"  Sharpe      : {sharpe:.4f}")
    print(f"  live 거래수 : {len(live_trades)}건  (이번 신규: {len(new_trades)}건)")
    print(f"\n  저장: {OUTDIR}/")

    # ── 텔레그램 알림 ─────────────────────────────────────────────────
    pos_icon = {"LONG": "🟢", "SHORT": "🔴", "FLAT": "⚪"}
    regime_icon = {
        "STRONG_TREND": "🚀", "STRONG_TREND_BEAR": "🐻",
        "VOL_EXPAND": "⚡", "CHOP": "〰️",
    }.get(str(t_regime), "❓")

    if is_first_run:
        tg_msg = (
            f"🚀 <b>Paper Trading 시작</b>\n"
            f"📅 {now_utc}\n"
            f"─────────────────\n"
            f"시작 시점: {latest_bar}\n"
            f"{regime_icon} 레짐: <b>{t_regime}</b>\n\n"
            f"<b>Trend (70%)</b>\n"
            f"  BTC: {pos_icon.get(t_positions.get('BTCUSDT','FLAT'), '⚪')} {t_positions.get('BTCUSDT','FLAT')}\n"
            f"  ETH: {pos_icon.get(t_positions.get('ETHUSDT','FLAT'), '⚪')} {t_positions.get('ETHUSDT','FLAT')}\n"
            f"<b>Sleeve (30%)</b>\n"
            f"  BTC: {pos_icon.get(s_positions.get('BTCUSDT','FLAT'), '⚪')} {s_positions.get('BTCUSDT','FLAT')}\n"
            f"  ETH: {pos_icon.get(s_positions.get('ETHUSDT','FLAT'), '⚪')} {s_positions.get('ETHUSDT','FLAT')}\n\n"
            f"다음 봉부터 수익 집계 시작 💰"
        )
    else:
        ret_icon = "📈" if total_ret >= 0 else "📉"

        # ── 신규 거래 상세 ─────────────────────────────────────────────
        type_label = {
            "ENTRY_LONG":    ("🟢 롱 진입",   False),
            "ENTRY_SHORT":   ("🔴 숏 진입",   False),
            "PYRAMID_LONG":  ("🟢 롱 추가",   False),
            "PYRAMID_SHORT": ("🔴 숏 추가",   False),
            "EXIT":          ("✅ 익절 청산",  True),
            "STOP_LONG":     ("🛑 롱 손절",   True),
            "STOP_SHORT":    ("🛑 숏 손절",   True),
            "CLOSE_BY_SIGNAL":("⚡ 시그널 청산", True),
            "FLIP_CLOSE":    ("🔄 반전 청산",  True),
            "FUNDING":       ("💸 펀딩비",     False),
        }
        sym_short = {"BTCUSDT": "BTC", "ETHUSDT": "ETH"}

        # 홀딩 기간 계산용: 심볼+진입가 기준으로 가장 최근 ENTRY 시각 조회
        def find_hold_hours(tr_row, all_live: pd.DataFrame) -> str | None:
            t_type = str(tr_row.get("type", ""))
            if t_type not in ("EXIT", "STOP_LONG", "STOP_SHORT", "CLOSE_BY_SIGNAL", "FLIP_CLOSE"):
                return None
            sym = tr_row.get("symbol")
            ep  = tr_row.get("entry")
            if ep is None or pd.isna(ep):
                return None
            ep_f = float(ep)
            entries = all_live[
                all_live["symbol"].eq(sym) &
                all_live["type"].isin(["ENTRY_LONG", "ENTRY_SHORT", "PYRAMID_LONG", "PYRAMID_SHORT"]) &
                (all_live["entry"].sub(ep_f).abs() < 1.0)
            ]
            if entries.empty:
                return None
            entry_time = pd.to_datetime(entries["time"].min(), utc=True)
            exit_time  = pd.to_datetime(tr_row.get("time"), utc=True)
            delta = exit_time - entry_time
            total_h = int(delta.total_seconds() // 3600)
            if total_h >= 24:
                d, h = divmod(total_h, 24)
                return f"{d}d {h}h" if h else f"{d}d"
            return f"{total_h}h"

        new_trade_str = ""
        if len(new_trades) > 0:
            lines = [f"\n🔔 <b>신규 거래 {len(new_trades)}건</b>"]
            for _, tr in new_trades.iterrows():
                t_type = str(tr.get("type", ""))
                label, has_exit = type_label.get(t_type, (t_type, False))
                sym  = sym_short.get(str(tr.get("symbol", "")), str(tr.get("symbol", "")))
                strat = str(tr.get("strategy", ""))
                qty  = float(tr.get("qty", 0))
                pnl  = float(tr.get("pnl", 0)) if tr.get("pnl") is not None else 0.0
                entry_p = tr.get("entry")
                exit_p  = tr.get("exit")
                hold    = find_hold_hours(tr, live_trades)

                line = f"  [{strat}] {sym} {label}"
                if entry_p is not None and not pd.isna(entry_p):
                    line += f"\n    진입가: ${float(entry_p):,.2f}"
                if has_exit and exit_p is not None and not pd.isna(exit_p):
                    line += f" → 청산가: ${float(exit_p):,.2f}"
                if hold:
                    line += f"  ⏱ {hold}"
                if qty > 0:
                    notional = qty * float(entry_p if entry_p else 0)
                    line += f"\n    수량: {qty:.4f} {sym}  (≈${notional:,.0f})"
                if has_exit or t_type == "FUNDING":
                    pnl_icon = "💰" if pnl >= 0 else "💸"
                    line += f"\n    손익: {pnl_icon} <b>${pnl:+,.2f}</b>"
                lines.append(line)
            new_trade_str = "\n" + "\n".join(lines)

        tg_msg = (
            f"{ret_icon} <b>Paper Trading 업데이트</b>\n"
            f"📅 {now_utc}\n"
            f"─────────────────\n"
            f"{regime_icon} 레짐: <b>{t_regime}</b>\n\n"
            f"<b>Trend (70%)</b>\n"
            f"  BTC: {pos_icon.get(t_positions.get('BTCUSDT','FLAT'), '⚪')} {t_positions.get('BTCUSDT','FLAT')}\n"
            f"  ETH: {pos_icon.get(t_positions.get('ETHUSDT','FLAT'), '⚪')} {t_positions.get('ETHUSDT','FLAT')}\n"
            f"<b>Sleeve (30%)</b>\n"
            f"  BTC: {pos_icon.get(s_positions.get('BTCUSDT','FLAT'), '⚪')} {s_positions.get('BTCUSDT','FLAT')}\n"
            f"  ETH: {pos_icon.get(s_positions.get('ETHUSDT','FLAT'), '⚪')} {s_positions.get('ETHUSDT','FLAT')}\n"
            f"─────────────────\n"
            f"💰 수익률: <b>{total_ret*100:+.2f}%</b>  (${final_eq:,.0f})\n"
            f"📊 MDD: {mdd*100:.2f}%  |  Sharpe: {sharpe:.2f}\n"
            f"📋 누적 거래: {len(live_trades)}건{new_trade_str}"
        )

    tg_send(tg_msg)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        tg_send(f"❌ <b>Paper Trading 오류</b>\n📅 {now_utc}\n\n{e}")
        raise
