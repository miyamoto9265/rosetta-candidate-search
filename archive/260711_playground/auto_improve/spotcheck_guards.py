#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION

QUERIES = [
    "Substantia nigra (lateral part)",
    "Cingulate area 23c",
    "Insular cortex",
    "Frontoinsular area",
    "Orbital cortex (ventral)",
    "Abducens nucleus",
    "Primary motor cortex",
    "Lateral olfactory tract",
    "Pedunculopontine Nucleus",
    "Visual area V3A",
    "4th ventricle",
]


def main() -> None:
    g = RosettaCandidateGenerator(REPO / "rcs" / "HOMBA_v1_fixed.csv")
    print(f"engine v{ENGINE_VERSION}\n")
    for q in QUERIES:
        cands = g.generate(q, top_k=2)
        print(q)
        for c in cands:
            print(f"   {c['score']:.3f}  {c['name']}")
        print()


if __name__ == "__main__":
    main()
