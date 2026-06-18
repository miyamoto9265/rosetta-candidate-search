"""Search HOMBA for terms matching a keyword."""
import csv
import sys

from cursor_rcs_paths import HOMBA_CSV

keyword = sys.argv[1].lower() if len(sys.argv) > 1 else "raphe"
hits = []
with HOMBA_CSV.open(newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        name = row.get("unified_ontology_name", "")
        if keyword in name.lower():
            hits.append((row.get("unified_ontology_id", ""), name, row.get("parent_identifier", "")))

for h in hits:
    print(f"  {h[0]:12} {h[1][:60]}  parent={h[2]}")
print(f"\n{len(hits)} matches for '{keyword}'")
