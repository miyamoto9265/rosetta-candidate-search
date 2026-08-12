#!/usr/bin/env python3
"""Spot-check short no_match abbrevs after round5 rules."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

HERE = Path(__file__).resolve().parent
cands = json.loads((HERE / "nomatch_short_abbrev_candidates.json").read_text(encoding="utf-8"))
rcs = REPO / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)

hit = miss = 0
misses = []
hits = []
for row in cands:
    q = row["abbrev"]
    top = (g.generate(q, top_k=1) or [None])[0]
    if top:
        hit += 1
        hits.append((q, top["name"], row.get("n_mentions"), row.get("fullname_corpus_maj")))
    else:
        miss += 1
        misses.append((q, row.get("n_mentions"), row.get("fullname_corpus_maj"), row.get("has_distinct_fn")))

print(f"covered {hit}/{len(cands)}  still_no_match {miss}")
print("\nTOP hits (n>=5):")
for q, name, n, fn in sorted(hits, key=lambda x: -(x[2] or 0))[:40]:
    print(f"  {q:12s} n={n:<3} -> {name}  [{fn}]")
print("\nRemaining misses (n>=4):")
for q, n, fn, has in sorted(misses, key=lambda x: -(x[1] or 0)):
    if (n or 0) >= 4:
        print(f"  {q:12s} n={n:<3} fn={fn!r} distinct={has}")
