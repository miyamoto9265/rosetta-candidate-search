#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION

QUERIES = [
    "Lateral olfactory tract",
    "Mesencephalic Trigeminal Nerve",
    "Fourth Nerve",
    "A1 catecholaminergic cell group",
    "A11 dopamine cell group",
    "Precuneiform Nucleus",
    "Retroreuniens thalamic nucleus",
    "Juxtaparaventricular nucleus",
    "Pedunculopontine Nucleus",
    "Supra Geniculate",
    "Ventralis intermedius",
    "Temporal horn of the lateral ventricle",
    "4th ventricle",
    "Laterodorsal tegmentum",
    "Centre median parafascicular complex",
    "Paraventricular hypothalamic nucleus",
    "Acoustic striae",
    "Anterior Interposed Cerebellar Nucleus",
    "Lateral Cerebellar Nucleus",
    "Nucleus of the stria medullaris",
    "Cochlea",
    "Spiral ganglion",
    "Visual area V3A",
    "Anterior nucleus (thalamus)",
    "Accessory trigeminal nucleus",
]


def main() -> None:
    g = RosettaCandidateGenerator(REPO / "rcs" / "HOMBA_v1_fixed.csv")
    print(f"engine v{ENGINE_VERSION}\n")
    for q in QUERIES:
        cands = g.generate(q, top_k=3)
        print(q)
        for c in cands:
            print(f"   {c['score']:.3f}  {c['name']}")
        if not cands:
            print("   (no candidates)")
        print()


if __name__ == "__main__":
    main()
