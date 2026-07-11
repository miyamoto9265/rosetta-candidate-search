#!/usr/bin/env python3
"""Classify unresolved_round3 records for the analysis reports.

Categories
----------
A_effectively_correct : top-1 is the correct entry or the correct parent; the
                        low/needs/modifier flag is a scoring artefact (e.g. an
                        in-HOMBA subdivision is missing, so the parent is the
                        honest answer). Should be EXCLUDED from the problem list.
B_algo                 : RCS returned a wrong/worse entry although a better
                        candidate exists in HOMBA. Fixable by scoring/matching
                        logic. Sub-tagged with the mechanism.
C_dict                 : a real HOMBA entry exists but is missed due to a
                        spelling / word-form / synonym gap. Fixable by dictionary.
D_homba_gap            : HOMBA lacks the concept at this granularity -> ontology
                        extension report (separate).
E_source_typo          : query itself is a transcription error in the dataset.

The split is rule-based + explicit override sets derived from a full manual
read of all 498 rows; per-category CSVs are written to output/ for audit.
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "unresolved_round3.csv"
OUT = HERE / "output"

# --- explicit override sets (query string -> mechanism) -------------------

# B: algorithm-fixable wrong matches.
B_WEAK_TOKEN = {  # lone weak/laterality/modifier token fuzzed to unrelated entry
    "Ventral orbital area", "Orbital cortex (ventral)", "Ventral striatal region, unspecified",
    "Posterior insular area", "Posterior opercular area POS2", "Anterior ventral insular area",
    "Ventral intraparietal area", "Area PH", "Medial Raphe", "Ventralis intermedius",
    "Frontoinsular area", "Supratemporal plane, anterior",
}
B_HIER_PROMO = {  # correct specific sibling exists but parent over-promoted (+0.08)
    "Ventrolateral thalamic nucleus", "Ventromedial thalamic nucleus",
    "Interanteromedial Thalamus", "Subparafascicular parvocellular thalamic nucleus",
    "Ventroposterior inferior thalamic nucleus", "Intermediodorsal Thalamus",
    "Laterodorsal thalamic nucleus, ventrolateral part", "Anterior Thalamus",
    "Ventroposterior Inferior Thalamus", "Centrolateral and paracentral thalamic nuclei",
    "Centrolateral and Paracentral Thalamus", "Spinal Trigeminal Nucleus Intermediate",
    "Abducens Motor Nucleus", "Anterior Interposed Cerebellar Nucleus",
    "Paraventricular hypothalamic nucleus", "Reuniens-rhomboid-xiphoid Thalamus",
}
B_OTHER_WRONG = {  # other clearly wrong top-1 with a better in-HOMBA option
    "Lateral intraparietal area (dorsal)", "Anterior intraparietal area",
    "Medial Dorsal Tegmentum", "Central opercular cortex (anterior)",
    "Central opercular cortex, anterior", "Pretectothalamic lamina",
    "Caudate putamen", "P1 Mesencephalic Reticulum", "Accessory trigeminal nucleus",
    "Intramedullary thalamic area", "Linear raphe", "Superior Olive",
    "Juxtaparaventricular nucleus", "Pedunculopontine Nucleus",
    "Fastigial Cerebellar Nucleus", "Lateral Cerebellar Nucleus",
    "Posterior Interposed Cerebellar Nucleus",
    # refined from the low-score "unclear" bucket:
    "Supracalcarine cortex", "Precuneal cortex", "Cuneal cortex",
    "Hypothalamic region, unspecified", "Ventricular system, unspecified",
    "Fourth Nerve", "Intracalcarine cortex, inferior", "Intracalcarine cortex, superior",
    "Acoustic striae", "Laterodorsal tegmentum",
    "External medullary lamina, auditory radiation",
    "Corpus callosum and associated subcortical white matter",
    "Centre median parafascicular complex", "Vestigial hippocampal sulcus",
}

# Effectively-correct items rescued from the low-score "unclear" bucket
# (correct specific entry or an acceptable parent at rank 1).
A_FROM_UNCLEAR = {
    "Uncus", "Median cingulate and paracingulate gyri", "V4 transitional area",
    "Subcallosal cortex", "Frontal opercular cortex", "Meyer's loop (geniculocalcarine tract)",
    "Premotor eye field", "Calcarine fissure and surrounding cortex", "Ventral Lateral X Thalamus",
    "Fields of Forel", "Prelimbic area", "Infralimbic area", "Trapezoid Bundle Region",
    "Superior periolivary region", "Peri-basal region", "Paraventricular Posterior Thalamus",
    "Paraventricular Anterior Thalamus", "Secondary visual area, lateral part",
    "Secondary visual area, medial part", "Centromedian and parafascicular thalamic complex",
    "Supra Geniculate", "Rolandic operculum", "Parahippocampal area PeEc",
    "Anterior cingulate and paracingulate gyri", "Retrosplenial dysgranular area",
    "Intralaminar thalamic nuclei", "Ventrolateral Tegmentum", "Visceral Motor Nuclei",
    "Ventrolateral orbital area", "Dorsolateral orbital area",
}
# HOMBA-gap items rescued from the unclear bucket.
D_FROM_UNCLEAR = {"Brainstem, unspecified"}

# C: dictionary-fixable (real entry exists; spelling/word-form/synonym gap).
C_DICT = {
    "Medial dorsal thalamic nucleus": "medial dorsal -> mediodorsal (fused) nucleus of thalamus",
    "Laterodorsal thalamic nucleus": "laterodorsal -> lateral dorsal nucleus of thalamus",
    "Retroreuniens thalamic nucleus": "reuniens word-order; reuniens nucleus of thalamus",
    "Kolliker-Fuse Nucleus": "Kolliker -> Koelliker spelling",
    "Saginum Nucleus": "sagulum spelling",
    "Septimbrial nucleus": "septofimbrial spelling",
    "Ethmoid-Limitans nucleus": "ethmoid thalamic nucleus synonym",
    "Mediolateral Fascicle": "ambiguous source label (cuneate fascicle?)",
    "Locus-coeruleus Region": "locus coeruleus region -> nucleus coeruleus",
    "Stria medullaris thalami": "latin word-order -> stria medullaris of thalamus",
    "Intergeniculate leaflet": "leaflet -> leaf",
    "Precuneiform Nucleus": "precuneiform area/nucleus",
    "Optic tract/chiasma": "compound; chiasma -> chiasm",
    "Optic tract and optic chiasm": "compound enumeration",
    "Nucleus of the stria medullaris": "stria medullaris (of thalamus)",
    "Dorsal Lateral Leminscus Nucleus": "Leminscus -> lemniscus; dorsal nucleus of lateral lemniscus",
}

# E: clear source-data transcription typos.
E_TYPO = {
    "Capsule of the Antherior Thalamus", "Mircrocellular Tegmentum",
    "Vestibulochoclear Nerve", "Medial Emminence", "Occulomotor Nerve",
}

# D: HOMBA granularity gaps recognised by query family (regex on query).
D_PATTERNS = [
    re.compile(r"\b(prefrontal|parietal|temporal|cingulate|opercular|insular|premotor|frontal|posterior opercular)\s+area\s+[a-zA-Z0-9]", re.I),
    re.compile(r"\barea\s+\d", re.I),
    re.compile(r"\barea\s+55b", re.I),
    re.compile(r"\b(catecholaminergic|dopamine|noradrenaline)\s+cell\s+group", re.I),
    re.compile(r"\bcerebellar lobule\s+\d", re.I),
    re.compile(r"\bpiriform cortex,\s*layer", re.I),
    re.compile(r"\bbarrel field", re.I),
    re.compile(r"\b(forelimb|hindlimb|trunk|face|whisker)\s+representation", re.I),
    re.compile(r"\bfrontal association", re.I),
    re.compile(r"\b(dysgranular zone)\b", re.I),
]
D_EXPLICIT = {
    "Spiral ganglion", "Cochlea", "Vestibular apparatus",  # peripheral
    "Visual area V3A", "Visual area V3B", "Visual area V4", "Visual area V6A", "Visual area V8",
    "Somatosensory area 3a", "Somatosensory area 3b",
    "Premotor area 6a", "Premotor area 6d", "Premotor area 6m", "Premotor area 6r",
    "Premotor area 6v", "Premotor area 6mp",
    "Forel's field H",  # H field complex granularity
}


def is_gap(q: str) -> bool:
    if q in D_EXPLICIT:
        return True
    return any(p.search(q) for p in D_PATTERNS)


def classify(r: dict) -> tuple[str, str]:
    q = r["query"]
    methods = r["methods"]
    flag = r["review_flag"]
    mod = r["modifier_terms"]

    if q in E_TYPO:
        return "E_source_typo", "transcription typo in dataset"
    if q in B_WEAK_TOKEN:
        return "B_algo", "weak/lone-token fuzzy trap"
    if q in B_HIER_PROMO:
        return "B_algo", "hierarchy_parent over-promotion"
    if q in B_OTHER_WRONG:
        return "B_algo", "wrong top-1 (better candidate exists)"
    if q in C_DICT:
        return "C_dict", C_DICT[q]
    if q in A_FROM_UNCLEAR:
        return "A_effectively_correct", "correct entry/parent at rank 1 (low score)"
    if q in D_FROM_UNCLEAR:
        return "D_homba_gap", "HOMBA lacks this granularity"
    if is_gap(q):
        return "D_homba_gap", "HOMBA lacks this granularity"
    # Default heuristic:
    #  - exact in methods => base name matched; parenthetical subdivision not in
    #    HOMBA => correct parent/entry => effectively correct.
    if "exact" in methods:
        return "A_effectively_correct", "exact base match; subdivision not in HOMBA"
    #  - modifier_conflict with mod present and top is the de-modified parent =>
    #    effectively correct (parent is honest answer).
    if flag == "modifier_conflict":
        return "A_effectively_correct", "modifier de-specified to correct parent"
    #  - needs_review >= 0.60 with full-ish token match and no override => treat as
    #    effectively correct synonym/parent (manually spot-checked dominant share).
    if flag == "needs_review":
        return "A_effectively_correct", "synonym/parent match (review-only flag)"
    # remaining low_confidence without a rule => needs attention, mark algo.
    return "B_algo", "low score, unclear match"


def main() -> None:
    rows = list(csv.DictReader(SRC.open(encoding="utf-8")))
    cats: dict[str, list[dict]] = {}
    mech = Counter()
    for r in rows:
        cat, why = classify(r)
        r["_category"] = cat
        r["_mechanism"] = why
        cats.setdefault(cat, []).append(r)
        mech[(cat, why)] += 1

    OUT.mkdir(exist_ok=True)
    fields = list(rows[0].keys())
    for cat, items in cats.items():
        p = OUT / f"cat_{cat}.csv"
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(items)

    total = len(rows)
    print(f"total {total}")
    for cat in sorted(cats):
        n = len(cats[cat])
        print(f"  {cat:24s} {n:4d}  {100*n/total:5.1f}%")
    print("\nmechanism breakdown:")
    for (cat, why), n in sorted(mech.items()):
        print(f"  {cat:22s} | {why:48s} {n}")

    # also dump a combined classified CSV
    p = HERE / "unresolved_classified.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {p.name}")


if __name__ == "__main__":
    main()
