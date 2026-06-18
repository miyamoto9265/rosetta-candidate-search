"""Inspect the 5 worsened queries to understand root cause."""

import sys

from cursor_rcs_paths import ALIAS_RULES_CSV, HOMBA_CSV, RCS_DIR

sys.path.insert(0, str(RCS_DIR))
from rosetta_candidate_generator import RosettaCandidateGenerator

g = RosettaCandidateGenerator(HOMBA_CSV, alias_rules_csv=ALIAS_RULES_CSV)
for q in ["Insular cortex", "Raphe nuclei", "Arcuate nucleus", "Septum", "Thalamic nuclei"]:
    r = g.generate(q, top_k=3)
    print(f"--- {q} ---")
    for c in r:
        print(f"  {c['score']:.4f} [{c['methods']:30}]  {c['name'][:50]}")
        if c.get("hierarchy_reason"):
            print(f"         hierarchy: {c['hierarchy_reason']}")
