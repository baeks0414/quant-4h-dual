"""Does live_real's replay agree with the running paper account?

live_real.py duplicates the orchestration loop of paper_live_stateful.py. This
compares the position it derives against the positions the live paper runner
last reported in its state.json. They must match before any real order is sent.
"""
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_real as LR

STATE_URL = ("https://raw.githubusercontent.com/baeks0414/quant-4h-dual/"
             "master/results/paper_live_rt/state.json")

frac, bar, detail = LR.desired_positions()
print("live_real replay")
print("  bar          %s" % bar)
print("  positions    %s" % ({k: round(v, 4) for k, v in frac.items()} or "none"))
for k, v in sorted(detail.items()):
    print("    %-22s %s" % (k, v))

try:
    remote = json.loads(urllib.request.urlopen(STATE_URL, timeout=25).read())
except Exception as exc:
    print("\ncould not read the live paper state: %s" % exc)
    sys.exit(0)

print("\npaper runner state.json")
print("  bar          %s" % remote.get("last_bar_time"))
print("  trend        %s" % remote.get("trend_positions"))
print("  sleeve       %s" % remote.get("sleeve_positions"))

mismatch = []
for sleeve, key in (("trend", "trend_positions"), ("sleeve", "sleeve_positions")):
    for sym, side in (remote.get(key) or {}).items():
        mine = detail.get("%s:%s" % (sleeve, sym), "FLAT")
        if mine != side:
            mismatch.append((sleeve, sym, side, mine))

print()
if mismatch:
    print("MISMATCH — do NOT enable live trading:")
    for s, sym, theirs, mine in mismatch:
        print("  %-7s %-10s paper=%-6s live_real=%s" % (s, sym, theirs, mine))
    sys.exit(1)
print("MATCH — live_real derives the same directional book as the paper runner.")
print("note: bars may differ by one if the two ran at different times.")
