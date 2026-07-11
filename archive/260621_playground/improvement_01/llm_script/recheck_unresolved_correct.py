#!/usr/bin/env python3
"""Re-review 3_unresolved_correct.csv and move mis-filed rows to 4_*.

After a second full read of all 302 "effectively correct" rows, the rows below
have a top-1 that is anatomically WRONG (not the true structure and not a true
ancestor of it - i.e. a sibling / different region / wrong structure type).
They were mis-filed as A and are moved to 4_unresolved_incorrect.csv with
_category=B_algo and a specific reason.

Rows that are merely COARSE (a correct parent/ancestor of the true structure)
stay in file 3 - those are still effectively correct.
"""
from __future__ import annotations

import csv
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "csv_analysis"
F3 = DIR / "3_unresolved_correct.csv"
F4 = DIR / "4_unresolved_incorrect.csv"

# (dataset, query) -> reason. These move to file 4.
MOVE: dict[tuple[str, str], str] = {
    ("corpus", "Intracalcarine cortex (superior)"):
        "LLM re-review: occipital intracalcarine (V1) -> parietal cortex (wrong lobe)",
    ("corpus", "Intracalcarine cortex (inferior)"):
        "LLM re-review: occipital intracalcarine (V1) -> parietal cortex (wrong lobe)",
    ("corpus", "Central opercular cortex (posterior)"):
        "LLM re-review: operculum -> frontal motor cortex via lone 'posterior' (weak-token trap)",
    ("corpus", "Temporal horn of the lateral ventricle"):
        "LLM re-review: temporal(inferior) horn -> rostral/anterior horn (wrong sibling horn)",
    ("species", "Central opercular cortex, posterior"):
        "LLM re-review: operculum -> frontal motor cortex via lone 'posterior' (weak-token trap)",
    ("species", "Supratemporal plane, posterior"):
        "LLM re-review: temporal plane -> caudal branch of anterior commissure (weak-token trap)",
    ("species", "Lateral parietal cortex, superior"):
        "LLM re-review: lateral parietal -> superior MEDIAL parietal (lateral vs medial mismatch)",
    ("species", "Laterodorsal thalamic nucleus, dorsomedial part"):
        "LLM re-review: LD nucleus -> ventral midline nuclei (parent over-promotion; LD exists)",
    ("species", "Ventroposterior medial and lateral thalamic nuclei"):
        "LLM re-review: VPM/VPL thalamus -> LaV amygdala subdivision (wrong structure)",
    ("species", "Orbital cortex (ventrolateral)"):
        "LLM re-review: orbitofrontal -> ventrolateral TEMPORAL cortex (wrong lobe)",
    ("species", "Basomedial amygdaloid nucleus"):
        "LLM re-review: basomedial -> basolateral group (distinct nucleus; correct at rank2)",
    ("species", "Mesencephalic Reticular Formation"):
        "LLM re-review: mesencephalic -> isthmic RF (midbrain reticular formation exists)",
    ("species", "Ventral periolivary nuclei"):
        "LLM re-review: periolivary -> solitary nucleus via 'ventral' (correct at rank2)",
    ("species", "4th ventricle"):
        "LLM re-review: -> olfactory recess via 'ventricle' (fourth ventricle is rank2)",
    ("species", "Dorsal Medial Hypothalamic Nucleus"):
        "LLM re-review: DMH -> ventromedial hypothalamic division (DMH is rank2)",
    ("species", "Lateral Ventral Amygdaloid Nucleus"):
        "LLM re-review: nucleus -> ventral amygdaloid efferent PATH (wrong structure type)",
    ("species", "Paraventricular hypothalamic nucleus (medial parvicellular dorsal zone)"):
        "LLM re-review: PVN -> ventromedial hypothalamic division (wrong nucleus)",
    ("species", "Retrosplenial dysgranular area"):
        "LLM re-review: retrosplenial -> area prostriata (distinct area; retrosplenial is rank2)",
}

FLAG_ORDER = {"high_confidence": 0, "needs_review": 1,
              "modifier_conflict": 2, "low_confidence": 3, "no_candidate": 4}


def read(p: Path):
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    return list(rows[0].keys()), rows


def write(p: Path, cols, rows):
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    cols3, rows3 = read(F3)
    cols4, rows4 = read(F4)

    keep, moved = [], []
    for r in rows3:
        key = (r["dataset"], r["query"])
        if key in MOVE:
            r["_category"] = "B_algo"
            r["_mechanism"] = MOVE[key]
            moved.append(r)
        else:
            keep.append(r)

    found = {(r["dataset"], r["query"]) for r in moved}
    missing = set(MOVE) - found
    if missing:
        raise SystemExit(f"ERROR: these MOVE keys not found in file 3: {missing}")

    rows4_new = rows4 + moved
    rows4_new.sort(key=lambda r: (r["dataset"], FLAG_ORDER.get(r["review_flag"], 9),
                                  float(r["score"] or 0), r["query"].lower()))

    write(F3, cols3, keep)
    write(F4, cols4, rows4_new)

    print(f"file 3: {len(rows3)} -> {len(keep)} (moved out {len(moved)})")
    print(f"file 4: {len(rows4)} -> {len(rows4_new)} (moved in {len(moved)})")
    print(f"total preserved: {len(keep) + len(rows4_new)} (= {len(rows3)+len(rows4)})")


if __name__ == "__main__":
    main()
