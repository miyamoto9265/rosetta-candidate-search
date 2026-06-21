#!/usr/bin/env python3
"""Interactively test ROSETTA Candidate Search from the terminal.

Run from repo root:
    python rcs/rcs_test_interactive.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = RCS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.review import review_flag_for
from rcs.rosetta_candidate_generator import (
    DEFAULT_ALIAS_RULES_CSV,
    DEFAULT_TOKEN_RULES_CSV,
    RosettaCandidateGenerator)

DEFAULT_HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactively run ROSETTA Candidate Search (playground)")
    parser.add_argument("--homba-csv", type=Path, default=DEFAULT_HOMBA_CSV)
    parser.add_argument("--alias-rules-csv", type=Path, default=DEFAULT_ALIAS_RULES_CSV)
    parser.add_argument("--top-k", type=int, default=5, help="Number of candidates to show")
    parser.add_argument(
        "--per-method-k",
        type=int,
        default=40,
        help="Internal candidate count retained from fuzzy and BM25-style searches",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show extra debug fields (modifier_terms, hierarchy_reason, etc.)",
    )
    return parser.parse_args()


def print_candidates(candidates: list[dict[str, object]], verbose: bool = False) -> None:
    if not candidates:
        print("  [No candidates found.]")
        return

    header = f"  {'rank':<4} {'score':<8} {'homba_id':<14} {'name':<40} {'methods':<22} matched_alias"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for rank, candidate in enumerate(candidates, start=1):
        name = str(candidate.get("name", ""))
        if len(name) > 38:
            name = f"{name[:37]}..."
        print(
            f"  {rank:<4} "
            f"{float(candidate.get('score', 0.0)):<8.6f} "
            f"{str(candidate.get('homba_id', '')):<14} "
            f"{name:<40} "
            f"{str(candidate.get('methods', '')):<22} "
            f"{candidate.get('matched_alias', '')}"
        )
        if verbose:
            mq = candidate.get("matched_query", "")
            mt = candidate.get("modifier_terms", "")
            ms = candidate.get("modifier_match_score", "")
            hr = candidate.get("hierarchy_reason", "")
            dhba = candidate.get("dhba_name", "")
            if mq:
                print(f"       matched_query  : {mq}")
            if mt:
                print(f"       modifier_terms : {mt}  score={ms}")
            if hr:
                print(f"       hierarchy      : {hr}")
            if dhba:
                print(f"       dhba_name      : {dhba}")


def main() -> None:
    args = parse_args()

    print("=== ROSETTA Candidate Search — playground ===")
    print(f"  HOMBA CSV  : {args.homba_csv}")
    print(f"  alias CSV  : {args.alias_rules_csv}")
    print(f"  token CSV  : {DEFAULT_TOKEN_RULES_CSV}")
    print(f"  top_k      : {args.top_k}")
    print(f"  verbose    : {args.verbose}")
    print()

    generator = RosettaCandidateGenerator(args.homba_csv, alias_rules_csv=args.alias_rules_csv)
    print(f"  Loaded {len(generator.terms)} HOMBA terms, {len(generator.alias_entries)} alias entries.")
    print()
    print("Enter a structure name. Type 'quit', 'exit', or press Ctrl-D to stop.")

    while True:
        try:
            query = input("\nquery> ").strip()
        except EOFError:
            print()
            break

        if not query:
            continue
        if query.lower() in {"quit", "exit"}:
            break

        candidates = generator.generate(query, top_k=args.top_k, per_method_k=args.per_method_k)
        print_candidates(candidates, verbose=args.verbose)


if __name__ == "__main__":
    main()
