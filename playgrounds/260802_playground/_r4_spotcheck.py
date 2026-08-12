#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
print("ENGINE", ENGINE_VERSION)
queries = [
    "TH", "DLS", "CN", "CP", "Acb", "VP", "DMS", "CA1", "ARC", "PPN",
    "dSC", "pTh", "SMT", "PRN", "CeM", "BN", "CUN", "PCx", "OP", "ANT",
    "contralateral MEC", "BLA Ppp1r1b", "CeA-CRF", "MDTGlut", "NAc-S D1-SPNs",
    "paraventricular nucleus", "arcuate nucleus", "caudal CP", "CLN", "vTRN",
    "LCIC", "matrix", "A8", "basal nucleus", "III", "DCN interpositus",
    "dorsolateral PAG", "NAc shell",
]
for q in queries:
    c = g.generate(q, top_k=1)
    if not c:
        print(f"{q:28} NO_MATCH")
    else:
        print(f"{q:28} {c[0]['score']:.3f} {c[0]['name'][:58]}")
