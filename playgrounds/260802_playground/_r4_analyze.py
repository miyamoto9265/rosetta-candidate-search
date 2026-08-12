#!/usr/bin/env python3
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

HERE = Path(__file__).resolve().parent
rows = list(
    csv.DictReader(
        (HERE / "runs/round3_abbrev/validation_results.csv").open(encoding="utf-8-sig")
    )
)


def lab(r):
    return "no_match" if not r.get("top_homba_id") else (r.get("final_label") or "uncertain")


hw = [
    r
    for r in rows
    if r["query_kind"] == "abbrev"
    and lab(r) == "wrong"
    and float(r.get("score") or 0) >= 0.75
]
print("high wrong", len(hw))
for r in sorted(hw, key=lambda x: -float(x.get("score") or 0))[:45]:
    print(
        f"{float(r['score']):.2f} | {r['query']!r:32} | "
        f"top={(r.get('top_name') or '')[:45]!r} | fn={(r.get('fullname') or '')[:40]!r}"
    )

by = defaultdict(dict)
for r in rows:
    by[r["structure_name"]][r["query_kind"]] = r
print("--- nm good ---")
nm_good = []
for sn, d in by.items():
    a, f = d.get("abbrev"), d.get("fullname")
    if a and lab(a) == "no_match" and f and lab(f) in ("aligned", "broader_parent"):
        nm_good.append((a["query"], f["query"], lab(f), f.get("top_name", "")))
print("count", len(nm_good))
for q, fn, lbl, top in nm_good:
    print(f"  {q!r} => {fn[:50]!r} [{lbl}] {top[:40]!r}")

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
print("--- probe ---")
for q in [
    "TH",
    "dSC",
    "pTh",
    "DC",
    "ipsilateral DC",
    "contralateral MEC",
    "matrix",
    "SMT",
    "SPA",
    "Su3",
    "basal nucleus",
    "BLA Ppp1r1b",
    "CeA-CRF",
    "NAc-S D1-SPNs",
    "paraventricular nucleus",
    "arcuate nucleus",
    "caudal CP",
    "CLN",
    "vTRN",
    "LCIC",
]:
    c = g.generate(q, top_k=2)
    if not c:
        print(f"{q:28} NO_MATCH")
    else:
        print(f"{q:28} {c[0]['score']:.3f} {c[0]['name'][:55]} mq={c[0].get('matched_query')!r}")
