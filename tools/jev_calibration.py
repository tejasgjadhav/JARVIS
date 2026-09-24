"""Check Jev's calibration against what prices actually did.

Reads data/jev_decisions.jsonl (one row per final decision), fetches the
current price for each symbol, and reports the return since the decision,
grouped by verdict and by confidence band. This is the outcome-labelled
validation the TypeSafe docs ask for; it becomes meaningful once the log
holds a few dozen decisions that are at least a month old.

Usage: python3 tools/jev_calibration.py [min_age_days]
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

import yfinance as yf

LOG = Path(__file__).resolve().parent.parent / "data" / "jev_decisions.jsonl"
MIN_AGE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
DIRECTION = {"BUY": 1, "ACCUMULATE": 1, "HOLD": 0, "REDUCE": -1, "SELL": -1}

rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()] if LOG.exists() else []
if not rows:
    sys.exit(f"No decisions logged yet at {LOG}")

now = datetime.now()
rows = [r for r in rows if (now - datetime.fromisoformat(r["ts"])).days >= MIN_AGE]
if not rows:
    sys.exit(f"No decisions older than {MIN_AGE} days")

prices = {}
for sym in sorted({r["symbol"] for r in rows}):
    try:
        prices[sym] = float(yf.Ticker(sym).fast_info["last_price"])
    except Exception as exc:
        print(f"{sym}: price fetch failed ({exc})")

by_verdict, by_conf = defaultdict(list), defaultdict(list)
print(f"{'date':<11}{'symbol':<13}{'verdict':<11}{'conf':>5}{'stance':>7}{'then':>10}{'now':>10}{'ret%':>7}  right?")
for r in rows:
    px = prices.get(r["symbol"])
    if not px:
        continue
    ret = (px / r["price"] - 1) * 100
    d = DIRECTION.get(r["verdict"], 0)
    right = "n/a" if d == 0 else ("yes" if ret * d > 0 else "no")
    by_verdict[r["verdict"]].append(ret)
    band = "high" if r["confidence"] >= 0.7 else ("medium" if r["confidence"] >= 0.4 else "low")
    if d:
        by_conf[band].append(ret * d > 0)
    print(f"{r['ts'][:10]:<11}{r['symbol']:<13}{r['verdict']:<11}{r['confidence']:>5.2f}{r['stance']:>7.2f}"
          f"{r['price']:>10,.0f}{px:>10,.0f}{ret:>7.1f}  {right}")

print("\nMean return since decision, by verdict (a well-calibrated judge shows BUY > ACCUMULATE > HOLD > REDUCE > SELL):")
for v in ("BUY", "ACCUMULATE", "HOLD", "REDUCE", "SELL"):
    if by_verdict.get(v):
        print(f"  {v:<11} n={len(by_verdict[v]):<3} mean {mean(by_verdict[v]):+.1f}%")
print("\nDirection hit rate by confidence band (should rise with confidence):")
for b in ("high", "medium", "low"):
    if by_conf.get(b):
        print(f"  {b:<7} n={len(by_conf[b]):<3} hit {100*mean(by_conf[b]):.0f}%")
