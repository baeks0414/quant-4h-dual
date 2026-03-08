# src/quant/cli/live.py
from __future__ import annotations

import argparse
from quant.cli.paper import main as paper_main
from quant.cli.real import main as real_main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("quant-live")
    p.add_argument("--mode", choices=["paper", "real"], default="paper")
    args, rest = p.parse_known_args(argv)

    if args.mode == "paper":
        return paper_main(rest)
    return real_main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
