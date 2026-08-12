#!/usr/bin/env python3
"""Mine high-value abbrev rules from baseline validation + curated corpus."""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VAL = HERE / "runs" / "baseline" / "validation_results.csv"
CURATED = REPO / "build_testdata" / "rcs_projection_corpus_curated_non_neocortex.csv"
ABBREV_RULES = REPO / "rcs" / "homba_abbrev_rules.csv"

rows = list(csv.DictReader(VAL.open(encoding="utf-8-sig")))
by_struct: dict[str, dict[str, dict]] = defaultdict(dict)
for r in rows:
    by_struct[r["structure_name"]][r["query_kind"]] = r

existing = set()
with ABBREV_RULES.open(encoding="utf-8-sig") as fh:
    for row in csv.DictReader(fh):
        existing.add((row["abbrev"].strip().lower(), row["expansion"].strip().lower()))

# Candidate rules from abbrev no_match / wrong where fullname is aligned or has a hit
candidates = []
for structure, kinds in by_struct.items():
    ab = kinds.get("abbrev")
    fn = kinds.get("fullname")
    if not ab:
        continue
    abbrev = ab["query"].strip()
    # Prefer corpus fullname; fall back to validation fullname field
    fullname = (ab.get("fullname") or "").strip()
    if fn and fn.get("query"):
        # when we have a fullname query row, use that string
        fullname = fn["query"].strip() or fullname
    if not fullname or fullname.casefold() == abbrev.casefold():
        continue
    # Only short-ish acronyms
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,5}", abbrev):
        continue
    if " " in abbrev:
        continue

    ab_label = ab["final_label"]
    fn_label = fn["final_label"] if fn else ""
    ab_match = bool(ab["top_homba_id"])
    fn_match = bool(fn and fn["top_homba_id"])
    mentions = int(ab.get("n_mentions") or 0)

    priority = None
    reason = ""
    if not ab_match and fn_match and fn_label in {"aligned", "broader_parent"}:
        priority = 1
        reason = f"no_match→fullname_{fn_label}"
    elif ab_label == "wrong" and fn_label == "aligned":
        priority = 2
        reason = "abbrev_wrong_fullname_aligned"
    elif ab_label == "wrong" and float(ab.get("score") or 0) >= 0.9 and fn_match:
        priority = 3
        reason = "abbrev_wrong_highconf"
    elif not ab_match and fullname:
        priority = 4
        reason = "abbrev_no_match_has_fullname"
    if priority is None:
        continue
    key = (abbrev.lower(), fullname.lower())
    if key in existing:
        continue
    candidates.append(
        {
            "priority": priority,
            "abbrev": abbrev,
            "expansion": fullname,
            "mentions": mentions,
            "reason": reason,
            "ab_label": ab_label,
            "fn_label": fn_label,
            "ab_top": ab.get("top_name", ""),
            "fn_top": (fn or {}).get("top_name", ""),
        }
    )

# Dedup by abbrev keeping highest mentions / best priority
best: dict[str, dict] = {}
for c in candidates:
    k = c["abbrev"].lower()
    prev = best.get(k)
    if prev is None or (c["priority"], -c["mentions"]) < (prev["priority"], -prev["mentions"]):
        best[k] = c

ranked = sorted(best.values(), key=lambda c: (c["priority"], -c["mentions"], c["abbrev"].lower()))
print(f"candidates unique abbrevs: {len(ranked)}")
print("by priority", Counter(c["priority"] for c in ranked))
print("\n=== TOP priority 1 (no_match, fullname good) ===")
for c in [x for x in ranked if x["priority"] == 1][:40]:
    print(f"  {c['mentions']:>4} {c['abbrev']:<12} -> {c['expansion'][:55]}  [{c['reason']}] fn_top={c['fn_top'][:40]}")
print("\n=== TOP priority 2/3 (wrong collisions) ===")
for c in [x for x in ranked if x["priority"] in {2, 3}][:40]:
    print(f"  {c['mentions']:>4} {c['abbrev']:<12} -> {c['expansion'][:55]}  wrong→{c['ab_top'][:40]}")
