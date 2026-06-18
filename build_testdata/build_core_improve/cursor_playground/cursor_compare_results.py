#!/usr/bin/env python3
"""Compare two RCS result CSV files to see which queries changed and how."""
import csv
import sys
from pathlib import Path


def load_results(csv_path: Path) -> dict[str, dict]:
    """Load top-rank-1 results keyed by structure_name."""
    results = {}
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if str(row.get("rcs_rank", "")) == "1":
                key = row.get("structure_name", "")
                results[key] = row
    return results


def main():
    if len(sys.argv) < 3:
        print("Usage: python compare_results.py old_result.csv new_result.csv")
        sys.exit(1)

    old_path = Path(sys.argv[1])
    new_path = Path(sys.argv[2])

    old = load_results(old_path)
    new = load_results(new_path)

    all_queries = sorted(set(old) | set(new))

    improved = []
    worsened = []
    unchanged = []
    new_matches = []
    lost_matches = []

    for query in all_queries:
        old_r = old.get(query)
        new_r = new.get(query)

        if old_r is None and new_r is not None:
            new_matches.append((query, new_r))
            continue
        if new_r is None and old_r is not None:
            lost_matches.append((query, old_r))
            continue

        old_name = old_r.get("rcs_candidate_name", "")
        new_name = new_r.get("rcs_candidate_name", "")
        old_score = float(old_r.get("rcs_score", 0))
        new_score = float(new_r.get("rcs_score", 0))
        old_flag = old_r.get("rcs_review_flag", "")
        new_flag = new_r.get("rcs_review_flag", "")

        if old_name == new_name and abs(old_score - new_score) < 0.001:
            unchanged.append(query)
        elif new_score > old_score or (new_score == old_score and old_flag != new_flag):
            improved.append((query, old_score, old_name, old_flag, new_score, new_name, new_flag))
        else:
            worsened.append((query, old_score, old_name, old_flag, new_score, new_name, new_flag))

    print(f"=== Comparison: {old_path.name} → {new_path.name} ===\n")

    if new_matches:
        print(f"NEW MATCHES ({len(new_matches)}):")
        for q, r in new_matches:
            print(f"  {q:40s} → {r['rcs_candidate_name']} ({r['rcs_score']}, {r['rcs_review_flag']})")
        print()

    if lost_matches:
        print(f"LOST MATCHES ({len(lost_matches)}):")
        for q, r in lost_matches:
            print(f"  {q:40s} was: {r['rcs_candidate_name']} ({r['rcs_score']})")
        print()

    if improved:
        print(f"IMPROVED ({len(improved)}):")
        for q, os, on, of_, ns, nn, nf in improved:
            marker = "[+]" if nn != on else "[^]"
            print(f"  {marker} {q:40s}")
            if on != nn:
                print(f"      OLD: {on:48s} score={os:.4f} [{of_}]")
                print(f"      NEW: {nn:48s} score={ns:.4f} [{nf}]")
            else:
                print(f"      {nn:48s} {os:.4f} → {ns:.4f} [{of_}→{nf}]")
        print()

    if worsened:
        print(f"WORSENED ({len(worsened)}):")
        for q, os, on, of_, ns, nn, nf in worsened:
            print(f"  [-] {q:40s}")
            print(f"      OLD: {on:48s} score={os:.4f} [{of_}]")
            print(f"      NEW: {nn:48s} score={ns:.4f} [{nf}]")
        print()

    print(f"UNCHANGED: {len(unchanged)} queries")
    print(f"\nSummary: +{len(new_matches)} new, -{len(lost_matches)} lost, {len(improved)} improved, {len(worsened)} worsened, {len(unchanged)} unchanged")


if __name__ == "__main__":
    main()
