# src/quant/cli/__main__.py
from __future__ import annotations

import sys
from quant.cli.live import main as live_main

if __name__ == "__main__":
    # Allow: python -m quant.cli  (defaults to live switcher)
    # e.g. python -m quant.cli --mode paper --interval 1m
    sys.exit(live_main())