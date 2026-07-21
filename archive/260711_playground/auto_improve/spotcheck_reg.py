#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

g = RosettaCandidateGenerator(Path("rcs/HOMBA_v1_fixed.csv"))
for q in [
    "Opercular area OP2-3",
    "Frontal association area 3",
    "Lateral lemniscus, dorsal nucleus",
    "Lateral olfactory tract",
    "Pedunculopontine Nucleus",
    "Visual area V3A",
    "Anterior commissure, posterior limb",
]:
    print(q)
    for c in g.generate(q, top_k=2):
        print(f"  {c['score']:.3f}  {c['name']}")
    print()
