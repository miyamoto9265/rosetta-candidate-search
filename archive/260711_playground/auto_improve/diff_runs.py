#!/usr/bin/env python3
"""Compare two runs: which queries changed label, improved, or regressed."""
from __future__ import annotations
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# label quality ranking (higher = better outcome for a query)
RANK = {
    "aligned": 4,
    "broader_parent": 3,
    "partial_or_narrower": 2,
    "ambiguous": 1,
    "source_or_ontology_issue": 1,
    "no_consensus": 1,
    "wrong": 0,
    "": 0,
}


def load(tag: str) -> dict[tuple[str, str], dict]:
    p = HERE / "runs" / tag / "records.csv"
    out = {}
    for r in csv.DictReader(p.open(encoding="utf-8-sig")):
        out[(r["dataset"], r["query"])] = r
    return out


def main() -> None:
    a_tag, b_tag = sys.argv[1], sys.argv[2]
    a, b = load(a_tag), load(b_tag)
    keys = sorted(set(a) & set(b))
    improved, regressed, changed_same = [], [], []
    for k in keys:
        la, lb = a[k]["final_label"], b[k]["final_label"]
        if la == lb:
            continue
        ra, rb = RANK[la], RANK[lb]
        entry = (k[0], k[1], la, a[k]["top_name"], lb, b[k]["top_name"])
        if rb > ra:
            improved.append(entry)
        elif rb < ra:
            regressed.append(entry)
        else:
            changed_same.append(entry)

    out = HERE / "runs" / b_tag / f"diff_vs_{a_tag}.txt"
    with out.open("w", encoding="utf-8") as fh:
        def dump(title, items):
            fh.write(f"\n=== {title}: {len(items)} ===\n")
            for ds, q, la, ta, lb, tb in items:
                fh.write(f"[{ds}] {q}\n    {la} ({ta})\n -> {lb} ({tb})\n")
        dump(f"IMPROVED ({a_tag} -> {b_tag})", improved)
        dump("REGRESSED", regressed)
        dump("CHANGED (same rank)", changed_same)
    print(f"improved={len(improved)} regressed={len(regressed)} "
          f"changed_same={len(changed_same)} -> {out}")


if __name__ == "__main__":
    main()
