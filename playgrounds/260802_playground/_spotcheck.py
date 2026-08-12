#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
queries = [
    "CA1", "CA2", "CA3", "VTA", "LC", "BLA", "NAc", "contra-DMS", "ipsi-DMS",
    "LS", "LHb", "Cd", "MEC", "TRN", "VP", "DMS", "ARC", "PPN", "III",
    "DCN", "DCN interpositus", "lateral NAcc", "lateral MDT", "EC III",
]
for q in queries:
    c = g.generate(q, top_k=1)[0]
    print(f"{q:22} {c['score']:.3f} {c['name'][:65]}")
