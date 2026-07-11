#!/usr/bin/env python3
"""Quick top-3 spot-check for specific queries against the current engine."""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION

QUERIES = [
    # regressed cases to fix (were broader_parent/aligned, became wrong)
    "Frontoinsular area", "Opercular area OP2-3", "Precuneal cortex",
    "Orbital cortex (ventral)",
    # regression guards (must stay correct)
    "Abducens nucleus", "Insular cortex", "Substantia nigra (lateral part)",
    "Orbital frontal cortex",
]


def main() -> None:
    g = RosettaCandidateGenerator(REPO / "rcs" / "HOMBA_v1_fixed.csv")
    print(f"engine v{ENGINE_VERSION}\n")
    for q in QUERIES:
        cands = g.generate(q, top_k=3)
        print(f"{q}")
        for c in cands:
            print(f"   {c['score']:.3f}  {c['name']}  [{c['methods']}]")
        if not cands:
            print("   (no candidates)")
        print()


if __name__ == "__main__":
    main()
