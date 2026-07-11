#!/usr/bin/env python3
"""Playground evaluation harness for RCS dictionary improvement (260621).

It runs the *production* RCS algorithm (rcs/rosetta_candidate_generator.py)
but lets us layer **playground-only dictionary additions** on top of the
production dictionaries without merging into rcs/.

Three dictionaries are layered (production + playground additions):
  - alias rules  : rcs/homba_alias_rules.csv  + playground_alias_rules.csv
  - abbrev rules : rcs/homba_abbrev_rules.csv  + playground_abbrev_rules.csv
  - token rules  : rcs/homba_token_rules.csv   + playground_token_rules.csv (optional)

Usage:
  # Evaluate the two datasets and print a flag-distribution summary
  python rcs_eval.py eval

  # Look up HOMBA candidates for a single query (for verifying a mapping)
  python rcs_eval.py search "ansa lenticularis"

  # Diff: show which queries changed flag/score vs a previous run baseline
  python rcs_eval.py eval --tag round1
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

PLAYGROUND_DIR = Path(__file__).resolve().parent
BUILD_TESTDATA = PLAYGROUND_DIR.parent
REPO_ROOT = BUILD_TESTDATA.parent
RCS_DIR = REPO_ROOT / "rcs"
OUTPUT_DIR = PLAYGROUND_DIR / "output"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.review import review_flag_for  # noqa: E402
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"

PROD_ALIAS = RCS_DIR / "homba_alias_rules.csv"
PROD_ABBREV = RCS_DIR / "homba_abbrev_rules.csv"
PROD_TOKEN = RCS_DIR / "homba_token_rules.csv"

PG_ALIAS = PLAYGROUND_DIR / "playground_alias_rules.csv"
PG_ABBREV = PLAYGROUND_DIR / "playground_abbrev_rules.csv"
PG_TOKEN = PLAYGROUND_DIR / "playground_token_rules.csv"

DATASETS = {
    "corpus": BUILD_TESTDATA / "rcs_corpus.csv",
    "species": BUILD_TESTDATA / "rcs_species.csv",
}


def _merge_csv(prod: Path, additions: Path, tmpdir: Path, name: str) -> Path:
    """Concatenate a production dictionary with playground additions.

    Rows from *additions* are appended after the production rows. The
    production file is never modified.
    """
    rows: list[list[str]] = []
    header: list[str] | None = None
    for path in (prod, additions):
        if not path or not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            file_header = next(reader, None)
            if file_header is None:
                continue
            if header is None:
                header = file_header
            for row in reader:
                if any((cell or "").strip() for cell in row):
                    rows.append(row)
    out = tmpdir / name
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header or [])
        writer.writerows(rows)
    return out


def build_generator(tmpdir: Path, *, use_playground: bool = True) -> RosettaCandidateGenerator:
    alias = _merge_csv(PROD_ALIAS, PG_ALIAS if use_playground else None, tmpdir, "alias.csv")
    abbrev = _merge_csv(PROD_ABBREV, PG_ABBREV if use_playground else None, tmpdir, "abbrev.csv")
    token = _merge_csv(PROD_TOKEN, PG_TOKEN if use_playground else None, tmpdir, "token.csv")
    return RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=token,
        alias_rules_csv=alias,
        abbrev_rules_csv=abbrev,
    )


def _iter_queries(dataset_path: Path):
    with dataset_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        field = reader.fieldnames[0]
        for row in reader:
            q = (row.get(field) or "").strip()
            if q:
                yield q, row


def evaluate(generator: RosettaCandidateGenerator, dataset_path: Path):
    """Return (rows, summary) for a dataset. One row per query (top-1)."""
    rows = []
    seen: set[str] = set()
    flag_counter: Counter[str] = Counter()
    for query, src in _iter_queries(dataset_path):
        if query in seen:
            continue
        seen.add(query)
        candidates = generator.generate(query, top_k=3)
        if candidates:
            top = candidates[0]
            flag = review_flag_for(top)
            rows.append({
                "query": query,
                "top_name": top["name"],
                "top_homba_id": top["homba_id"],
                "score": top["score"],
                "methods": top["methods"],
                "matched_alias": top["matched_alias"],
                "matched_query": top["matched_query"],
                "modifier_terms": top["modifier_terms"],
                "modifier_match_score": top["modifier_match_score"],
                "review_flag": flag,
                "rank2_name": candidates[1]["name"] if len(candidates) > 1 else "",
                "rank2_score": candidates[1]["score"] if len(candidates) > 1 else "",
            })
        else:
            flag = "no_candidate"
            rows.append({
                "query": query, "top_name": "", "top_homba_id": "", "score": 0.0,
                "methods": "", "matched_alias": "", "matched_query": "",
                "modifier_terms": "", "modifier_match_score": "", "review_flag": flag,
                "rank2_name": "", "rank2_score": "",
            })
        flag_counter[flag] += 1

    total = len(rows)
    summary = {
        "dataset": dataset_path.name,
        "unique_queries": total,
        "flags": dict(flag_counter),
        "flag_pct": {k: round(100 * v / total, 1) for k, v in flag_counter.items()},
    }
    return rows, summary


def cmd_eval(args):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = args.tag or datetime.now().strftime("%Y%m%d_%H%M%S")
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        gen = build_generator(tmpdir, use_playground=not args.baseline)
        print(f"Loaded {len(gen.terms)} HOMBA terms, {len(gen.alias_entries)} alias entries.")
        print(f"alias_rules={len(gen.alias_rules)}  abbrev_rules={len(gen.abbrev_rules)}")
        all_summaries = []
        for name in (args.datasets or list(DATASETS)):
            path = DATASETS[name]
            rows, summary = evaluate(gen, path)
            all_summaries.append(summary)
            out_csv = OUTPUT_DIR / f"{name}_{tag}.csv"
            with out_csv.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            print(f"\n=== {name} ({summary['unique_queries']} unique queries) -> {out_csv.name}")
            for flag in ("high_confidence", "needs_review", "modifier_conflict", "low_confidence", "no_candidate"):
                c = summary["flags"].get(flag, 0)
                p = summary["flag_pct"].get(flag, 0.0)
                print(f"  {flag:18s} {c:5d}  {p:5.1f}%")
        summ_path = OUTPUT_DIR / f"summary_{tag}.json"
        summ_path.write_text(json.dumps(all_summaries, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSummary written: {summ_path.name}")


def cmd_search(args):
    with tempfile.TemporaryDirectory() as td:
        gen = build_generator(Path(td), use_playground=not args.baseline)
        cands = gen.generate(args.query, top_k=args.top_k)
        print(f"Query: {args.query!r}")
        for i, c in enumerate(cands, 1):
            print(f"  {i:2d}. {c['score']:.3f}  {c['homba_id']:14s} {c['name']!r}  "
                  f"[{c['methods']}] alias={c['matched_alias']!r}")


def main():
    parser = argparse.ArgumentParser(description="RCS playground evaluation harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_eval = sub.add_parser("eval", help="Evaluate datasets")
    p_eval.add_argument("--tag", default=None, help="Output tag (default: timestamp)")
    p_eval.add_argument("--baseline", action="store_true", help="Ignore playground additions")
    p_eval.add_argument("--datasets", nargs="*", choices=list(DATASETS), default=None)
    p_eval.set_defaults(func=cmd_eval)

    p_search = sub.add_parser("search", help="Search HOMBA for a single query")
    p_search.add_argument("query")
    p_search.add_argument("--top-k", type=int, default=8)
    p_search.add_argument("--baseline", action="store_true")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
