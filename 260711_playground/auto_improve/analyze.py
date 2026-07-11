#!/usr/bin/env python3
"""Dump wrong / partial cases with reasons + top-3 for root-cause analysis."""
from __future__ import annotations
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    tag = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    labels = sys.argv[2].split(",") if len(sys.argv) > 2 else ["wrong"]
    rows = list(csv.DictReader(
        (HERE / "runs" / tag / "records.csv").open(encoding="utf-8-sig")))
    sel = [r for r in rows if r["final_label"] in labels]
    out = HERE / "runs" / tag / f"analysis_{'_'.join(labels)}.txt"
    with out.open("w", encoding="utf-8") as fh:
        fh.write(f"{'+'.join(labels)}: {len(sel)}\n\n")
        for r in sorted(sel, key=lambda x: (x["dataset"], x["query"])):
            fh.write(f"[{r['dataset']}] {r['query']}\n")
            fh.write(f"   => {r['top_name']} ({r['top_homba_id']})  "
                     f"score={r['score']} methods={r['methods']}\n")
            fh.write(f"   matched_alias={r['matched_alias']!r} "
                     f"matched_query={r['matched_query']!r} mod={r['modifier_terms']!r}\n")
            try:
                top3 = json.loads(r["top3"])
                fh.write("   top3: " + " | ".join(
                    f"{c['name']}({c['score']})" for c in top3) + "\n")
            except Exception:
                pass
            fh.write(f"   p1={r['pass1_label']}: {r['pass1_reason'][:180]}\n")
            fh.write(f"   p3={r['pass3_label']}: {r['pass3_reason'][:180]}\n\n")
    print(f"wrote {out} ({len(sel)} cases)")


if __name__ == "__main__":
    main()
