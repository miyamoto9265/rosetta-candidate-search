#!/usr/bin/env python3
"""Mine short-abbrev no_match cases for selective rule addition."""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
rows = list(
    csv.DictReader(
        (HERE / "runs/round4_abbrev/validation_results.csv").open(encoding="utf-8-sig")
    )
)
corpus = list(
    csv.DictReader(
        (REPO / "build_testdata" / "rcs_projection_corpus_curated_non_neocortex.csv").open(
            encoding="utf-8-sig"
        )
    )
)


def is_nm(r):
    return not r.get("top_homba_id")


by = defaultdict(dict)
for r in rows:
    by[r["structure_name"]][r["query_kind"]] = r

corp_fn: dict[str, list[str]] = defaultdict(list)
for r in corpus:
    sn = (r.get("structure_name") or "").strip()
    fn = (r.get("fullname") or "").strip()
    if sn and fn and fn.casefold() != sn.casefold():
        corp_fn[sn].append(fn)

short = []
for r in rows:
    if r["query_kind"] != "abbrev" or not is_nm(r):
        continue
    q = r["query"].strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,7}", q):
        continue
    fn_row = by[r["structure_name"]].get("fullname")
    fn_eval = (fn_row.get("query") if fn_row else "") or ""
    maj = Counter(corp_fn.get(r["structure_name"], [])).most_common(1)
    fn_best = maj[0][0] if maj else (r.get("fullname") or fn_eval)
    short.append(
        {
            "abbrev": q,
            "structure_name": r["structure_name"],
            "n_mentions": int(float(r.get("n_mentions") or 0)),
            "fullname_csv": r.get("fullname") or "",
            "fullname_eval": fn_eval,
            "fullname_corpus_maj": fn_best,
            "has_distinct_fn": bool(fn_best and fn_best.casefold() != q.casefold()),
            "sibling_label": (
                fn_row.get("final_label")
                if fn_row and fn_row.get("top_homba_id")
                else ("no_match" if fn_row else "none")
            ),
            "sibling_top": (fn_row.get("top_name") if fn_row else "") or "",
        }
    )

short.sort(key=lambda x: (-x["n_mentions"], x["abbrev"].lower()))
out = HERE / "nomatch_short_abbrev_candidates.json"
out.write_text(json.dumps(short, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {out} n={len(short)}")
print("--- with distinct fullname ---")
with_fn = [x for x in short if x["has_distinct_fn"]]
print(len(with_fn))
for x in with_fn:
    print(
        f"{x['n_mentions']:>4} {x['abbrev']!r:12} -> {x['fullname_corpus_maj']!r:55} "
        f"sib={x['sibling_label']}"
    )
print("--- abbrev-only ---")
only = [x for x in short if not x["has_distinct_fn"]]
print(len(only))
for x in only:
    print(f"{x['n_mentions']:>4} {x['abbrev']!r}")
