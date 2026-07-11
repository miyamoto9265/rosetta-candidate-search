#!/usr/bin/env python3
"""Inspect a playground eval output CSV: list queries by review flag.

Usage:
  python analyze.py corpus_baseline.csv low_confidence
  python analyze.py species_baseline.csv needs_review
  python analyze.py corpus_baseline.csv all          # flag distribution only
"""
import csv
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def main():
    name = sys.argv[1]
    flag = sys.argv[2] if len(sys.argv) > 2 else "all"
    path = OUTPUT_DIR / name if not Path(name).exists() else Path(name)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    if flag == "all":
        from collections import Counter
        c = Counter(r["review_flag"] for r in rows)
        for k, v in c.most_common():
            print(f"{k:18s} {v}")
        return
    sel = [r for r in rows if r["review_flag"] == flag]
    sel.sort(key=lambda r: float(r["score"]))
    print(f"{path.name}  flag={flag}  n={len(sel)}")
    for r in sel:
        print(f"{float(r['score']):.2f} | {r['query'][:48]:48s} -> "
              f"{r['top_name'][:38]:38s} [{r['methods']}] "
              f"mq={r['matched_query'][:24]}")


if __name__ == "__main__":
    main()
