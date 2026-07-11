#!/usr/bin/env python3
"""Seed the judgement cache from the v1 validation results.

The v1 CSV already contains 3-pass DeepSeek judgements for 921 (query, top-1)
pairs.  Re-using them means the baseline run and any improvement that keeps the
same top-1 for a query costs zero API calls.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V1_CSV = HERE.parent / "top1_consistency_review" / "v1" / "validation_results.csv"
CACHE_PATH = HERE / "cache" / "judgements.json"


def cache_key(dataset: str, query: str, top_id: str) -> str:
    return f"{dataset}||{query}||{top_id}"


def main() -> None:
    cache: dict = {}
    if CACHE_PATH.exists():
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    added = 0
    with V1_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            key = cache_key(r["dataset"], r["query"], r["top_homba_id"])
            entry = cache.setdefault(key, {})
            for src, dst in (("pass1", "pass1"), ("pass2", "pass2"), ("pass3", "pass3")):
                label = r.get(f"{src}_label", "")
                if not label or dst in entry:
                    continue
                try:
                    conf = float(r.get(f"{src}_confidence") or 0)
                except ValueError:
                    conf = 0.0
                entry[dst] = {
                    "label": label,
                    "certainty": r.get(f"{src}_certainty", "") or "medium",
                    "confidence": conf,
                    "reason": r.get(f"{src}_reason", "") or "",
                }
                added += 1

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"seeded {added} pass-judgements across {len(cache)} keys -> {CACHE_PATH}")


if __name__ == "__main__":
    main()
