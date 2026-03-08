# src/quant/cli/paper.py
from __future__ import annotations

import argparse

from quant.config.presets import preset_regime_only_live
from quant.core.runner import run_live
from quant.execution.paper_broker import PaperBroker


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("quant-paper")
    p.add_argument("--interval", default="4h")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--outdir", default="result")
    p.add_argument("--state", default="result/state_paper.json")
    p.add_argument("--keep_rows", type=int, default=2500)
    p.add_argument("--initial_days", type=int, default=120)
    p.add_argument("--save_every", type=int, default=50)

    # paper에서도 인터페이스 통일(원하면 씀)
    p.add_argument("--min_usdt_balance", type=float, default=1.0)
    p.add_argument("--deploy_capital", type=float, default=None)

    args = p.parse_args(argv)

    cfg = preset_regime_only_live()
    cfg.interval = args.interval

    broker = PaperBroker(cfg)

    run_live(
        cfg,
        broker=broker,
        poll_seconds=args.poll,
        outdir=args.outdir,
        state_path=args.state,
        keep_rows=args.keep_rows,
        initial_days=args.initial_days,
        save_every_bars=args.save_every,
        min_usdt_balance_to_run=args.min_usdt_balance,
        deploy_capital_usdt=args.deploy_capital,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
