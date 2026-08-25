#!/usr/bin/env python3
"""
Run the real-money runner locally against the real Binance account, read-only.

    python scripts/run_local.py

Credentials are read from a file sitting NEXT TO this repository folder, not
inside it -- on this machine that is the Desktop:

    C:\\Users\\...\\Desktop\\quant4h.env      (beside quant_4h_1\\)

containing exactly:

    BINANCE_API_KEY=...
    BINANCE_API_SECRET=...

Outside the working tree means outside version control, so it cannot be added to
a commit by accident, and it never appears in shell history the way an inline
export does. Set QUANT4H_ENV to read it from somewhere else.

DRY_RUN is forced on and cannot be overridden here. This script reads the wallet
and the open positions, computes the plan, and stops. Live trading belongs on
the server, where the systemd timer runs it on the bar; a laptop that may be
asleep at 04:02 UTC is not a place to hold real positions from.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Beside the repository folder, never inside it. ROOT.parent is the directory
# holding quant_4h_1, which on this machine is the Desktop. The older locations
# are still accepted so an existing file keeps working.
PREFERRED = ROOT.parent / "quant4h.env"
CANDIDATES = [PREFERRED,
              ROOT.parent / ".quant4h.env",
              Path(os.path.expanduser("~")) / ".quant4h.env"]

_override = os.environ.get("QUANT4H_ENV")
ENV = Path(_override) if _override else next(
    (p for p in CANDIDATES if p.exists()), PREFERRED)


def load_env() -> None:
    if not ENV.exists():
        sys.exit(
            f"credentials file not found: {ENV}\n\n"
            f"Create it with two lines and nothing else:\n"
            f"    BINANCE_API_KEY=...\n"
            f"    BINANCE_API_SECRET=...\n\n"
            f"    notepad \"{PREFERRED}\"\n\n"
            f"Put it beside the repository folder, not inside it -- anything\n"
            f"inside {ROOT.name} is under version control.")
    bad = []
    for n, raw in enumerate(ENV.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            bad.append(n)
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
    if bad:
        print(f"warning: ignoring malformed line(s) {bad} in {ENV}")

    for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET"):
        v = os.environ.get(name, "")
        if len(v) != 64 or not v.isalnum():
            sys.exit(f"{name} is {len(v)} characters; a Binance HMAC key is 64 "
                     f"alphanumeric characters. The value was probably truncated.")


def main() -> None:
    load_env()

    # Not negotiable, and set before live_real is imported because it reads
    # DRY_RUN at import time.
    os.environ["DRY_RUN"] = "1"

    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import live_real as L

    if not L.DRY_RUN:
        sys.exit("refusing to run: DRY_RUN did not take effect")

    # keep local runs out of the server's result directory
    L.RESULTS = ROOT / "results" / "live_local"
    L.RESULTS.mkdir(parents=True, exist_ok=True)
    L.STATE = L.RESULTS / "state.json"
    L.notify = lambda *a, **k: None      # no Telegram noise from a laptop

    print(f"credentials: {ENV}")
    print(f"results:     {L.RESULTS}")
    print("mode:        DRY RUN (forced)\n")

    try:
        L.main()
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "-2015" in text:
            import urllib.request
            try:
                ip = urllib.request.urlopen(
                    "https://api.ipify.org", timeout=10).read().decode()
            except Exception:  # noqa: BLE001
                ip = "unknown"
            sys.exit(
                f"\nBinance rejected the key (-2015).\n"
                f"This machine's public IP is {ip}.\n"
                f"The key is IP-restricted, so add this address to its whitelist\n"
                f"alongside the server's, or the request will keep being refused.")
        if "-1021" in text:
            sys.exit("\nBinance rejected the timestamp (-1021): this machine's "
                     "clock is off. Sync it and retry.")
        raise


if __name__ == "__main__":
    main()
