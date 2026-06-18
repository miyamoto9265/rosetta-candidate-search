"""Analyze a test results CSV and classify queries by outcome.

Usage: python cursor_analyze_results.py <results_csv> [score_threshold_high] [score_threshold_low]
"""
import csv
import sys

from cursor_rcs_paths import TEST_OUTPUT_DIR

_DEFAULT_RESULTS = TEST_OUTPUT_DIR / "round4_large_scale_20260517_175326.csv"
results_path = sys.argv[1] if len(sys.argv) > 1 else str(_DEFAULT_RESULTS)
HIGH = float(sys.argv[2]) if len(sys.argv) > 2 else 0.9
LOW  = float(sys.argv[3]) if len(sys.argv) > 3 else 0.6

rows: dict[str, list[dict]] = {}  # query -> list of rank rows
with open(results_path, newline="", encoding="utf-8-sig") as f:
    for row in csv.DictReader(f):
        q = row["structure_name"]
        rows.setdefault(q, []).append(row)

high_conf    = []   # top score >= HIGH
needs_review = []   # LOW <= top score < HIGH
low_conf     = []   # top score < LOW
no_result    = []   # no rows at all

for query, recs in rows.items():
    recs_sorted = sorted(recs, key=lambda r: -float(r.get("rcs_score", 0)))
    top = recs_sorted[0]
    score = float(top.get("rcs_score", 0))
    name  = top.get("rcs_candidate_name", "?")
    methods = top.get("rcs_methods", "")
    if score == 0.0:
        no_result.append(query)
    elif score >= HIGH:
        high_conf.append((query, score, name, methods))
    elif score >= LOW:
        needs_review.append((query, score, name, methods))
    else:
        low_conf.append((query, score, name, methods))

print(f"=== Results Summary for: {results_path} ===")
print(f"Total queries: {len(rows)}")
print(f"  high_confidence  (>= {HIGH}): {len(high_conf)}")
print(f"  needs_review ({LOW}–{HIGH}):  {len(needs_review)}")
print(f"  low_confidence   (<  {LOW}): {len(low_conf)}")
print(f"  no_result:                   {len(no_result)}")

print(f"\n{'='*70}")
print(f"HIGH CONFIDENCE ({len(high_conf)} queries)")
print(f"{'='*70}")
for q, s, n, m in sorted(high_conf, key=lambda x: -x[1]):
    print(f"  {s:.4f}  {q:<45}  {n[:45]}")

print(f"\n{'='*70}")
print(f"NEEDS REVIEW ({len(needs_review)} queries)")
print(f"{'='*70}")
for q, s, n, m in sorted(needs_review, key=lambda x: x[1]):
    print(f"  {s:.4f}  {q:<45}  {n[:45]}")

print(f"\n{'='*70}")
print(f"LOW CONFIDENCE ({len(low_conf)} queries)")
print(f"{'='*70}")
for q, s, n, m in sorted(low_conf, key=lambda x: x[1]):
    print(f"  {s:.4f}  {q:<45}  {n[:45]}")

print(f"\n{'='*70}")
print(f"NO RESULT ({len(no_result)} queries)")
print(f"{'='*70}")
for q in no_result:
    print(f"  {q}")
