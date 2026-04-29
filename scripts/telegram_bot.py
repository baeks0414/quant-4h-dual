#!/usr/bin/env python3
"""
텔레그램 봇 커맨드 핸들러 - GitHub Actions 원샷 버전
5분마다 실행되어 새 메시지를 확인하고 명령어에 응답.

지원 명령어:
  /status  - 현재 자본, 수익률, MDD, Sharpe
  /trades  - 최근 거래 내역
  /regime  - 현재 레짐 + 포지션
  /help    - 명령어 목록

일반 텍스트도 지원:
  "수익률", "상태", "지금 어때?" 같은 메시지를 보내면
  현재 수익률과 핵심 상태 요약을 자동으로 답장.
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
ALLOW_PRIVATE_DM = os.environ.get("TELEGRAM_ALLOW_PRIVATE_DM", "1").strip().lower() not in {"0", "false", "no", "off"}
ALLOWED_CHAT_IDS = {
    value.strip()
    for value in os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if value.strip()
}

ROOT       = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "results" / "paper_live_rt" / "state.json"
LOG_PATH   = ROOT / "results" / "paper_live_rt" / "run_log.csv"
TRADES_PATH= ROOT / "results" / "paper_live_rt" / "trades.csv"
BOT_STATE  = ROOT / "results" / "paper_live_rt" / "bot_state.json"

POS_ICON = {"LONG": "🟢", "SHORT": "🔴", "FLAT": "⚪"}
REGIME_ICON = {
    "STRONG_TREND": "🚀",
    "STRONG_TREND_BEAR": "🐻",
    "VOL_EXPAND": "⚡",
    "CHOP": "〰️",
}
STATUS_KEYWORDS = (
    "status", "summary", "snapshot", "state", "performance", "pnl", "profit", "return",
    "수익", "수익률", "손익", "상태", "현황", "성과", "리턴", "지금", "현재",
)
TRADES_KEYWORDS = ("trade", "trades", "fills", "거래", "체결", "내역")
REGIME_KEYWORDS = ("regime", "position", "positions", "레짐", "포지션")
HELP_KEYWORDS = ("help", "commands", "도움", "도움말", "명령어")
ENTRY_TYPES = {"ENTRY_LONG", "ENTRY_SHORT", "PYRAMID_LONG", "PYRAMID_SHORT"}
EXIT_TYPES = {"EXIT", "STOP_LONG", "STOP_SHORT", "CLOSE_BY_SIGNAL", "FLIP_CLOSE"}


def api(method: str, **kwargs) -> dict:
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        json=kwargs, timeout=10,
    )
    return r.json()


def send(text: str, chat_id: str | None = None) -> None:
    target_chat_id = str(chat_id or CHAT_ID).strip()
    if not target_chat_id:
        return
    api("sendMessage", chat_id=target_chat_id, text=text, parse_mode="HTML")


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


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _latest_log_row() -> dict:
    if not LOG_PATH.exists():
        return {}
    try:
        df = pd.read_csv(LOG_PATH)
        if df.empty:
            return {}
        return df.iloc[-1].to_dict()
    except Exception:
        return {}


def _fmt_symbol(symbol: str) -> str:
    return symbol.replace("USDT", "")


def _format_positions_line(label: str, positions: dict) -> str:
    ordered = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        side = str(positions.get(symbol, "FLAT"))
        ordered.append(f"{_fmt_symbol(symbol)} {POS_ICON.get(side, '⚪')} {side}")
    return f"{label}: " + " | ".join(ordered)


def _load_recent_trade_lines(limit: int = 3) -> list[str]:
    if not TRADES_PATH.exists():
        return []
    try:
        df = pd.read_csv(TRADES_PATH)
        if df.empty:
            return []
        recent = df.tail(limit)
        lines: list[str] = []
        for _, row in recent.iterrows():
            trade_type = str(row.get("type", "?"))
            symbol = _fmt_symbol(str(row.get("symbol", "?")))
            ts = str(row.get("time", "?"))[:16].replace("T", " ")
            entry_px = row.get("entry")
            exit_px = row.get("exit")
            price = exit_px if exit_px is not None and not pd.isna(exit_px) else entry_px
            pnl = row.get("pnl")
            note = row.get("note")

            if trade_type in {"ENTRY_LONG", "PYRAMID_LONG"}:
                icon = "🟢"
            elif trade_type in {"ENTRY_SHORT", "PYRAMID_SHORT"}:
                icon = "🔴"
            elif trade_type == "FUNDING":
                icon = "💰" if _as_float(pnl, 0.0) >= 0 else "💸"
            else:
                icon = "🔚"

            display_type = trade_type
            if (
                trade_type in EXIT_TYPES
                and note is not None
                and not pd.isna(note)
                and str(note).strip()
            ):
                display_type = f"{trade_type}/{str(note).strip()}"

            price_str = f" @${float(price):,.1f}" if price is not None and not pd.isna(price) else ""
            show_pnl = trade_type in EXIT_TYPES or trade_type == "FUNDING"
            pnl_str = f" (${_as_float(pnl):+,.2f})" if show_pnl and pnl is not None and not pd.isna(pnl) else ""
            lines.append(f"{icon} {ts} {symbol} {display_type}{price_str}{pnl_str}")
        return lines
    except Exception:
        return []


def _build_status_message() -> str:
    state = load_json(STATE_PATH)
    if not state:
        return "⚠️ 아직 데이터 없음. 첫 4H 실행 후 확인 가능."

    log = _latest_log_row()
    eq = _as_float(state.get("final_equity", log.get("final_equity", 0.0)))
    ret = _as_float(state.get("total_return", log.get("total_return", 0.0)))
    live_start = state.get("live_start", "?")
    latest = state.get("last_bar_time", "?")
    mdd = _as_float(log.get("max_drawdown", 0.0))
    sharpe = _as_float(log.get("sharpe", 0.0))
    n_trades = int(_as_float(log.get("num_live_trades", 0)))
    new_trades = int(_as_float(log.get("new_trades", 0)))
    regime = str(state.get("market_regime", log.get("market_regime", "?")))
    trend_positions = state.get("trend_positions", {})
    sleeve_positions = state.get("sleeve_positions", {})
    run_time = log.get("run_time")
    recent_trades = _load_recent_trade_lines(limit=3)

    ret_icon = "📈" if ret >= 0 else "📉"
    regime_icon = REGIME_ICON.get(regime, "❓")

    lines = [
        f"{ret_icon} <b>현재 페이퍼 트레이딩 현황</b>",
        "",
        f"💰 자본: <b>${eq:,.2f}</b>",
        f"📊 수익률: <b>{ret * 100:+.2f}%</b>",
        f"📉 MDD: {mdd * 100:.2f}%",
        f"⚡ Sharpe: {sharpe:.2f}",
        f"📋 누적 거래: {n_trades}건  |  이번 봉 신규: {new_trades}건",
        "",
        f"{regime_icon} 레짐: <b>{regime}</b>",
        _format_positions_line("Trend", trend_positions),
        _format_positions_line("Sleeve", sleeve_positions),
        "",
        f"🕐 시작: {live_start}",
        f"🕐 최신 봉: {latest}",
    ]
    if run_time:
        lines.append(f"🔄 최근 점검: {run_time}")
    if recent_trades:
        lines.extend(["", "🧾 <b>최근 거래</b>"])
        lines.extend(recent_trades)
    else:
        lines.extend(["", "🧾 최근 거래 없음"])
    return "\n".join(lines)


def _detect_command(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None

    first = text.split("@")[0].split(" ")[0].lower()
    if first.startswith("/"):
        return first

    lowered = " ".join(text.casefold().split())
    if any(keyword in lowered for keyword in HELP_KEYWORDS):
        return "/help"
    if any(keyword in lowered for keyword in TRADES_KEYWORDS):
        return "/trades"
    if any(keyword in lowered for keyword in REGIME_KEYWORDS):
        return "/regime"
    if any(keyword in lowered for keyword in STATUS_KEYWORDS):
        return "/status"
    return "/status"


def _chat_allowed(chat_id: str, chat_type: str) -> bool:
    if chat_id and chat_id == str(CHAT_ID):
        return True
    if chat_id and chat_id in ALLOWED_CHAT_IDS:
        return True
    if chat_type == "private" and ALLOW_PRIVATE_DM:
        return True
    return False


# ── 명령어 핸들러 ─────────────────────────────────────────────────────

def cmd_help() -> str:
    return (
        "📋 <b>사용 가능한 명령어</b>\n\n"
        "/status  — 현재 자본, 수익률, 포지션 요약\n"
        "/trades  — 최근 거래 내역\n"
        "/regime  — 현재 레짐 및 포지션\n"
        "/help    — 명령어 목록\n\n"
        "💬 일반 메시지를 보내도 현재 현황 요약을 답장합니다.\n"
        "예: 수익률, 상태, 지금 어때?"
    )


def cmd_status() -> str:
    return _build_status_message()


def cmd_trades() -> str:
    lines = _load_recent_trade_lines(limit=5)
    if not lines:
        return "⚠️ 아직 거래 없음."
    return "📋 <b>최근 거래 내역</b> (최근 5건)\n\n" + "\n".join(lines)


def cmd_regime() -> str:
    state = load_json(STATE_PATH)
    if not state:
        return "⚠️ 아직 데이터 없음."

    regime   = state.get("market_regime", "?")
    t_pos    = state.get("trend_positions", {})
    s_pos    = state.get("sleeve_positions", {})
    latest   = state.get("last_bar_time", "?")

    regime_icon = REGIME_ICON.get(str(regime), "❓")

    return (
        f"{regime_icon} <b>현재 시장 상태</b>\n\n"
        f"레짐: <b>{regime}</b>\n"
        f"🕐 기준 봉: {latest}\n\n"
        f"<b>Trend (70%)</b>\n"
        f"  BTC: {POS_ICON.get(t_pos.get('BTCUSDT','FLAT'),'⚪')} {t_pos.get('BTCUSDT','FLAT')}\n"
        f"  ETH: {POS_ICON.get(t_pos.get('ETHUSDT','FLAT'),'⚪')} {t_pos.get('ETHUSDT','FLAT')}\n"
        f"<b>Sleeve (30%)</b>\n"
        f"  BTC: {POS_ICON.get(s_pos.get('BTCUSDT','FLAT'),'⚪')} {s_pos.get('BTCUSDT','FLAT')}\n"
        f"  ETH: {POS_ICON.get(s_pos.get('ETHUSDT','FLAT'),'⚪')} {s_pos.get('ETHUSDT','FLAT')}"
    )


COMMANDS = {
    "/status":  cmd_status,
    "/trades":  cmd_trades,
    "/regime":  cmd_regime,
    "/help":    cmd_help,
    "/start":   cmd_help,
}


def main() -> None:
    if not TOKEN:
        print("[BOT] TELEGRAM_TOKEN 없음. 종료.")
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
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = str(chat.get("type", ""))

        # 허용된 채팅에서 온 메시지만 처리
        if not _chat_allowed(chat_id, chat_type):
            print(f"[BOT] 무시: chat_id={chat_id} type={chat_type}")
            continue

        print(f"[BOT] 수신: {text!r}  (chat_id={chat_id}, type={chat_type})")

        cmd = _detect_command(text)
        if not cmd:
            continue
        handler = COMMANDS.get(cmd)

        if handler:
            reply = handler()
            send(reply, chat_id=chat_id)
            print(f"[BOT] 응답 전송: {cmd} -> {chat_id}")
        else:
            send(
                f"❓ 알 수 없는 명령어: <code>{text}</code>\n"
                "/help 로 명령어 목록을 확인하세요.\n"
                "일반 메시지를 보내면 현재 현황 요약을 답장합니다.",
                chat_id=chat_id,
            )

    # 처리한 update_id 저장
    bot_state["last_update_id"] = last_update
    save_json(BOT_STATE, bot_state)
    print(f"[BOT] 처리 완료. last_update_id={last_update}")


if __name__ == "__main__":
    main()
