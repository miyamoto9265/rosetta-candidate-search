#!/usr/bin/env python3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from rcs.rosetta_candidate_generator import (
    RosettaCandidateGenerator,
    query_variants,
    string_similarity,
    normalize_text,
    tokenize,
)

rcs = Path(__file__).resolve().parents[2] / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
for q in [
    "TH", "DLS", "CN", "CP", "Acb", "ANT", "PRN", "SMT", "dSC", "pTh",
    "CeM", "PAL", "CUN", "Bs", "CS", "PCx", "OP", "BN", "basal nucleus",
]:
    print("===", q)
    print(" variants", query_variants(q, g.config, g.alias_rules, g.abbrev_rules)[:8])
    for c in g.generate(q, top_k=4):
        print(
            f"  {c['score']:.3f} {c['name'][:55]} mq={c['matched_query']!r} "
            f"methods={c['methods']}"
        )

# sim checks
pairs = [
    ("cerebral nuclei", "cerebellar nuclei"),
    ("medial division of PHC (area TH)", "thalamus"),
    ("(dorso)lateral sulcus", "dorsolateral striatum"),
    ("cortical plate of neocortex", "caudate putamen"),
    ("stria medullaris of thalamus", "sensorimotor thalamus"),
    ("dorsal spinocerebellar tract", "deep superior colliculus"),
    ("pallidothalamic tract", "prethalamus"),
]
print("--- sims ---")
for a, b in pairs:
    print(f"{string_similarity(a,b):.3f} | {a} || {b}")
    print("  toks", tokenize(a), "embeds th?", "th" in tokenize("medial division of PHC (area TH)"))
