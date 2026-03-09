#!/usr/bin/env python3
"""
텔레그램 봇 커맨드 핸들러 - GitHub Actions 원샷 버전
5분마다 실행되어 새 메시지를 확인하고 명령어에 응답.

지원 명령어:
  /status  - 현재 자본, 수익률, MDD, Sharpe
  /trades  - 최근 거래 내역
  /regime  - 현재 레짐 + 포지션
  /help    - 명령어 목록
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
import pandas as pd

TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

ROOT       = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "results" / "paper_live_rt" / "state.json"
LOG_PATH   = ROOT / "results" / "paper_live_rt" / "run_log.csv"
TRADES_PATH= ROOT / "results" / "paper_live_rt" / "trades.csv"
BOT_STATE  = ROOT / "results" / "paper_live_rt" / "bot_state.json"


def api(method: str, **kwargs) -> dict:
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=kwargs, timeout=10,
    )
    return r.json()


def send(text: str) -> None:
    api("sendMessage", chat_id=CHAT_ID, text=text, parse_mode="HTML")


def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 명령어 핸들러 ─────────────────────────────────────────────────────

def cmd_help() -> str:
    return (
        "📋 <b>사용 가능한 명령어</b>\n\n"
        "/status  — 현재 자본 및 수익률\n"
        "/trades  — 최근 거래 내역\n"
        "/regime  — 현재 레짐 및 포지션\n"
        "/help    — 명령어 목록"
    )


def cmd_status() -> str:
    state = load_json(STATE_PATH)
    if not state:
        return "⚠️ 아직 데이터 없음. 첫 4H 실행 후 확인 가능."

    eq        = state.get("final_equity", 0)
    ret       = state.get("total_return", 0)
    live_start= state.get("live_start", "?")
    latest    = state.get("last_bar_time", "?")

    # run_log에서 MDD, Sharpe 가져오기
    mdd, sharpe, n_trades = 0.0, 0.0, 0
    if LOG_PATH.exists():
        try:
            df = pd.read_csv(LOG_PATH)
            if not df.empty:
                last = df.iloc[-1]
                mdd      = float(last.get("max_drawdown", 0))
                sharpe   = float(last.get("sharpe", 0))
                n_trades = int(last.get("num_live_trades", 0))
        except Exception:
            pass

    ret_icon = "📈" if ret >= 0 else "📉"
    return (
        f"{ret_icon} <b>현재 페이퍼 트레이딩 현황</b>\n\n"
        f"💰 자본: <b>${eq:,.2f}</b>\n"
        f"📊 수익률: <b>{ret*100:+.2f}%</b>\n"
        f"📉 MDD: {mdd*100:.2f}%\n"
        f"⚡ Sharpe: {sharpe:.2f}\n"
        f"📋 누적 거래: {n_trades}건\n\n"
        f"🕐 시작: {live_start}\n"
        f"🕐 최신 봉: {latest}"
    )


def cmd_trades() -> str:
    if not TRADES_PATH.exists():
        return "⚠️ 아직 거래 없음."
    try:
        df = pd.read_csv(TRADES_PATH)
        if df.empty:
            return "⚠️ 아직 거래 없음."

        # 최근 5건
        recent = df.tail(5)
        lines = ["📋 <b>최근 거래 내역</b> (최근 5건)\n"]
        for _, row in recent.iterrows():
            side  = str(row.get("side", row.get("action", "?")))
            sym   = str(row.get("symbol", "?"))
            price = row.get("price", row.get("entry_price", 0))
            t     = str(row.get("time", row.get("entry_time", "?")))[:16]
            pnl   = row.get("pnl", row.get("realized_pnl", None))

            side_icon = "🟢" if "LONG" in side.upper() else ("🔴" if "SHORT" in side.upper() else "⚪")
            pnl_str = f"  PnL: ${float(pnl):+.2f}" if pnl is not None and str(pnl) != "nan" else ""
            lines.append(f"{side_icon} {t}  {sym}  {side}  @${float(price):,.1f}{pnl_str}")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ 거래 내역 로드 오류: {e}"


def cmd_regime() -> str:
    state = load_json(STATE_PATH)
    if not state:
        return "⚠️ 아직 데이터 없음."

    regime   = state.get("market_regime", "?")
    t_pos    = state.get("trend_positions", {})
    s_pos    = state.get("sleeve_positions", {})
    latest   = state.get("last_bar_time", "?")

    pos_icon = {"LONG": "🟢", "SHORT": "🔴", "FLAT": "⚪"}
    regime_icon = {
        "STRONG_TREND": "🚀", "STRONG_TREND_BEAR": "🐻",
        "VOL_EXPAND": "⚡", "CHOP": "〰️",
    }.get(str(regime), "❓")

    return (
        f"{regime_icon} <b>현재 시장 상태</b>\n\n"
        f"레짐: <b>{regime}</b>\n"
        f"🕐 기준 봉: {latest}\n\n"
        f"<b>Trend (70%)</b>\n"
        f"  BTC: {pos_icon.get(t_pos.get('BTCUSDT','FLAT'),'⚪')} {t_pos.get('BTCUSDT','FLAT')}\n"
        f"  ETH: {pos_icon.get(t_pos.get('ETHUSDT','FLAT'),'⚪')} {t_pos.get('ETHUSDT','FLAT')}\n"
        f"<b>Sleeve (30%)</b>\n"
        f"  BTC: {pos_icon.get(s_pos.get('BTCUSDT','FLAT'),'⚪')} {s_pos.get('BTCUSDT','FLAT')}\n"
        f"  ETH: {pos_icon.get(s_pos.get('ETHUSDT','FLAT'),'⚪')} {s_pos.get('ETHUSDT','FLAT')}"
    )


COMMANDS = {
    "/status":  cmd_status,
    "/trades":  cmd_trades,
    "/regime":  cmd_regime,
    "/help":    cmd_help,
    "/start":   cmd_help,
}


def main() -> None:
    if not TOKEN or not CHAT_ID:
        print("[BOT] TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 없음. 종료.")
        return

    # 마지막으로 처리한 update_id 로드
    bot_state   = load_json(BOT_STATE)
    last_update = int(bot_state.get("last_update_id", 0))

    # 새 메시지 가져오기 (offset = last_update+1 로 이미 처리한 것 제외)
    resp = api("getUpdates", offset=last_update + 1, timeout=5)
    updates = resp.get("result", [])

    if not updates:
        print("[BOT] 새 메시지 없음.")
        return

    for update in updates:
        update_id = update.get("update_id", 0)
        last_update = max(last_update, update_id)

        msg  = update.get("message", {})
        text = msg.get("text", "").strip()
        from_id = str(msg.get("chat", {}).get("id", ""))

        # 등록된 chat_id 에서 온 메시지만 처리
        if from_id != str(CHAT_ID):
            continue

        print(f"[BOT] 수신: {text!r}")

        # 명령어 매칭 (e.g. /status@botname → /status)
        cmd = text.split("@")[0].split(" ")[0].lower()
        handler = COMMANDS.get(cmd)

        if handler:
            reply = handler()
            send(reply)
            print(f"[BOT] 응답 전송: {cmd}")
        else:
            send(
                f"❓ 알 수 없는 명령어: <code>{text}</code>\n"
                "/help 로 명령어 목록을 확인하세요."
            )

    # 처리한 update_id 저장
    bot_state["last_update_id"] = last_update
    save_json(BOT_STATE, bot_state)
    print(f"[BOT] 처리 완료. last_update_id={last_update}")


if __name__ == "__main__":
    main()
