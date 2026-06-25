#!/usr/bin/env python3
"""Analyze rcs_corpus_source RCS run and emit structured summary JSON-ish prints."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS_CSV = ROOT / "build_core_improve" / "output" / "rcs_corpus_source_run1.csv"
SOURCE_CSV = ROOT / "rcs_corpus.csv"
CORE_CSV = ROOT / "rcs_core.csv"
CHALLENGE_CSV = ROOT / "rcs_challenge.csv"
OUT_JSON = ROOT / "build_core_improve" / "output" / "rcs_corpus_source_analysis.json"


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def has_parenthetical(name: str) -> bool:
    return "(" in name


def classify_improvability(
    name: str,
    row: dict[str, str],
    meta: dict[str, str],
    core_row: dict[str, str] | None,
) -> str:
    """Return improvable | limited | homba_gap."""
    flag = row.get("rcs_review_flag", "")
    score = float(row.get("rcs_score") or 0)
    species = meta.get("species", "")

    gap_patterns = (
        r"\bexcluding\b",
        r"\(excluding ",
        r"whole brain",
        r"all regions",
        r"limbic system",
        r"brainstem\b",
    )
    if any(re.search(p, name, re.I) for p in gap_patterns):
        return "homba_gap"

    if species in ("Macaque", "Rat") and flag != "high_confidence":
        # Many NHP/rodent parcellation labels have no HOMBA counterpart
        if score < 0.75:
            return "limited"

    if core_row and core_row.get("expected_homba_id"):
        if core_row["expected_homba_id"] != row.get("rcs_candidate_homba_id", ""):
            return "improvable"

    if flag in ("needs_review", "low_confidence", "modifier_conflict"):
        return "improvable"

    if score == 0:
        return "homba_gap" if species != "Human" else "improvable"

    return "ok"


def main() -> None:
    results = load_csv(RESULTS_CSV)
    source = load_csv(SOURCE_CSV)
    core = {r["structure_name"]: r for r in load_csv(CORE_CSV)}
    challenge = {r["structure_name"] for r in load_csv(CHALLENGE_CSV)}

    meta_by_name: dict[str, dict[str, str]] = {}
    papers_by_name: dict[str, set[str]] = defaultdict(set)
    for row in source:
        name = row["structure_name"]
        if name not in meta_by_name:
            meta_by_name[name] = row
        papers_by_name[name].add(row["paper"])

    res_by_name: dict[str, dict[str, str]] = {}
    for row in results:
        name = row["structure_name"]
        if name not in res_by_name:
            res_by_name[name] = row

    unique_names = sorted(res_by_name.keys())

    row_flags = Counter(r.get("rcs_review_flag", "") for r in results)
    unique_flags = Counter(res_by_name[n].get("rcs_review_flag", "") for n in unique_names)

    overlap = [n for n in unique_names if n in core]
    core_match = [
        n for n in overlap
        if core[n]["expected_homba_id"] == res_by_name[n].get("rcs_candidate_homba_id", "")
    ]
    core_mismatch = [
        {
            "structure_name": n,
            "expected_homba_id": core[n]["expected_homba_id"],
            "got_homba_id": res_by_name[n].get("rcs_candidate_homba_id", ""),
            "score": res_by_name[n].get("rcs_score", ""),
            "candidate": res_by_name[n].get("rcs_candidate_name", ""),
            "species": meta_by_name[n]["species"],
        }
        for n in overlap
        if core[n]["expected_homba_id"] != res_by_name[n].get("rcs_candidate_homba_id", "")
    ]

    improvable: list[dict] = []
    limited: list[dict] = []
    homba_gap: list[dict] = []
    ok: list[str] = []

    for name in unique_names:
        row = res_by_name[name]
        meta = meta_by_name[name]
        bucket = classify_improvability(name, row, meta, core.get(name))
        entry = {
            "structure_name": name,
            "species": meta["species"],
            "category": meta["category"],
            "paper": sorted(papers_by_name[name]),
            "rcs_review_flag": row.get("rcs_review_flag", ""),
            "rcs_score": row.get("rcs_score", ""),
            "rcs_candidate_homba_id": row.get("rcs_candidate_homba_id", ""),
            "rcs_candidate_name": row.get("rcs_candidate_name", ""),
            "in_core": name in core,
            "in_challenge": name in challenge,
        }
        if bucket == "improvable":
            improvable.append(entry)
        elif bucket == "limited":
            limited.append(entry)
        elif bucket == "homba_gap":
            homba_gap.append(entry)
        else:
            ok.append(name)

    # pattern tags for improvable
    pattern_tags: Counter[str] = Counter()
    for e in improvable:
        n = e["structure_name"]
        if has_parenthetical(n):
            pattern_tags["parenthetical"] += 1
        if n in challenge:
            pattern_tags["known_challenge"] += 1
        if e["in_core"]:
            pattern_tags["core_regression"] += 1
        if e["rcs_review_flag"] == "needs_review":
            pattern_tags["needs_review"] += 1
        if e["rcs_review_flag"] == "low_confidence":
            pattern_tags["low_confidence"] += 1
        if e["rcs_review_flag"] == "modifier_conflict":
            pattern_tags["modifier_conflict"] += 1
        if e["species"] == "Human" and not e["in_core"]:
            pattern_tags["human_paper_specific"] += 1

    species_unique = {
        sp: dict(Counter(
            res_by_name[n].get("rcs_review_flag", "")
            for n in unique_names
            if meta_by_name[n]["species"] == sp
        ))
        for sp in ("Human", "Macaque", "Rat")
    }

    paper_stats = {}
    for row in source:
        p = row["paper"]
        n = row["structure_name"]
        paper_stats.setdefault(p, {"total": 0, "high": 0, "needs_review": 0, "low": 0})
        paper_stats[p]["total"] += 1
        flag = res_by_name[n].get("rcs_review_flag", "")
        if flag == "high_confidence":
            paper_stats[p]["high"] += 1
        elif flag == "needs_review":
            paper_stats[p]["needs_review"] += 1
        elif flag == "low_confidence":
            paper_stats[p]["low"] += 1

    summary = {
        "run_input": str(SOURCE_CSV),
        "run_output": str(RESULTS_CSV),
        "total_rows": len(results),
        "unique_names": len(unique_names),
        "row_review_flags": dict(row_flags),
        "unique_review_flags": dict(unique_flags),
        "high_conf_rate_rows": round(row_flags["high_confidence"] / len(results), 4),
        "high_conf_rate_unique": round(unique_flags["high_confidence"] / len(unique_names), 4),
        "core_overlap_unique": len(overlap),
        "core_exact_match": len(core_match),
        "core_mismatch_count": len(core_mismatch),
        "core_mismatches": core_mismatch,
        "improvable_count": len(improvable),
        "limited_count": len(limited),
        "homba_gap_count": len(homba_gap),
        "ok_count": len(ok),
        "improvable_pattern_tags": dict(pattern_tags),
        "species_unique_flags": species_unique,
        "paper_stats": paper_stats,
        "improvable": sorted(improvable, key=lambda x: (x["rcs_review_flag"], -float(x["rcs_score"] or 0))),
        "limited": sorted(limited, key=lambda x: -float(x["rcs_score"] or 0)),
        "homba_gap": homba_gap,
        "challenge_in_corpus": sorted(challenge & set(unique_names)),
    }

    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in summary if k not in ("improvable", "limited", "homba_gap")}, ensure_ascii=False, indent=2))
    print(f"\nWrote full analysis to {OUT_JSON}")


if __name__ == "__main__":
    main()
