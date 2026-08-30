#!/usr/bin/env python3
"""
Answer Telegram messages with the state of the real-money account.

Run as a one-shot from a timer, the way the trader itself runs: it drains the
pending updates, replies, records the offset and exits. Nothing to supervise,
nothing to restart, and a crash costs one poll rather than the whole service.

Ground truth comes from the exchange, not from local files. A local ledger can
disagree with reality -- that is the whole reason the runner reconciles against
positions rather than against its own record -- so a status report built from
the ledger could confirm a position that is not there.

Commands, all read-only except one:

    /status       wallet, kill-switch distance, positions, last run
    /positions    open positions in detail
    /chart        equity curve from the exchange's own income ledger
    /log          the tail of the runner log
    /stop CONFIRM disable the timer, so no further orders are placed

/stop is allowed from a chat because it can only ever reduce activity: it stops
new orders and cannot open, size up, or move anything. No command can place an
order. It does not close open positions either -- that is left to a human at a
keyboard, deliberately.

Env: BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
     KILL_DRAWDOWN
"""
from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
KILL = float(os.environ.get("KILL_DRAWDOWN", "0.35"))
RESULTS = ROOT / "results" / "live_real"
STATE = RESULTS / "state.json"
OFFSET = RESULTS / "bot_offset.json"
LOG = Path("/var/log/quant4h/run.log")
TIMER = "quant4h.timer"
API = f"https://api.telegram.org/bot{TOKEN}"


