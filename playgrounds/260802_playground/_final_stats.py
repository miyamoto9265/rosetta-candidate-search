#!/usr/bin/env python3
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load(tag):
    rows = list(
        csv.DictReader(
            (HERE / "runs" / tag / "validation_results.csv").open(encoding="utf-8-sig")
        )
    )
    s = json.loads((HERE / "runs" / tag / "summary.json").read_text(encoding="utf-8"))
    return rows, s


def lab(r):
    return "no_match" if not r.get("top_homba_id") else (r.get("final_label") or "uncertain")


RANK = {
    "aligned": 0,
    "broader_parent": 1,
    "partial_or_narrower": 2,
    "wrong": 3,
    "ambiguous": 4,
    "source_or_ontology_issue": 5,
    "no_consensus": 5,
    "no_match": 6,
}


def compare(a_tag, b_tag):
    a, _ = load(a_tag)
    b, _ = load(b_tag)
    am = {(r["query_kind"], r["query"]): r for r in a}
    bm = {(r["query_kind"], r["query"]): r for r in b}
    imp, reg = [], []
    for k, br in bm.items():
        ar = am.get(k)
        if not ar:
            continue
        al, bl = lab(ar), lab(br)
        if al == bl:
            continue
        row = (k[0], al, bl, k[1], ar.get("top_name", ""), br.get("top_name", ""))
        if RANK.get(bl, 9) < RANK.get(al, 9):
            imp.append(row)
        elif RANK.get(bl, 9) > RANK.get(al, 9):
            reg.append(row)
    return imp, reg


for tag in ["baseline", "round1_abbrev", "round2_abbrev", "round3_abbrev"]:
    _, s = load(tag)
    o = s["overall"]["label_counts"]
    ab = s["datasets"]["non_neocortex_abbrev"]["label_counts"]
    print(
        f"{tag:16} nm={s.get('no_match_n'):4} al={o.get('aligned'):4} "
        f"br={o.get('broader_parent'):4} wr={o.get('wrong'):4} soi={o.get('source_or_ontology_issue'):4}"
    )
    print(
        f"{'':16} abbrev al={ab.get('aligned'):4} wr={ab.get('wrong'):4} "
        f"br={ab.get('broader_parent'):4} soi={ab.get('source_or_ontology_issue'):4}"
    )

imp, reg = compare("baseline", "round3_abbrev")
print(f"baseline->round3 improved={len(imp)} regressed={len(reg)}")
print("regress", Counter((r[1], r[2]) for r in reg))
print("--- key ---")
rows3, _ = load("round3_abbrev")
rows0, _ = load("baseline")
for q in [
    "CA1", "ARC", "VP", "DMS", "PPN", "DCN interpositus", "EC III",
    "lateral NAcc", "dorsolateral PAG", "NAc shell", "III", "contra-DMS",
]:
    r0 = next(x for x in rows0 if x["query"] == q and x["query_kind"] == "abbrev")
    r3 = next(x for x in rows3 if x["query"] == q and x["query_kind"] == "abbrev")
    print(
        f"{q:34} {lab(r0):20} -> {lab(r3):20} | {r3.get('top_name', '')[:55]}"
    )
print("--- regress abbrev ---")
for r in sorted([x for x in reg if x[0] == "abbrev"], key=lambda x: (x[1], x[2])):
    print(f"{r[1]:25} -> {r[2]:25} | {r[3]!r}")
    print(f"  now={r[5][:60]!r}")
