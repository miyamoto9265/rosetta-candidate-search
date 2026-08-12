#!/usr/bin/env python3
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load(tag: str):
    rows = list(
        csv.DictReader(
            (HERE / "runs" / tag / "validation_results.csv").open(
                encoding="utf-8-sig"
            )
        )
    )
    summary = json.loads(
        (HERE / "runs" / tag / "summary.json").read_text(encoding="utf-8")
    )
    return rows, summary


def lab(r: dict) -> str:
    if not r.get("top_homba_id"):
        return "no_match"
    return r.get("final_label") or "uncertain"


RANK = {
    "aligned": 0,
    "broader_parent": 1,
    "partial_or_narrower": 2,
    "wrong": 3,
    "ambiguous": 4,
    "source_or_ontology_issue": 5,
    "no_consensus": 5,
    "no_match": 6,
    "uncertain": 5,
}


def compare(a_tag: str, b_tag: str):
    a, _ = load(a_tag)
    b, _ = load(b_tag)
    am = {(r["query_kind"], r["query"]): r for r in a}
    bm = {(r["query_kind"], r["query"]): r for r in b}
    improved, regressed = [], []
    for k, br in bm.items():
        ar = am.get(k)
        if not ar:
            continue
        al, bl = lab(ar), lab(br)
        if al == bl:
            continue
        row = (
            k[0],
            al,
            bl,
            k[1],
            ar.get("top_name", ""),
            br.get("top_name", ""),
        )
        if RANK.get(bl, 9) < RANK.get(al, 9):
            improved.append(row)
        elif RANK.get(bl, 9) > RANK.get(al, 9):
            regressed.append(row)
    return improved, regressed


for tag in ["baseline", "round1_abbrev", "round2_abbrev"]:
    _, s = load(tag)
    o = s["overall"]["label_counts"]
    print(
        tag,
        "no_match",
        s.get("no_match_n"),
        "aligned",
        o.get("aligned"),
        "broader",
        o.get("broader_parent"),
        "wrong",
        o.get("wrong"),
        "soi",
        o.get("source_or_ontology_issue"),
    )
    ab = s["datasets"]["non_neocortex_abbrev"]["label_counts"]
    print(
        "  abbrev aligned",
        ab.get("aligned"),
        "wrong",
        ab.get("wrong"),
        "soi",
        ab.get("source_or_ontology_issue"),
        "broader",
        ab.get("broader_parent"),
    )

imp, reg = compare("baseline", "round2_abbrev")
print("baseline->round2 improved", len(imp), "regressed", len(reg))
print("regress transitions", Counter((r[1], r[2]) for r in reg))
print("improve transitions", Counter((r[1], r[2]) for r in imp))

print("--- key queries ---")
for q in [
    "CA1",
    "CA2",
    "CA3",
    "ARC",
    "VP",
    "DMS",
    "PPN",
    "DCN interpositus",
    "EC III",
    "lateral NAcc",
    "III",
    "contra-DMS",
    "deep dorsal horn (laminae III-IV)",
]:
    for tag in ["baseline", "round1_abbrev", "round2_abbrev"]:
        rows, _ = load(tag)
        r = next(
            (x for x in rows if x["query"] == q and x["query_kind"] == "abbrev"),
            None,
        )
        if r:
            print(
                f"{tag:16} {q:34} {lab(r):25} {r.get('top_name', '')[:50]}"
            )

print("--- round2 regress vs baseline (abbrev, first 35) ---")
for r in sorted([x for x in reg if x[0] == "abbrev"], key=lambda x: (x[1], x[2]))[
    :35
]:
    print(f"{r[1]:25} -> {r[2]:25} | {r[3]!r}")
    print(f"  was={r[4][:55]!r}")
    print(f"  now={r[5][:55]!r}")
