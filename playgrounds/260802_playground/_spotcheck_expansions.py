#!/usr/bin/env python3
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

rcs = REPO / "rcs"
g = RosettaCandidateGenerator(
    rcs / "HOMBA_v1_fixed.csv",
    token_rules_csv=rcs / "homba_token_rules.csv",
    alias_rules_csv=rcs / "homba_alias_rules.csv",
    abbrev_rules_csv=rcs / "homba_abbrev_rules.csv",
)
queries = [
    "presubiculum",
    "presubiculum (presubicular cortex)",
    "perirhinal cortex",
    "perirhinal cortex (area 35)",
    "posterior hypothalamic nucleus",
    "supraoculomotor nucleus",
    "substantia nigra compact division",
    "substantia nigra, compact division",
    "ventral hippocampus",
    "dorsal hippocampus",
    "hippocampus",
    "ventrolateral preoptic nucleus",
    "organum vasculosum laminae terminalis",
    "intermediate reticular nucleus",
    "interpositus nucleus",
    "interpositus (intermediate) nucleus",
    "lateral interpositus (emboliform) nucleus",
    "pontine reticular formation",
    "inferior olive",
    "dorsal horn of spinal cord",
    "spinal dorsal horn",
    "reticular formation",
    "hypothalamus",
    "ventral striatum",
    "ventral striatum (STRv)",
    "nucleus of diagonal band",
    "anterior pretectal nucleus",
    "lateral hypothalamic area",
    "lateral hypothalamus",
    "Edinger-Westphal nucleus (accessory oculomotor nucleus)",
    "gray matter of midbrain",
    "cerebellar nuclei",
    "anterior hypothalamus",
    "posterior hypothalamus",
]
for q in queries:
    c = g.generate(q, top_k=1)
    top = c[0] if c else None
    if isinstance(top, dict):
        name = top.get("name") or top.get("homba_name")
        hid = top.get("homba_id") or top.get("id") or ""
    else:
        name = getattr(top, "name", None) if top else None
        hid = getattr(top, "homba_id", "") if top else ""
    print(f"{q:55s} -> {name!r}  {hid}")
    if c and isinstance(c[0], dict) and q == queries[0]:
        print("  keys:", sorted(c[0].keys()))
