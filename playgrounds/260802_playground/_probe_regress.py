#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, query_variants

REPO = Path(__file__).resolve().parents[2]
rcs = REPO / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
queries = [
    "CA1",
    "ARC",
    "VP",
    "DMS",
    "PPN",
    "DCN interpositus",
    "EC III",
    "lateral NAcc",
    "medial NAcc",
    "lateral MDT",
    "deep dorsal horn (laminae III-IV)",
    "III",
    "DCN",
    "NAcc",
]
for q in queries:
    print("===", q)
    print(" variants:", query_variants(q, g.config, g.alias_rules, g.abbrev_rules)[:14])
    for c in g.generate(q, top_k=3):
        print(
            f"  {c['score']:.3f} {c['name'][:55]} mq={c['matched_query']!r} "
            f"methods={c.get('methods')}"
        )
