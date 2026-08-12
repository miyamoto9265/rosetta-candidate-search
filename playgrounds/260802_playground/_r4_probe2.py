#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import (
    RosettaCandidateGenerator,
    query_variants,
    apply_abbrev_rules,
    normalize_text,
)

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
print("CP rules", [r for r in g.abbrev_rules if r.abbrev == "cp"])
print("direct abbrev", apply_abbrev_rules("caudal CP", g.abbrev_rules))
print("direct abbrev caudalis", apply_abbrev_rules("caudalis cp", g.abbrev_rules))
print("variants", query_variants("caudal CP", g.config, g.alias_rules, g.abbrev_rules)[:20])
for c in g.generate("caudal CP", top_k=6):
    print(f"  {c['score']:.3f} {c['name'][:55]} mq={c['matched_query']!r}")
