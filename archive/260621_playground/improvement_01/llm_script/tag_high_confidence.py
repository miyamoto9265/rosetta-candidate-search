#!/usr/bin/env python3
"""Add an llm_check column to resolved_high_confidence.csv.

All 423 high_confidence rows were read and judged for anatomical correctness of
the top-1 HOMBA mapping. Tags:

  correct        - top-1 is the right entry (exact / accepted synonym / spelling
                   / word-order variant), or a correct parent where HOMBA has no
                   finer entry and the query carries no extra concept.
  correct_parent - top-1 is the correct PARENT; the query's subdivision is not a
                   distinct HOMBA entry, so the parent is the honest answer
                   (effectively correct, but granularity was dropped).
  questionable   - top-1 is debatable: an arbitrary one of several subdivisions,
                   a parent returned although a finer correct entry exists, a
                   structure-type mismatch (e.g. tract -> nucleus), or an
                   ambiguous term that needs a human decision.
  wrong          - top-1 is anatomically incorrect.

Default is "correct"; the exception sets below are the only non-correct rows.
"""
from __future__ import annotations

import csv
from pathlib import Path

CSV = Path(__file__).resolve().parent / "csv_analysis" / "resolved_high_confidence.csv"

WRONG = {
    # "Anterior nucleus (thalamus)" -> rostral division of pulvinar; should be
    # anterior nuclear complex of thalamus (rank2 is ventral anterior n.).
    "Anterior nucleus (thalamus)",
}

QUESTIONABLE = {
    "Area 43",                       # picked caudal division; "area 43" unqualified = subcentral cortex parent
    "Internal globus pallidus",      # returned GP parent; "internal division of globus pallidus" exists (rank2)
    "Ventral posterior internal thalamic nucleus",  # "internal"(inferior?) ambiguous; complex parent returned
    "Basal Nucleus",                 # ambiguous (Meynert / amygdala / basal ganglia) -> basal ganglia
    "Medial parietal cortex",        # narrowed to "superior medial parietal cortex"
    "Inferior colliculus, dorsal cortex",   # dorsal cortex != dorsal central nucleus
    "Inferior colliculus, central nucleus", # parent IC returned; central nucleus of IC exists (rank2)
    "Lateral hypothalamic area",     # returned tuberal-part subdivision, not general LHA
    "Posterior interstitial nucleus of the anterior commissure",  # mapped to POSTERIOR commissure nucleus
    "Medial geniculate complex (medial division)",  # parent complex; medial division of MGN exists
    "Vestibular nucleus",            # pons/medulla split -> arbitrary "vestibular nuclei in pons"
    "Vestibular Nucleus",
    "Ansiform Lobule Crus1",         # parent lobule VII; ansiform lobule VIIA exists (rank2)
    "Ansiform Lobule Crus2",
    "Lateral olfactory tract",       # tract mapped to its NUCLEUS (structure-type mismatch)
    "Posterior intralaminar nucleus",# caudal intralaminar GROUP; PIL is the precise match (rank2)
}

CORRECT_PARENT = {
    "Middle frontal gyrus (middle)",
    "Lateral posterior thalamic nucleus, lateral part",
    "Lateral posterior thalamic nucleus, mediocaudal part",
    "Lateral posterior thalamic nucleus, mediorostral part",
    "Ventral cochlear nucleus, cap area",
    "Ventral cochlear nucleus, anterior part",
    "Lateral lemniscus, commissure",
}


def tag(query: str) -> str:
    if query in WRONG:
        return "wrong"
    if query in QUESTIONABLE:
        return "questionable"
    if query in CORRECT_PARENT:
        return "correct_parent"
    return "correct"


def main() -> None:
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    cols = list(rows[0].keys())
    if "llm_check" not in cols:
        cols.append("llm_check")
    counts: dict[str, int] = {}
    for r in rows:
        t = tag(r["query"])
        r["llm_check"] = t
        counts[t] = counts.get(t, 0) + 1
    with CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"tagged {len(rows)} rows in {CSV.name}")
    for t in ("correct", "correct_parent", "questionable", "wrong"):
        print(f"  {t:14s} {counts.get(t, 0)}")


if __name__ == "__main__":
    main()
