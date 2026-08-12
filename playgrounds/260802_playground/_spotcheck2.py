#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, query_variants

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
for q in [
    "dorsolateral PAG",
    "ventrolateral PAG",
    "lateral VTA",
    "medial NAc",
    "BLA.ac",
    "deep dorsal horn (laminae III-IV)",
    "DCN interpositus",
    "lateral NAcc",
    "NAc shell",
]:
    print("===", q)
    print(" variants:", query_variants(q, g.config, g.alias_rules, g.abbrev_rules)[:8])
    for c in g.generate(q, top_k=2):
        print(f"  {c['score']:.3f} {c['name'][:60]}")
