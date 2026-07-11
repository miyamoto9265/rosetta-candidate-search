#!/usr/bin/env python3
"""Reconstruct the round3 results into three review datasets.

1. resolved_high_confidence.csv
   Flag-based provisional correct: the high_confidence rows from
   corpus_round3 / species_round3 that were NOT collected into
   unresolved_round3.csv. Same columns as unresolved_round3.csv.

2. classified_A_effectively_correct.csv
   The "A 実質正解" rows from unresolved_classified.csv.

3. classified_non_A.csv
   Everything except A (= B/C/D/E) from unresolved_classified.csv.
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"

UNRESOLVED_COLS = [
    "dataset", "query", "review_flag", "score", "top_homba_id", "top_name",
    "methods", "matched_query", "matched_alias", "modifier_terms",
    "modifier_match_score", "rank2_name", "rank2_score",
]


def read(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write(path: Path, rows: list[dict], cols: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  {path.name:42s} {len(rows):4d} rows")


def main() -> None:
    flag_order = {"high_confidence": 0, "needs_review": 1,
                  "modifier_conflict": 2, "low_confidence": 3, "no_candidate": 4}

    # --- dataset 1: flag-based provisional correct (high_confidence) ----------
    resolved: list[dict] = []
    for ds, fname in [("corpus", "corpus_round3.csv"), ("species", "species_round3.csv")]:
        for r in read(OUT / fname):
            if r["review_flag"] != "high_confidence":
                continue
            r["dataset"] = ds
            resolved.append(r)
    resolved.sort(key=lambda r: (r["dataset"], -float(r["score"] or 0), r["query"].lower()))

    # --- datasets 2 & 3: split classified by category A ----------------------
    classified = read(HERE / "unresolved_classified.csv")
    cls_cols = list(classified[0].keys())
    cat_a = [r for r in classified if r["_category"] == "A_effectively_correct"]
    non_a = [r for r in classified if r["_category"] != "A_effectively_correct"]

    def keyf(r):
        return (r["dataset"], flag_order.get(r["review_flag"], 9),
                float(r["score"] or 0), r["query"].lower())

    cat_a.sort(key=keyf)
    non_a.sort(key=keyf)

    print("written:")
    write(HERE / "resolved_high_confidence.csv", resolved, UNRESOLVED_COLS)
    write(HERE / "classified_A_effectively_correct.csv", cat_a, cls_cols)
    write(HERE / "classified_non_A.csv", non_a, cls_cols)

    total = len(resolved) + len(cat_a) + len(non_a)
    print(f"\nrecord totals: high={len(resolved)} + A={len(cat_a)} + non-A={len(non_a)} = {total}")
    print("corpus+species unique queries should equal high + (A + non-A=unresolved 498)")


if __name__ == "__main__":
    main()
