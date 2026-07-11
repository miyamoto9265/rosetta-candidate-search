#!/usr/bin/env python3
"""Compare two eval output CSVs (by query) and report flag transitions.

Usage: python compare.py corpus_baseline.csv corpus_round3.csv
"""
import csv
import sys
from collections import Counter
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
RANK = {"high_confidence": 3, "needs_review": 2, "modifier_conflict": 2,
        "low_confidence": 1, "no_candidate": 0}


def load(name):
    p = OUTPUT_DIR / name if not Path(name).exists() else Path(name)
    return {r["query"]: r for r in csv.DictReader(p.open(encoding="utf-8"))}


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    trans = Counter()
    improved, regressed = [], []
    for q, ra in a.items():
        rb = b.get(q)
        if not rb:
            continue
        fa, fb = ra["review_flag"], rb["review_flag"]
        trans[(fa, fb)] += 1
        da, db = float(ra["score"]), float(rb["score"])
        if RANK[fb] > RANK[fa] or (db - da) > 0.02:
            improved.append((q, fa, fb, da, db, rb["top_name"]))
        if RANK[fb] < RANK[fa] or (da - db) > 0.02:
            regressed.append((q, fa, fb, da, db, rb["top_name"]))
    print(f"# {sys.argv[1]} -> {sys.argv[2]}")
    print(f"improved: {len(improved)}  regressed: {len(regressed)}")
    print("\n-- transitions (from -> to : count), only changes --")
    for (fa, fb), c in sorted(trans.items(), key=lambda x: -x[1]):
        if fa != fb:
            print(f"  {fa:18s} -> {fb:18s} {c}")
    if regressed:
        print("\n-- REGRESSED --")
        for q, fa, fb, da, db, name in sorted(regressed, key=lambda x: x[3]-x[4]):
            print(f"  {da:.2f}->{db:.2f} {fa}->{fb} | {q[:45]} -> {name[:35]}")


if __name__ == "__main__":
    main()
