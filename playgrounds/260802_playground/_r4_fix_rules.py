#!/usr/bin/env python3
import csv
from pathlib import Path

p = Path(__file__).resolve().parents[2] / "rcs" / "homba_abbrev_rules.csv"
rows = list(csv.DictReader(p.open(encoding="utf-8-sig", newline="")))
for r in rows:
    if r["abbrev"] == "BN":
        r["expansion"] = "Barrington's nucleus"
        print("BN ->", r["expansion"])
    if r["abbrev"] == "CeM":
        r["expansion"] = "medial division of central nucleus"
        print("CeM ->", r["expansion"])
with p.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["abbrev", "expansion", "notes"], lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
