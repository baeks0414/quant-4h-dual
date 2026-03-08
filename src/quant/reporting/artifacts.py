from __future__ import annotations

import os
import pandas as pd


def save_csvs(equity_curve: pd.DataFrame, trades: pd.DataFrame, outdir: str, tag: str):
    os.makedirs(outdir, exist_ok=True)
    eq_path = os.path.join(outdir, f"equity_curve_{tag}.csv")
    tr_path = os.path.join(outdir, f"trades_{tag}.csv")

    if equity_curve is not None and not equity_curve.empty:
        equity_curve.to_csv(eq_path)
    else:
        pd.DataFrame().to_csv(eq_path)

    if trades is not None and not trades.empty:
        trades.to_csv(tr_path, index=False)
    else:
        pd.DataFrame().to_csv(tr_path, index=False)

    return eq_path, tr_path
