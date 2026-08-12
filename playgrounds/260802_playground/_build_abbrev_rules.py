#!/usr/bin/env python3
"""Build corpus-prioritized abbrev rule additions for RCS."""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VAL = HERE / "runs" / "baseline" / "validation_results.csv"
RULES = REPO / "rcs" / "homba_abbrev_rules.csv"
OUT_ADDITIONS = HERE / "abbrev_rules_round1_additions.csv"

rows = list(csv.DictReader(VAL.open(encoding="utf-8-sig")))
by_struct: dict[str, dict[str, dict]] = defaultdict(dict)
for r in rows:
    by_struct[r["structure_name"]][r["query_kind"]] = r

existing = {}
with RULES.open(encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        existing[row["abbrev"].strip().lower()] = row

candidates = []
for structure, kinds in by_struct.items():
    ab = kinds.get("abbrev")
    fn = kinds.get("fullname")
    if not ab:
        continue
    abbrev = ab["query"].strip()
    fullname = (ab.get("fullname") or "").strip()
    if fn and fn.get("query"):
        fullname = fn["query"].strip() or fullname
    if not fullname or fullname.casefold() == abbrev.casefold():
        continue
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,5}", abbrev):
        continue
    if re.search(r"\d{3,}", abbrev):
        continue

    ab_label = ab["final_label"]
    fn_label = fn["final_label"] if fn else ""
    ab_match = bool(ab["top_homba_id"])
    fn_match = bool(fn and fn["top_homba_id"])
    mentions = int(ab.get("n_mentions") or 0)

    if not ab_match and fn_match and fn_label in {"aligned", "broader_parent"}:
        priority = 1
        reason = f"corpus: no_match; fullname {fn_label}"
    elif ab_label == "wrong" and fn_label == "aligned":
        priority = 2
        reason = "corpus: abbrev wrong, fullname aligned (HOMBA acronym collision)"
    elif ab_label == "wrong" and float(ab.get("score") or 0) >= 0.9 and fn_match and fn_label in {"aligned", "broader_parent", "partial_or_narrower"}:
        priority = 3
        reason = "corpus: high-conf abbrev collision"
    elif not ab_match and mentions >= 10 and fullname:
        priority = 4
        reason = "corpus: frequent abbrev no_match"
    else:
        continue

    if abbrev.lower() in existing:
        continue
    # Prefer literature expansion; keep readable
    candidates.append(
        {
            "priority": priority,
            "abbrev": abbrev,
            "expansion": fullname,
            "mentions": mentions,
            "notes": reason,
        }
    )

best: dict[str, dict] = {}
for c in candidates:
    k = c["abbrev"].lower()
    prev = best.get(k)
    if prev is None or (c["priority"], -c["mentions"]) < (prev["priority"], -prev["mentions"]):
        best[k] = c

selected = []
for c in sorted(best.values(), key=lambda x: (x["priority"], -x["mentions"], x["abbrev"].lower())):
    if c["priority"] in {1, 2}:
        selected.append(c)
    elif c["priority"] == 3 and c["mentions"] >= 5:
        selected.append(c)
    elif c["priority"] == 4 and c["mentions"] >= 15:
        selected.append(c)

with OUT_ADDITIONS.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["abbrev", "expansion", "notes", "priority", "mentions"])
    w.writeheader()
    for c in selected:
        w.writerow(c)

print(f"selected {len(selected)} new rules -> {OUT_ADDITIONS}")
print("p1", sum(1 for c in selected if c["priority"] == 1))
print("p2", sum(1 for c in selected if c["priority"] == 2))
print("p3", sum(1 for c in selected if c["priority"] == 3))
print("p4", sum(1 for c in selected if c["priority"] == 4))
for c in selected[:15]:
    print(f"  {c['abbrev']:<10} -> {c['expansion'][:50]}")
