# src/quant/cli/real.py
from __future__ import annotations

import argparse
import sys

from quant.config.presets import preset_live_small_test, preset_regime_only_live 
from quant.config.settings import load_settings
from quant.core.runner import run_live
from quant.execution.binance_broker import BinanceBroker


def _require_keys_from_settings():
    s = load_settings()
    if not s.binance_api_key or not s.binance_api_secret:
        print(
            "BINANCE_API_KEY / BINANCE_API_SECRET 를 찾지 못했습니다.\n"
            "해결:\n"
            "1) 프로젝트 루트에 .env 생성 (project/.env)\n"
            "   BINANCE_API_KEY=...\n"
            "   BINANCE_API_SECRET=...\n"
            "2) 또는 PowerShell에 임시 설정\n"
            '   $env:BINANCE_API_KEY="..."\n'
            '   $env:BINANCE_API_SECRET="..."\n',
            file=sys.stderr,
        )
        raise SystemExit(2)
    return s


def main(argv: list[str] | None = None) -> int:
    s = _require_keys_from_settings()

    p = argparse.ArgumentParser("quant-real")
    p.add_argument("--interval", default="4h")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--outdir", default="result")
    p.add_argument("--state", default="result/state_real.json")
    p.add_argument("--keep_rows", type=int, default=2500)
    p.add_argument("--initial_days", type=int, default=120)
    p.add_argument("--save_every", type=int, default=50)

    # 실전 안전장치
    p.add_argument("--min_usdt_balance", type=float, default=1.0)
    p.add_argument("--deploy_capital", type=float, default=None)

    args = p.parse_args(argv)

    # cfg = preset_regime_only_live()
    cfg = preset_live_small_test()  # 소액 테스트용 프리셋
    cfg.interval = args.interval

    cfg.binance_api_key = s.binance_api_key
    cfg.binance_api_secret = s.binance_api_secret

    broker = BinanceBroker(cfg)

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
