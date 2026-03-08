#!/usr/bin/env python3
"""
가상 라이브 페이퍼 트레이딩 - 듀얼 콤보
채택된 전략: preset_dynamic_bear_state_trend (70%) + preset_balanced_alpha_sleeve_aggressive (30%)
실시간 바이낸스 가격 수신, 실제 주문 없음.

실행:
    python -m quant.cli.paper_dual
    python -m quant.cli.paper_dual --poll 30 --outdir results/paper_dual
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime

import pandas as pd

from quant.config.presets import (
    preset_dynamic_bear_state_trend,
    preset_balanced_alpha_sleeve_aggressive,
)
from quant.core.clock import BarClock
from quant.core.engine import Engine
from quant.core.market import update_market_regime_gate
from quant.core.metrics import compute_metrics
from quant.core.portfolio import Portfolio
from quant.core.risk import RiskManager
from quant.core.risk_vol import VolScaledRiskManager
from quant.data.binance_fetch import fetch_klines, fetch_funding_rates, interval_to_ms
from quant.data.loaders import add_features, to_feature_rows
from quant.execution.paper_broker import PaperBroker
from quant.reporting.artifacts import save_csvs
from quant.strategies.wrappers import MarketRegimeGate, MarketRegimeGateConfig
from quant.strategies.your_strategy import YourStrategy
from quant.util.state import load_state, save_state_atomic


TREND_WEIGHT  = 0.70
SLEEVE_WEIGHT = 0.30
INITIAL_EQUITY = 10_000.0


def _ms(ts: pd.Timestamp) -> int:
    return int(ts.timestamp() * 1000)


def _side_str(side) -> str:
    if side == 0:   return "FLAT"
    if side > 0:    return "LONG"
    return "SHORT"


def _update_price_cache(symbol: str, interval: str, cache: pd.DataFrame,
                        keep_rows: int, initial_days: int) -> pd.DataFrame:
    end = pd.Timestamp.now("UTC")
    if cache is None or cache.empty:
        start = end - pd.Timedelta(days=initial_days)
        df = fetch_klines(symbol, interval, _ms(start), _ms(end))
    else:
        last = cache.index[-1]
        start = last - pd.Timedelta(milliseconds=interval_to_ms(interval) * 5)
        df_new = fetch_klines(symbol, interval, _ms(start), _ms(end))
        df = pd.concat([cache, df_new])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    if len(df) > keep_rows:
        df = df.iloc[-keep_rows:]
    return df


def _fetch_funding_recent(symbol: str, days: int = 7) -> pd.DataFrame:
    end = pd.Timestamp.now("UTC")
    start = end - pd.Timedelta(days=days)
    return fetch_funding_rates(symbol, _ms(start), _ms(end))


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


def run_paper_dual(
    poll_seconds: int = 30,
    outdir: str = "results/paper_dual",
    state_path: str = "results/paper_dual/state.json",
    keep_rows: int = 2500,
    initial_days: int = 120,
    save_every_bars: int = 10,
) -> None:
    # ── 설정 ──────────────────────────────────────────
    trend_cfg  = preset_dynamic_bear_state_trend()
    sleeve_cfg = preset_balanced_alpha_sleeve_aggressive()

    trend_cfg.initial_equity  = INITIAL_EQUITY * TREND_WEIGHT
    sleeve_cfg.initial_equity = INITIAL_EQUITY * SLEEVE_WEIGHT

    symbols  = list(trend_cfg.symbols)   # BTCUSDT, ETHUSDT
    interval = trend_cfg.interval        # 4h

    # ── 엔진 구성 ──────────────────────────────────────
    trend_strategy  = _build_strategy(trend_cfg)
    sleeve_strategy = _build_strategy(sleeve_cfg)

    trend_risk   = VolScaledRiskManager(trend_cfg)  if trend_cfg.enable_vol_risk  else RiskManager(trend_cfg)
    sleeve_risk  = VolScaledRiskManager(sleeve_cfg) if sleeve_cfg.enable_vol_risk else RiskManager(sleeve_cfg)

    trend_portfolio  = Portfolio(symbols=symbols, initial_cash=trend_cfg.initial_equity)
    sleeve_portfolio = Portfolio(symbols=symbols, initial_cash=sleeve_cfg.initial_equity)

    trend_engine  = Engine(trend_cfg,  trend_strategy,  PaperBroker(trend_cfg),  trend_risk,  trend_portfolio)
    sleeve_engine = Engine(sleeve_cfg, sleeve_strategy, PaperBroker(sleeve_cfg), sleeve_risk, sleeve_portfolio)

    # ── 캐시 초기화 ────────────────────────────────────
    price_cache: dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}
    feat_trend:  dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}
    feat_sleeve: dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}
    funding_cache: dict[str, pd.DataFrame] = {s: pd.DataFrame() for s in symbols}

    # ── 상태 복원 ──────────────────────────────────────
    state = load_state(state_path)
    last_bar_time: pd.Timestamp | None = None
    if state.get("last_bar_time"):
        try:
            last_bar_time = pd.Timestamp(state["last_bar_time"]).tz_convert("UTC")
        except Exception:
            pass

    clock = BarClock(interval=interval, symbols=symbols, settle_lag_seconds=3)
    bar_count = 0

    print("=" * 65)
    print("  [PAPER DUAL] 가상 라이브 시작")
    print(f"  전략: Trend({TREND_WEIGHT:.0%}) + Sleeve({SLEEVE_WEIGHT:.0%})")
    print(f"  심볼: {symbols}  |  인터벌: {interval}")
    print(f"  초기자본: ${INITIAL_EQUITY:,.0f}  |  poll: {poll_seconds}s")
    print(f"  상태파일: {state_path}")
    print("=" * 65)

    # 초기 가격 데이터 로드
    print("[INIT] 바이낸스에서 초기 가격 데이터 로딩 중...")
    for s in symbols:
        price_cache[s] = _update_price_cache(s, interval, pd.DataFrame(), keep_rows, initial_days)
        feat_trend[s]  = add_features(price_cache[s], trend_cfg)
        feat_sleeve[s] = add_features(price_cache[s], sleeve_cfg)
        print(f"  {s}: {len(price_cache[s])}봉 로드 완료 (마지막: {price_cache[s].index[-1]})")
    print("[INIT] 완료. 다음 봉 확정을 기다립니다...\n")

    while True:
        try:
            t = clock.confirm_closed_bar_time()
            if t is None:
                time.sleep(poll_seconds)
                continue

            if last_bar_time is not None and t <= last_bar_time:
                time.sleep(poll_seconds)
                continue

            last_bar_time = t
            t_py: datetime = t.to_pydatetime()
            bar_count += 1
            state["last_bar_time"] = str(last_bar_time)
            save_state_atomic(state_path, state)

            # 1) 가격 + 피처 업데이트
            for s in symbols:
                price_cache[s] = _update_price_cache(s, interval, price_cache[s], keep_rows, initial_days)
                feat_trend[s]  = add_features(price_cache[s], trend_cfg)
                feat_sleeve[s] = add_features(price_cache[s], sleeve_cfg)

            # 2) 펀딩 업데이트
            for s in symbols:
                funding_cache[s] = _fetch_funding_recent(s, days=7)

            # 3) 펀딩 적용
            for s in symbols:
                fdf = funding_cache[s]
                if fdf is None or fdf.empty:
                    continue
                fdf_sub = fdf.loc[:t]
                if fdf_sub.empty:
                    continue
                rate = float(fdf_sub["fundingRate"].iloc[-1])
                close_px = float(feat_trend[s].loc[t, "close"])
                trend_portfolio.update_close(s, close_px)
                trend_portfolio.apply_funding(t_py, s, rate)
                sleeve_portfolio.update_close(s, close_px)
                sleeve_portfolio.apply_funding(t_py, s, rate)

            # 4) 마켓 레짐 업데이트 (각 전략 독립)
            mkt = trend_cfg.market_symbol
            if trend_cfg.enable_regime_gate:
                update_market_regime_gate(trend_strategy,  mkt, feat_trend[mkt],  t, equity=trend_portfolio.equity)
            if sleeve_cfg.enable_regime_gate:
                update_market_regime_gate(sleeve_strategy, mkt, feat_sleeve[mkt], t, equity=sleeve_portfolio.equity)

            # 5) on_bar
            for s in symbols:
                fdf = funding_cache[s]
                fr = None
                if fdf is not None and not fdf.empty:
                    fdf_sub = fdf.loc[:t]
                    if not fdf_sub.empty:
                        fr = float(fdf_sub["fundingRate"].iloc[-1])

                trend_row  = to_feature_rows(s, feat_trend[s].loc[[t]])[0]
                sleeve_row = to_feature_rows(s, feat_sleeve[s].loc[[t]])[0]
                trend_engine.on_bar(trend_row,   funding_rate=fr)
                sleeve_engine.on_bar(sleeve_row, funding_rate=fr)

            trend_engine.snapshot_curve(t_py)
            sleeve_engine.snapshot_curve(t_py)

            # 6) 상태 출력
            t_eq   = trend_portfolio.equity
            s_eq   = sleeve_portfolio.equity
            c_eq   = t_eq + s_eq
            t_pnl  = t_eq - trend_cfg.initial_equity
            s_pnl  = s_eq - sleeve_cfg.initial_equity
            c_pnl  = c_eq - INITIAL_EQUITY
            c_ret  = c_pnl / INITIAL_EQUITY

            t_pos = {s: _side_str(trend_portfolio.positions[s].side)  for s in symbols}
            s_pos = {s: _side_str(sleeve_portfolio.positions[s].side) for s in symbols}
            t_reg = getattr(trend_strategy,  "last_market_regime", None)
            t_on  = getattr(trend_strategy,  "market_on", None)

            print(f"\n{'─'*65}")
            print(f"  [{t}]  Bar #{bar_count}")
            print(f"  BTC레짐: {t_reg}  |  마켓ON: {t_on}")
            print(f"  Trend  ({TREND_WEIGHT:.0%}): ${t_eq:>10,.2f}  PnL {t_pnl:+,.2f}  pos={t_pos}")
            print(f"  Sleeve ({SLEEVE_WEIGHT:.0%}): ${s_eq:>10,.2f}  PnL {s_pnl:+,.2f}  pos={s_pos}")
            print(f"  ──────────────────────────────────────────────────────")
            print(f"  Combined:  ${c_eq:>10,.2f}  PnL {c_pnl:+,.2f}  ({c_ret:+.2%})")

            # 7) 자동 저장
            if save_every_bars > 0 and bar_count % save_every_bars == 0:
                tr = trend_engine.result()
                sr = sleeve_engine.result()
                save_csvs(tr.equity_curve, tr.trades, outdir, "trend_live")
                save_csvs(sr.equity_curve, sr.trades, outdir, "sleeve_live")
                print(f"  [SAVED] {outdir}/")

            time.sleep(poll_seconds)

        except KeyboardInterrupt:
            print("\n\n[PAPER DUAL] Ctrl+C 감지 - 최종 결과 저장 중...")
            break
        except Exception as e:
            print(f"[ERROR] {repr(e)}")
            time.sleep(poll_seconds)

    # ── 최종 결과 ──────────────────────────────────────
    tr = trend_engine.result()
    sr = sleeve_engine.result()

    save_csvs(tr.equity_curve, tr.trades, outdir, "trend_live_final")
    save_csvs(sr.equity_curve, sr.trades, outdir, "sleeve_live_final")

    print("\n===== 최종 결과 =====")
    for label, res, init in [("Trend", tr, trend_cfg.initial_equity), ("Sleeve", sr, sleeve_cfg.initial_equity)]:
        m = compute_metrics(res.equity_curve, res.trades, init, interval)
        print(f"\n[{label}]")
        for k, v in m.items():
            print(f"  {k:20s}: {v:.6f}" if isinstance(v, float) else f"  {k:20s}: {v}")
    print(f"\n저장 완료: {outdir}/")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("quant-paper-dual")
    p.add_argument("--poll",         type=int,   default=30,                        help="폴링 주기 (초)")
    p.add_argument("--outdir",       default="results/paper_dual",                  help="결과 저장 디렉토리")
    p.add_argument("--state",        default="results/paper_dual/state.json",       help="상태 파일 경로")
    p.add_argument("--keep_rows",    type=int,   default=2500,                      help="가격 캐시 최대 봉 수")
    p.add_argument("--initial_days", type=int,   default=120,                       help="초기 로딩 기간 (일)")
    p.add_argument("--save_every",   type=int,   default=10,                        help="N봉마다 자동 저장")
    args = p.parse_args(argv)

    run_paper_dual(
        poll_seconds=args.poll,
        outdir=args.outdir,
        state_path=args.state,
        keep_rows=args.keep_rows,
        initial_days=args.initial_days,
        save_every_bars=args.save_every,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
