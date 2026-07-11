#!/usr/bin/env python3
"""Reorganise the review datasets into a consistent 2x2 of four CSVs.

Axes
----
source : highconf   - rows the review_flag already called high_confidence
         unresolved - rows that did NOT reach high_confidence (round3)
verdict: correct    - genuinely / effectively correct on inspection
         incorrect  - not (plainly) correct -> needs human attention

Mapping
-------
highconf_correct.csv     <- resolved_high_confidence.csv where llm_check == 'correct'
highconf_incorrect.csv   <- resolved_high_confidence.csv where llm_check != 'correct'
                            (correct_parent / questionable / wrong)
unresolved_correct.csv   <- classified_A_effectively_correct.csv (rename)
unresolved_incorrect.csv <- classified_non_A.csv (rename)

Old files are removed after the new ones are written.
"""
from __future__ import annotations

import csv
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "csv_analysis"


def read(p: Path) -> tuple[list[str], list[dict]]:
    rows = list(csv.DictReader(p.open(encoding="utf-8")))
    cols = list(rows[0].keys()) if rows else []
    return cols, rows


def write(p: Path, cols: list[str], rows: list[dict]) -> None:
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"  {p.name:32s} {len(rows):4d} rows")


def main() -> None:
    hc = DIR / "resolved_high_confidence.csv"
    cols, rows = read(hc)
    correct = [r for r in rows if r["llm_check"] == "correct"]
    incorrect = [r for r in rows if r["llm_check"] != "correct"]

    print("written:")
    write(DIR / "highconf_correct.csv", cols, correct)
    write(DIR / "highconf_incorrect.csv", cols, incorrect)

    # rename the two classified files
    renames = [
        ("classified_A_effectively_correct.csv", "unresolved_correct.csv"),
        ("classified_non_A.csv", "unresolved_incorrect.csv"),
    ]
    for old, new in renames:
        src = DIR / old
        dst = DIR / new
        c, r = read(src)
        write(dst, c, r)

    # cleanup old files
    for name in ["resolved_high_confidence.csv",
                 "classified_A_effectively_correct.csv",
                 "classified_non_A.csv"]:
        f = DIR / name
        if f.exists():
            f.unlink()
            print(f"  removed {name}")

    total = len(correct) + len(incorrect)
    print(f"\nhighconf split: correct {len(correct)} + incorrect {len(incorrect)} = {total}")


if __name__ == "__main__":
    main()
