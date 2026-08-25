#!/usr/bin/env python3
"""
Run the real-money runner locally against the real Binance account, read-only.

    python scripts/run_local.py

Credentials are read from quant4h.env in the project root:

    quant_4h_1\\quant4h.env

containing exactly:

    BINANCE_API_KEY=...
    BINANCE_API_SECRET=...

That path is inside a repository whose remote is public, so before reading it
this script asks git whether the file is ignored and refuses to run if it is
not. The *.env rule in .gitignore is what makes it safe; the check is there
because a rule can be edited away and a leaked key cannot be recalled.

Set QUANT4H_ENV to read the file from somewhere else.

Against production, DRY_RUN is forced on and cannot be overridden: the script
reads the wallet and the open positions, computes the plan, and stops. Real
trading belongs on the server, where the systemd timer runs it on the bar; a
laptop that may be asleep at 04:02 UTC is not a place to hold real positions
from.

    BINANCE_TESTNET=1 DRY_RUN=0    place real orders on the Binance futures
                                   testnet, with testnet funds and testnet keys

That combination is the only way to exercise order placement -- post-only
acceptance, client order id format, partial fills, cancels -- which no dry run
ever reaches.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PREFERRED = ROOT / "quant4h.env"
CANDIDATES = [PREFERRED,
              ROOT.parent / "quant4h.env",
              ROOT.parent / ".quant4h.env",
              Path(os.path.expanduser("~")) / ".quant4h.env"]

_override = os.environ.get("QUANT4H_ENV")
ENV = Path(_override) if _override else next(
    (p for p in CANDIDATES if p.exists()), PREFERRED)


def assert_not_committable(path: Path) -> None:
    """Refuse to read credentials that git would happily commit.

    The remote for this repository is public. A file inside the tree is only
    safe while .gitignore keeps ignoring it, which is a condition worth checking
    on every run rather than assuming: rules get edited, and a key that reaches
    a public remote has to be treated as burnt even if the commit is reverted.
    """
    try:
        path.relative_to(ROOT)
    except ValueError:
        return                      # outside the tree, nothing to check

    try:
        rc = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(path)],
                            capture_output=True, timeout=15).returncode
    except (OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"cannot verify that {path.name} is git-ignored ({exc}).\n"
                 f"Move it outside {ROOT.name}\\ or set QUANT4H_ENV.")

    if rc == 0:
        return                      # ignored
    if rc == 128:
        return                      # not a git repository at all
    sys.exit(
        f"REFUSING TO READ {path}\n\n"
        f"git does not ignore this file, and this repository's remote is public.\n"
        f"Committing it would publish your API key.\n\n"
        f"Add a rule to .gitignore:   {path.name}\n"
        f"or move the file out of {ROOT.name}\\ and point QUANT4H_ENV at it.")


def load_env() -> None:
    assert_not_committable(ENV)
    if not ENV.exists():
        sys.exit(
            f"credentials file not found: {ENV}\n\n"
            f"Create it with two lines and nothing else:\n"
            f"    BINANCE_API_KEY=...\n"
            f"    BINANCE_API_SECRET=...\n\n"
            f"    notepad \"{PREFERRED}\"\n\n"
            f"The .env suffix matters: it is what .gitignore matches, and this\n"
            f"script refuses to read a credentials file git would commit.")
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

    # Live orders from a workstation are allowed against the testnet and
    # nowhere else. Order placement is the one path a dry run never reaches, so
    # it has to be exercised somewhere, and play money is the place. Against
    # production this stays a rehearsal.
    testnet = os.environ.get("BINANCE_TESTNET") == "1"
    if not testnet:
        os.environ["DRY_RUN"] = "1"
    elif os.environ.get("DRY_RUN") == "0":
        print("BINANCE_TESTNET=1 and DRY_RUN=0: this WILL place orders on the"
              + chr(10) + "Binance futures testnet, using testnet funds."
              + chr(10))

    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import live_real as L

    if not L.DRY_RUN and not L.TESTNET:
        sys.exit("refusing to run: live orders are only allowed on the testnet")

    # keep local runs out of the server's result directory
    L.RESULTS = ROOT / "results" / ("live_testnet" if testnet else "live_local")
    L.RESULTS.mkdir(parents=True, exist_ok=True)
    L.STATE = L.RESULTS / "state.json"
    L.notify = lambda *a, **k: None      # no Telegram noise from a laptop

    print(f"credentials: {ENV}")
    print(f"results:     {L.RESULTS}")
    print(f"endpoint:    {L.TAPI}")
    print(f"mode:        {'LIVE (testnet)' if not L.DRY_RUN else 'DRY RUN'}\n")

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