def api(method: str, **params) -> dict:
    import urllib.parse
    import urllib.request
    req = urllib.request.Request(
        f"{API}/{method}", data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def send(chat: str, text: str) -> None:
    try:
        api("sendMessage", chat_id=chat, text=text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001
        print(f"send failed: {exc}", flush=True)


def send_photo(chat: str, path: Path, caption: str) -> None:
    import requests
    with path.open("rb") as fh:
        r = requests.post(f"{API}/sendPhoto",
                          data={"chat_id": chat, "caption": caption,
                                "parse_mode": "HTML"},
                          files={"photo": ("chart.png", fh, "image/png")},
                          timeout=60)
    if not r.ok:
        print(f"sendPhoto failed: {r.text}", flush=True)
        send(chat, caption)


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def last_run() -> dict:
    runs = sorted(RESULTS.glob("run_*.json"))
    if not runs:
        return {}
    try:
        return json.loads(runs[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def timer_state() -> str:
    try:
        r = subprocess.run(["systemctl", "is-enabled", TIMER],
                           capture_output=True, text=True, timeout=10)
        if r.stdout.strip() != "enabled":
            return "DISABLED, no further runs"
        r = subprocess.run(["systemctl", "show", TIMER, "--value",
                            "-p", "NextElapseUSecRealtime"],
                           capture_output=True, text=True, timeout=10)
        return f"enabled, next {r.stdout.strip() or 'unknown'}"
    except Exception:  # noqa: BLE001
        return "unknown"


def exchange():
    """Import live_real only when the exchange is actually needed.

    This polls once a minute. Importing pandas and the strategy package every
    time would cost seconds of CPU to answer nothing, since most polls find no
    messages at all."""
    key = os.environ.get("BINANCE_API_KEY", "").strip()
    sec = os.environ.get("BINANCE_API_SECRET", "").strip()
    if not key or not sec:
        return None
    # Forced, not defaulted: /etc/quant4h.env now carries DRY_RUN=0 and is
    # this service's EnvironmentFile, so setdefault would leave the import
    # armed. The bot never calls L.main(), but the module a reporting tool
    # loads should not be one environment variable away from trading.
    os.environ["DRY_RUN"] = "1"
    import live_real as L
    return L.Futures(key, sec)


def cmd_status() -> str:
    st, run = read_state(), last_run()
    out = ["<b>quant-4h-dual</b>"]

    if st.get("killed_at"):
        out.append(f"\n⛔ <b>KILL SWITCH TRIPPED</b> {str(st['killed_at'])[:19]}"
                   f"\nNo orders until it is cleared by hand.")

    ex = exchange()
    if ex is None:
        return "credentials unavailable"
    try:
        wallet, pos = ex.wallet_usdt(), ex.positions()
    except Exception as exc:  # noqa: BLE001
        return f"could not reach Binance: {html.escape(str(exc))}"

    base = float(st.get("baseline_equity") or wallet or 0)
    floor = base * (1 - KILL)
    out.append(f"\nwallet   <b>{wallet:,.2f}</b> USDT "
               f"({wallet / base - 1:+.2%} vs start)" if base > 0 else
               f"\nwallet   <b>{wallet:,.2f}</b> USDT")
    out.append(f"start    {base:,.2f}")
    if floor > 0:
        out.append(f"floor    {floor:,.2f}  ({wallet / floor - 1:+.1%} away)")

    if pos:
        out.append("\n<b>positions</b>")
        for sym, amt in sorted(pos.items()):
            out.append(f"  {sym} {amt:+.6f}")
    else:
        out.append("\nno open positions")

    frac = run.get("target_fraction") or {}
    if frac:
        out.append("\nlast target  "
                   + ", ".join(f"{k} {v:.1%}" for k, v in frac.items()))
    out.append(f"last run     {run.get('bar', '?')}, "
               f"{len(run.get('plan') or [])} order(s)"
               + ("  [dry]" if run.get("dry_run") else ""))
    out.append(f"schedule     {timer_state()}")
    return "\n".join(out)


def cmd_positions() -> str:
    ex = exchange()
    if ex is None:
        return "credentials unavailable"
    try:
        rows = ex._signed("GET", "/fapi/v2/positionRisk")
    except Exception as exc:  # noqa: BLE001
        return f"could not reach Binance: {html.escape(str(exc))}"
    live = [r for r in rows if abs(float(r.get("positionAmt") or 0)) > 0]
    if not live:
        return "no open positions"
    out = ["<b>positions</b>"]
    for r in live:
        out.append(
            f"\n{r['symbol']}  {float(r['positionAmt']):+.6f}"
            f"\n  entry {float(r.get('entryPrice') or 0):,.2f}"
            f"   mark {float(r.get('markPrice') or 0):,.2f}"
            f"\n  notional {abs(float(r.get('notional') or 0)):,.2f} USD"
            f"\n  uPnL {float(r.get('unRealizedProfit') or 0):+,.2f} USD"
            f"\n  liquidation {float(r.get('liquidationPrice') or 0):,.2f}")
    return "\n".join(out)


def income(ex, days: int = 120) -> list:
    """Every ledger entry, paged. The exchange's own record of what happened."""
    rows, start = [], int(time.time() * 1000) - days * 86_400_000
    while True:
        page = ex._signed("GET", "/fapi/v1/income",
                          {"startTime": start, "limit": 1000})
        rows += page
        if len(page) < 1000:
            break
        start = int(page[-1]["time"]) + 1
    rows.sort(key=lambda r: int(r["time"]))
    return rows


def cmd_chart():
    """Equity from the exchange's income ledger.

    Realised P&L, funding and commission all land there with timestamps, which
    makes it the account's actual history rather than a reconstruction from
    local files. TRANSFER entries are excluded: money moved in is not profit,
    and counting it would draw a deposit as a rally."""
    ex = exchange()
    if ex is None:
        return "credentials unavailable"
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return ("charting needs matplotlib:\n"
                "<code>/opt/quant-4h-dual/.venv/bin/pip install matplotlib</code>")

    try:
        rows = income(ex)
        wallet = ex.wallet_usdt()
        upnl = sum(float(p.get("unRealizedProfit") or 0)
                   for p in ex._signed("GET", "/fapi/v2/positionRisk"))
    except Exception as exc:  # noqa: BLE001
        return f"could not reach Binance: {html.escape(str(exc))}"

    trade = [r for r in rows if r.get("incomeType") != "TRANSFER"]
    if not trade:
        return ("nothing realised yet, so there is no curve to draw.\n"
                f"wallet {wallet:,.2f} USDT, unrealised {upnl:+,.2f}")

    st = read_state()
    base = float(st.get("baseline_equity") or wallet)
    floor = base * (1 - KILL)

    xs, ys, run = [], [], 0.0
    for r in trade:
        run += float(r["income"])
        xs.append(datetime.fromtimestamp(int(r["time"]) / 1000, timezone.utc))
        ys.append(base + run)
    xs.append(datetime.now(timezone.utc))
    ys.append(base + run + upnl)

    tot = {}
    for r in trade:
        tot[r["incomeType"]] = tot.get(r["incomeType"], 0.0) + float(r["income"])

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    ax.plot(xs, ys, lw=2, color="#22aa77", zorder=3)
    ax.fill_between(xs, base, ys, alpha=.12, color="#22aa77", zorder=2)
    # Scale to the equity, not to the kill floor. The floor sits 35% below the
    # start, so including it squeezes the curve into the top third of the frame
    # and the shape -- the reason for drawing this at all -- becomes unreadable.
    # When the floor is off-scale it is reported in the caption instead.
    lo, hi = min(min(ys), base), max(max(ys), base)
    pad = max((hi - lo) * .15, base * .01)
    lo, hi = lo - pad, hi + pad
    ax.axhline(base, color="#999", lw=1, ls="--", zorder=1)
    ax.annotate(f"start {base:,.0f}", (xs[0], base), fontsize=8, color="#666",
                textcoords="offset points", xytext=(3, 5))
    if floor >= lo:
        ax.axhline(floor, color="#cc3333", lw=1.2, ls="--", zorder=1)
        ax.annotate(f"kill floor {floor:,.0f}", (xs[0], floor), fontsize=8,
                    color="#cc3333", textcoords="offset points", xytext=(3, 5))
    ax.set_ylim(lo, hi)
    ax.set_ylabel("USDT")
    ax.set_title(f"quant-4h-dual   {ys[-1]:,.2f} USDT  "
                 f"({ys[-1] / base - 1:+.2%} since start)", fontsize=11)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.grid(alpha=.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = RESULTS / "chart.png"
    fig.savefig(out)
    plt.close(fig)

    caption = "\n".join([
        f"<b>{ys[-1]:,.2f} USDT</b>  ({ys[-1] / base - 1:+.2%} since start)",
        f"realised   {tot.get('REALIZED_PNL', 0):+,.2f}",
        f"funding    {tot.get('FUNDING_FEE', 0):+,.2f}",
        f"fees       {tot.get('COMMISSION', 0):+,.2f}",
        f"unrealised {upnl:+,.2f}",
        f"kill floor {floor:,.2f}  ({wallet / floor - 1:+.1%} away)"
        if floor > 0 else "",
    ])
    return out, caption


def cmd_log() -> str:
    try:
        tail = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-14:]
    except Exception as exc:  # noqa: BLE001
        return f"cannot read the log: {html.escape(str(exc))}"
    return "<pre>" + html.escape("\n".join(tail)) + "</pre>"


def cmd_stop(text: str) -> str:
    if "CONFIRM" not in text.upper():
        return ("This disables the schedule, so no further orders are placed.\n"
                "Open positions are NOT closed — do that on Binance.\n\n"
                "Send  <code>/stop CONFIRM</code>  to go ahead.")
    try:
        subprocess.run(["sudo", "-n", "systemctl", "disable", "--now", TIMER],
                       capture_output=True, text=True, timeout=20, check=True)
    except Exception as exc:  # noqa: BLE001
        return (f"could not disable the timer: {html.escape(str(exc))}\n"
                f"On the server: <code>systemctl disable --now {TIMER}</code>")
    return ("⏹ schedule disabled. Open positions are untouched — "
            "close them on Binance if you want out.")


HELP = ("<b>quant-4h-dual</b>\n"
        "/status — wallet, kill-switch distance, positions\n"
        "/positions — open positions in detail\n"
        "/chart — equity curve since the account started\n"
        "/log — the tail of the runner log\n"
        "/stop CONFIRM — stop placing orders\n\n"
        "Any other message returns /status.")


def handle(text: str):
    t = text.strip().lower()
    if t.startswith("/stop"):
        return cmd_stop(text)
    if t.startswith("/pos"):
        return cmd_positions()
    if t.startswith("/chart") or t.startswith("/graph"):
        return cmd_chart()
    if t.startswith("/log"):
        return cmd_log()
    if t.startswith("/help") or t.startswith("/start"):
        return HELP
    return cmd_status()


def main() -> None:
    if not TOKEN or not CHAT:
        print("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set", flush=True)
        return
    RESULTS.mkdir(parents=True, exist_ok=True)
    try:
        offset = int(json.loads(OFFSET.read_text())["offset"])
    except Exception:  # noqa: BLE001
        offset = 0

    try:
        updates = api("getUpdates", offset=offset + 1, timeout=0).get("result", [])
    except Exception as exc:  # noqa: BLE001
        print(f"getUpdates failed: {exc}", flush=True)
        return

    for u in updates:
        offset = max(offset, int(u.get("update_id", 0)))
        msg = u.get("message") or u.get("edited_message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        # Only the configured chat. Anyone can find a bot and message it, and
        # this one reports on a real account.
        if chat != CHAT:
            print(f"ignoring chat {chat}", flush=True)
            continue
        print(f"{chat}: {text!r}", flush=True)
        try:
            reply = handle(text)
            if isinstance(reply, tuple):
                send_photo(chat, reply[0], reply[1])
            else:
                send(chat, reply)
        except Exception as exc:  # noqa: BLE001
            send(chat, f"failed: {html.escape(str(exc))}")

    OFFSET.write_text(json.dumps(
        {"offset": offset,
         "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))


if __name__ == "__main__":
    main()
