import sys

from cursor_rcs_paths import ALIAS_RULES_CSV, HOMBA_CSV, RCS_DIR

sys.path.insert(0, str(RCS_DIR))
from rosetta_candidate_generator import RosettaCandidateGenerator

g = RosettaCandidateGenerator(HOMBA_CSV, alias_rules_csv=ALIAS_RULES_CSV)
for q in ["PVN", "GPe", "GPi", "CA1", "CA3", "LC", "NTS", "DG", "SC", "IC", "SN"]:
    r = g.generate(q, top_k=3)
    print(f"--- {q} ---")
    for c in r:
        print(f"  {c['score']:.4f}  {c['name'][:55]}  [{c['methods']}]  {c['matched_alias'][:30]}")
