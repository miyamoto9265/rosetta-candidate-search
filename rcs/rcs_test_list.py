#!/usr/bin/env python3
"""Run ROSETTA Candidate Search against a CSV file and write results.

Used during LLM-based Recursive Improvement and ongoing dataset evaluation.

Input CSVs: build_testdata/build_core_improve/input/  (Round test files)
Output:     build_testdata/build_core_improve/output/

Example usage (from repo root):
    python rcs/rcs_test_list.py build_testdata/build_core_improve/input/level1.csv
    python rcs/rcs_test_list.py build_testdata/build_core_improve/input/level1.csv --top-k 3
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

RCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = RCS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.review import review_flag_for
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

DEFAULT_HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
DEFAULT_ALIAS_RULES_CSV = RCS_DIR / "homba_alias_rules.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "build_testdata" / "build_core_improve" / "output"

RCS_RESULT_FIELDS = [
    "rcs_rank",
    "rcs_candidate_homba_id",
    "rcs_candidate_name",
    "rcs_candidate_acronym",
    "rcs_candidate_dhba_name",
    "rcs_candidate_dhba_acronym",
    "rcs_candidate_parent_id",
    "rcs_candidate_graph_order",
    "rcs_candidate_depth",
    "rcs_score",
    "rcs_methods",
    "rcs_matched_query",
    "rcs_matched_alias",
    "rcs_review_flag",
    "rcs_modifier_terms",
    "rcs_modifier_match_score",
    "rcs_hierarchy_reason",
    "rcs_dhba_filter",
]


def build_output_path(input_csv: Path, output_dir: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{input_csv.stem}_{timestamp}.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate HOMBA candidates for each row in a CSV (playground version)."
    )
    parser.add_argument(
        "input_csv",
        type=Path,
        metavar="INPUT_CSV",
        help="Input CSV file. The first column is the search query.",
    )
    parser.add_argument("--homba-csv", type=Path, default=DEFAULT_HOMBA_CSV)
    parser.add_argument("--alias-rules-csv", type=Path, default=DEFAULT_ALIAS_RULES_CSV)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument("--output-csv", type=Path, default=None)
    parser.add_argument("--top-k", type=int, default=3, help="Number of candidates per row (default: 3)")
    parser.add_argument("--per-method-k", type=int, default=40)
    parser.add_argument(
        "--dhba-filter",
        choices=("both", "with", "without"),
        default="both",
    )
    return parser.parse_args()


def resolve_output_csv(args: argparse.Namespace) -> Path:
    if args.output_csv is not None:
        return args.output_csv
    return build_output_path(args.input_csv, args.output_dir)


def rcs_fields_from_candidate(
    candidate: dict[str, object],
    rank: int,
    dhba_filter: str,
) -> dict[str, object]:
    return {
        "rcs_rank": rank,
        "rcs_candidate_homba_id": candidate.get("homba_id", ""),
        "rcs_candidate_name": candidate.get("name", ""),
        "rcs_candidate_acronym": candidate.get("acronym", ""),
        "rcs_candidate_dhba_name": candidate.get("dhba_name", ""),
        "rcs_candidate_dhba_acronym": candidate.get("dhba_acronym", ""),
        "rcs_candidate_parent_id": candidate.get("parent_id", ""),
        "rcs_candidate_graph_order": candidate.get("graph_order", ""),
        "rcs_candidate_depth": candidate.get("depth", ""),
        "rcs_score": candidate.get("score", ""),
        "rcs_methods": candidate.get("methods", ""),
        "rcs_matched_query": candidate.get("matched_query", ""),
        "rcs_matched_alias": candidate.get("matched_alias", ""),
        "rcs_review_flag": review_flag_for(candidate),
        "rcs_modifier_terms": candidate.get("modifier_terms", ""),
        "rcs_modifier_match_score": candidate.get("modifier_match_score", ""),
        "rcs_hierarchy_reason": candidate.get("hierarchy_reason", ""),
        "rcs_dhba_filter": dhba_filter,
    }


def rcs_fields_empty(dhba_filter: str) -> dict[str, object]:
    empty = {field: "" for field in RCS_RESULT_FIELDS}
    empty["rcs_rank"] = 0
    empty["rcs_dhba_filter"] = dhba_filter
    return empty


def main() -> None:
    args = parse_args()

    if not args.input_csv.exists():
        raise SystemExit(f"Input CSV not found: {args.input_csv}")

    output_csv = resolve_output_csv(args)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading HOMBA from: {args.homba_csv}")
    generator = RosettaCandidateGenerator(args.homba_csv, alias_rules_csv=args.alias_rules_csv)
    print(f"  {len(generator.terms)} terms, {len(generator.alias_entries)} alias entries loaded.")

    candidate_cache: dict[tuple[str, int, int, str], list[dict[str, object]]] = {}

    def cached_generate(query: str) -> list[dict[str, object]]:
        internal_k = max(args.top_k * 3, 10)
        cache_key = (query, internal_k, args.per_method_k, args.dhba_filter)
        if cache_key not in candidate_cache:
            candidate_cache[cache_key] = generator.generate(
                query,
                top_k=internal_k,
                per_method_k=args.per_method_k,
                dhba_filter=args.dhba_filter,
            )
        return candidate_cache[cache_key]

    output_rows: list[dict[str, object]] = []
    input_fieldnames: list[str] = []

    with args.input_csv.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise SystemExit(f"Input CSV has no header row: {args.input_csv}")

        input_fieldnames = list(reader.fieldnames)
        query_field = input_fieldnames[0]
        print(f"Query column: '{query_field}'")

        for row_number, row in enumerate(reader, start=1):
            query = (row.get(query_field) or "").strip()
            candidates = cached_generate(query)[: args.top_k]

            if not candidates:
                output_rows.append({**row, **rcs_fields_empty(args.dhba_filter)})
                continue

            for rank, candidate in enumerate(candidates, start=1):
                output_rows.append({
                    **row,
                    **rcs_fields_from_candidate(candidate, rank, args.dhba_filter),
                })

    output_fieldnames = input_fieldnames + RCS_RESULT_FIELDS

    with output_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=output_fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\nInput : {args.input_csv}")
    print(f"Filter: dhba_filter={args.dhba_filter}, top_k={args.top_k}")
    print(f"Output: {output_csv}")
    print(f"Wrote {len(output_rows)} rows ({len(output_rows) // max(args.top_k, 1)} queries).")


if __name__ == "__main__":
    main()
