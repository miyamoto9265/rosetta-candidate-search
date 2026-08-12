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
    "Thal", "PreS", "PeRh", "vHipp", "dcHPC", "PiCo", "PH", "SOA",
    "CINs", "pretectum", "DH", "HP", "VH", "ARN", "ADn", "vHC", "DM",
]:
    c = g.generate(q, top_k=2)
    v = query_variants(q, g.config, g.alias_rules, g.abbrev_rules)[:5]
    if not c:
        print(f"{q:10} NO_MATCH  variants={v}")
    else:
        print(f"{q:10} {c[0]['score']:.2f} {c[0]['name'][:45]}  variants={v}")
