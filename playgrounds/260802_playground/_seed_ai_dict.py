"""Seed the curated AI reference dictionary from observed AI regressions.

Takes records where AI changed an aligned off-result into wrong/partial and
writes rcs/homba_ai_reference_dict.csv with the *correct* mapping (off side).
"""
import csv
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RECS = REPO / "playgrounds/260802_playground/runs/ai_eval/records.json"
OUT = REPO / "rcs/homba_ai_reference_dict.csv"

recs = json.loads(RECS.read_text(encoding="utf-8"))
rows = []
seen = set()
for r in recs:
    if not (r["changed"] and r["off_label"] == "aligned" and r["ai_label"] in ("wrong", "partial_or_narrower")):
        continue
    ab = r["query"].strip()
    key = ab.casefold()
    if key in seen or not r["off_id"]:
        continue
    seen.add(key)
    rows.append(
        {
            "abbrev": ab,
            "homba_id": r["off_id"],
            "homba_name": r["off_name"],
            "note": "ai_eval regression: AI picked "
            + (r["ai_name"] or "")[:60]
            + "; corrected to literature-conventional sense",
        }
    )

rows.sort(key=lambda x: x["abbrev"].casefold())
with OUT.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["abbrev", "homba_id", "homba_name", "note"])
    w.writeheader()
    w.writerows(rows)
print(f"wrote {OUT} ({len(rows)} rows)")
for r in rows:
    print(f"  {r['abbrev']:10} -> {r['homba_id']} {r['homba_name'][:50]}")
