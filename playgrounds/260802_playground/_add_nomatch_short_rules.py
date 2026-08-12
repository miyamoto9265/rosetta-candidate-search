#!/usr/bin/env python3
"""Add selective short-abbrev rules for round4 no_match cases (round5).

Prefer corpus-backed fullnames; include abbrev-only only when literature
usage is clear AND expansion resolves in HOMBA (directly or via alias).
Skip cell-type-only / paper-private parcels (CINs, PoSp, marker-fused…).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "rcs" / "homba_abbrev_rules.csv"
ALIASES = REPO / "rcs" / "homba_alias_rules.csv"

# (abbrev, expansion, notes)
RULES_ADD = [
    # --- high-n, corpus fullname ---
    ("Thal", "thalamus", "corpus/lit: Thal = thalamus"),
    ("tha", "thalamus", "corpus/lit: tha = thalamus"),
    ("THL", "thalamus", "corpus/lit: THL = thalamus"),
    ("rThal", "thalamus", "lit: rThal informal → thalamus parent"),
    ("MThal", "thalamus", "lit/corpus: medial thalamus → thalamus"),
    ("PreS", "presubiculum", "lit: PreS/PrS = presubiculum"),
    ("PeRh", "perirhinal cortex", "lit: PeRh/PRh = perirhinal cortex"),
    ("PeRhC", "perirhinal cortex", "corpus: caudal perirhinal → perirhinal"),
    ("iPER", "perirhinal cortex", "corpus: ipsilateral perirhinal"),
    ("vHipp", "ventral hippocampus", "lit: vHipp = ventral hippocampus"),
    ("vHIP", "ventral hippocampus", "lit: vHIP = ventral hippocampus"),
    ("vHC", "ventral hippocampus", "lit: vHC = ventral hippocampus"),
    ("vHP", "ventral hippocampus", "lit: vHP = ventral hippocampus"),
    ("VH", "ventral hippocampus", "lit/corpus: VH = ventral hippocampus"),
    ("dcHPC", "dorsal hippocampus", "lit: dcHPC = dorsal(-caudal) hippocampus"),
    ("dHIP", "dorsal hippocampus", "lit/corpus: dHIP = dorsal hippocampus"),
    ("dHipp", "dorsal hippocampus", "lit: dHipp = dorsal hippocampus"),
    ("HP", "hippocampus", "lit/corpus: HP = hippocampus"),
    ("HC", "hippocampus", "lit/corpus: HC = hippocampus"),
    ("PH", "posterior hypothalamic nucleus", "lit/corpus: PH = posterior hypothalamus"),
    ("PHb", "posterior hypothalamic nucleus", "corpus: posterior hypothalamus"),
    ("PHA", "posterior hypothalamic nucleus", "corpus: posterior hypothalamic area"),
    ("SOA", "supraoculomotor nucleus", "lit: SOA = supraoculomotor area/nucleus"),
    ("SNpc", "substantia nigra compact division", "lit/corpus: SNpc = SNc"),
    ("SNpr", "substantia nigra reticular division", "lit/corpus: SNpr = SNr"),
    ("PaF", "parafascicular nucleus of thalamus", "lit/corpus: PaF/Pf"),
    ("PfN", "parafascicular nucleus of thalamus", "corpus: PfN"),
    ("ARN", "arcuate nucleus of hypothalamus", "lit/corpus: ARN = arcuate (hypothalamic)"),
    ("DM", "dorsomedial hypothalamic nucleus", "lit/corpus: DM = dorsomedial hypothalamus"),
    ("VMN", "ventromedial hypothalamic nucleus", "lit/corpus: VMN = VMH"),
    ("VLPO", "lateral preoptic area", "lit: VLPO; HOMBA lacks VLPO node → LPA parent"),
    ("GRN", "gracile nucleus", "lit/corpus: GRN"),
    ("APN", "anterior pretectal nucleus", "lit/corpus: APN"),
    ("EPN", "entopeduncular nucleus", "lit/corpus: EPN"),
    ("Tu", "olfactory tubercle", "lit/corpus: Tu"),
    ("TUB", "olfactory tubercle", "lit/corpus: TUB"),
    ("vLGN", "pregeniculate nucleus", "lit/corpus: vLGN = ventral LGN / pregeniculate"),
    ("VNLL", "ventral nucleus of lateral lemniscus", "lit/corpus: VNLL"),
    ("LEnt", "lateral (rostral) entorhinal cortex", "lit/corpus: LEnt/LEC"),
    ("MEnt", "medial (caudal) entorhinal cortex", "lit: MEnt/MEC"),
    ("ECx", "entorhinal cortex", "lit: ECx"),
    ("AcbSh", "shell of nucleus accumbens", "lit/corpus: AcbSh"),
    ("NAcb", "nucleus accumbens", "lit: NAcb"),
    ("NAcbS", "shell of nucleus accumbens", "lit: NAcbS"),
    ("NAshell", "shell of nucleus accumbens", "lit: NAshell"),
    ("APir", "piriform cortex", "lit/corpus: APir = anterior piriform → piriform"),
    ("PirC", "piriform cortex", "lit: PirC"),
    ("MPO", "medial preoptic nucleus", "lit/corpus: MPO"),
    ("AMG", "amygdaloid complex", "lit/corpus: AMG"),
    ("Amyg", "amygdaloid complex", "lit: Amyg"),
    ("HYTH", "hypothalamus", "lit/corpus: HYTH"),
    ("Hypo", "hypothalamus", "lit: Hypo"),
    ("DH", "spinal dorsal horn", "lit/corpus: DH = dorsal horn"),
    ("ADn", "anterodorsal nucleus of thalamus", "lit: ADn/AD"),
    ("MDTN", "mediodorsal nucleus of thalamus", "lit/corpus: MDTN"),
    ("nIII", "oculomotor nucleus", "lit: nIII = CN III nucleus"),
    ("nVI", "abducens nucleus", "lit: nVI = CN VI nucleus"),
    ("PaSp", "parasubiculum", "lit/corpus: PaSp"),
    ("ParaS", "parasubiculum", "lit: ParaS"),
    ("PoSub", "caudal (dorsal) presubiculum (postsubiculum)", "lit/corpus: PoSub/postsubiculum"),
    ("pSUB", "caudal (dorsal) presubiculum (postsubiculum)", "lit/corpus: pSUB"),
    ("sSC", "superior colliculus", "lit/corpus: sSC"),
    ("CNIC", "central nucleus of inferior colliculus", "lit/corpus: CNIC"),
    ("mRt", "midbrain reticular formation", "lit/corpus: mRt"),
    ("PrV", "principal sensory nucleus of trigeminal nerve", "lit/corpus: PrV"),
    ("SMN", "supramammillary nucleus", "lit/corpus: SMN"),
    ("SUBv", "subiculum", "lit/corpus: SUBv = ventral subiculum → subiculum"),
    ("sVc", "spinal trigeminal nucleus caudalis", "lit/corpus: sVc"),
    ("Vmes", "mesencephalic trigeminal nucleus", "lit/corpus: Vmes"),
    ("DMNV", "dorsal motor nucleus of vagus", "lit/corpus: DMNV/DMX"),
    ("DVMN", "dorsal motor nucleus of vagus", "lit/corpus: DVMN"),
    ("DmnX", "dorsal motor nucleus of vagus", "lit: DmnX"),
    ("MBO", "mammillary body", "lit/corpus: MBO"),
    ("CdN", "caudate nucleus", "lit: CdN"),
    ("Cau", "caudate nucleus", "lit/corpus: Cau"),
    ("Cdt", "caudate nucleus", "lit: Cdt"),
    ("CBN", "cerebellar nuclei", "lit: CBN = cerebellar deep nuclei"),
    ("VStr", "ventral striatum", "lit: VStr"),
    ("VOLT", "organum vasculosum laminae terminalis", "lit: VOLT = OVLT"),
    ("ZIV", "zona incerta", "lit/corpus: ZIV = ventral ZI → ZI"),
    ("mHab", "medial habenular nucleus", "lit: mHab"),
    ("Vest", "vestibular nuclei", "lit: Vest"),
    ("AHC", "anterior hypothalamic nucleus", "lit/corpus: AHC"),
    ("DBN", "nucleus of diagonal band", "lit: DBN"),
    ("dDG", "dentate gyrus", "lit: dDG → DG"),
    ("dMEC", "medial (caudal) entorhinal cortex", "lit: dMEC"),
    ("MDRN", "medullary reticular formation in medulla oblongata", "lit: MDRN"),
    ("PARN", "parvicellular reticular nucleus", "lit: PARN"),
    ("PRNr", "pontine reticular formation", "lit: PRNr"),
    ("aBST", "bed nucleus of stria terminalis", "lit: aBST → BNST"),
    ("pBNST", "bed nucleus of stria terminalis", "lit: pBNST"),
    ("aBA", "basolateral nuclear group of amygdala", "lit: aBA → BLA"),
    ("pBA", "basolateral nuclear group of amygdala", "lit: pBA"),
    ("BLAa", "basolateral nuclear group of amygdala", "lit: BLAa"),
    ("BLAp", "basolateral nuclear group of amygdala", "lit: BLAp"),
    ("pdMeA", "medial nucleus of amygdala", "lit: pdMeA → MeA"),
    ("aMeA", "medial nucleus of amygdala", "lit: aMeA"),
    ("PFA", "perifornical nucleus", "lit/corpus: PFA"),
    ("PeFA", "perifornical nucleus", "lit: PeFA"),
    ("MCPO", "magnocellular preoptic nucleus", "lit/corpus: MCPO"),
    ("ILM", "intralaminar nuclear complex of thalamus", "lit/corpus: ILM"),
    ("rILN", "intralaminar nuclear complex of thalamus", "lit/corpus: rILN"),
    ("VNC", "vestibular nuclei", "lit/corpus: VNC = vestibular nuclear complex"),
    ("MLR", "gray matter of midbrain", "lit: MLR functional region → midbrain GM"),
    ("DVC", "solitary nucleus", "lit: DVC = dorsal vagal complex → Sol parent"),
    ("EWpg", "Edinger-Westphal nucleus (accessory oculomotor nucleus)", "lit/corpus: EWpg"),
    ("avTRN", "reticular nucleus of thalamus", "lit/corpus: avTRN → Rt"),
    ("LHy", "lateral hypothalamic area", "lit: LHy"),
    # --- abbrev-only / literature-confirmed ---
    ("PiCo", "intermediate reticular nucleus", "lit: PiCo = postinspiratory complex in IRt (Anderson 2016)"),
    ("mZI", "zona incerta", "lit: mZI = medial zona incerta → ZI"),
    ("IntA", "lateral interpositus (emboliform) nucleus", "lit: IntA = anterior interpositus / emboliform"),
    ("PPRF", "pontine reticular formation", "lit: PPRF = paramedian pontine reticular formation"),
    ("DAO", "inferior olive", "lit: DAO = dorsal accessory olive → IO"),
    ("dPul", "pulvinar of thalamus", "lit: dPul = dorsal pulvinar → Pul"),
    ("VLa", "ventral lateral nucleus of thalamus", "lit: VLa → VL"),
    ("rCau", "caudate nucleus", "lit: rCau = rostral caudate"),
    ("rGP", "globus pallidus", "lit: rGP → GP"),
    ("MidRF", "midbrain reticular formation", "lit: MidRF"),
    ("vmCAU", "caudate nucleus", "lit: vmCAU"),
    ("pdlPUT", "putamen", "lit: pdlPUT → putamen"),
    ("IVN", "inferior vestibular nucleus", "lit: IVN"),
    ("SupV", "superior vestibular nucleus", "lit: SupV"),
    ("CA3a", "CA3 region of hippocampus", "lit: CA3a → CA3"),
    ("A28", "entorhinal cortex", "lit: Brodmann A28 ≈ entorhinal"),
]

ALIAS_ADD = [
    ("posterior hypothalamus", "posterior hypothalamic nucleus", "PH corpus phrasing → PHN (avoid MCN)", "no"),
    ("supraoculomotor area", "supraoculomotor nucleus", "SOA literature synonym", "no"),
    ("ventrolateral preoptic nucleus", "lateral preoptic area", "VLPO → LPA parent (no VLPO node)", "no"),
    ("ventrolateral preoptic area", "lateral preoptic area", "VLPO area phrasing → LPA", "no"),
    ("postinspiratory complex", "intermediate reticular nucleus", "PiCo → IRt", "no"),
    ("paramedian pontine reticular formation", "pontine reticular formation", "PPRF", "no"),
    ("dorsal accessory olive", "inferior olive", "DAO → IO", "no"),
    ("medial zona incerta", "zona incerta", "mZI → ZI", "no"),
    ("anterior interpositus nucleus", "lateral interpositus (emboliform) nucleus", "IntA", "no"),
    ("emboliform nucleus", "lateral interpositus (emboliform) nucleus", "IntA synonym", "no"),
    ("mesencephalic locomotor region", "gray matter of midbrain", "MLR → midbrain GM", "no"),
    ("dorsal vagal complex", "solitary nucleus", "DVC → Sol", "no"),
    ("vascular organ of the lamina terminalis", "organum vasculosum laminae terminalis", "VOLT naming", "no"),
    ("vestibular nuclear complex", "vestibular nuclei", "VNC phrasing", "no"),
    ("parafascicular nucleus", "parafascicular nucleus of thalamus", "bare PaF fullname", "no"),
    ("dorsomedial hypothalamus", "dorsomedial hypothalamic nucleus", "DM corpus (reinforce)", "no"),
    ("anterior dorsal thalamus", "anterodorsal nucleus of thalamus", "ADn corpus phrasing", "no"),
    ("spinal dorsal horn", "dorsal column (horn) of spinal cord", "DH/SDH parent horn", "no"),
    ("dorsal horn", "dorsal column (horn) of spinal cord", "bare dorsal horn", "no"),
    ("lateral entorhinal cortex", "lateral (rostral) entorhinal cortex", "LEnt phrasing", "no"),
    ("medial entorhinal cortex", "medial (caudal) entorhinal cortex", "MEnt phrasing", "no"),
    ("cerebellar nuclei", "cerebellar deep nuclei", "CBN phrasing", "no"),
    ("principal sensory trigeminal nucleus", "principal sensory nucleus of trigeminal nerve", "PrV phrasing", "no"),
]


def main() -> int:
    existing = set()
    rows = list(csv.DictReader(RULES.open(encoding="utf-8-sig", newline="")))
    for r in rows:
        existing.add(r["abbrev"].strip().lower())

    added = []
    for ab, exp, notes in RULES_ADD:
        key = ab.lower()
        if key in existing:
            print("skip exists", ab)
            continue
        rows.append({"abbrev": ab, "expansion": exp, "notes": f"round5_nomatch: {notes}"})
        existing.add(key)
        added.append((ab, exp))

    with RULES.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["abbrev", "expansion", "notes"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"added {len(added)} abbrev rules")

    alias_rows = list(csv.DictReader(ALIASES.open(encoding="utf-8-sig", newline="")))
    alias_keys = {(r["input_text"].strip().lower(), r["homba_text"].strip().lower()) for r in alias_rows}
    new_aliases = 0
    for a, b, n, bi in ALIAS_ADD:
        key = (a.lower(), b.lower())
        if key in alias_keys:
            print("skip alias", a)
            continue
        # also skip if same input already mapped (avoid conflicting duplicates)
        if any(r["input_text"].strip().lower() == a.lower() for r in alias_rows):
            print("skip alias input exists", a)
            continue
        alias_rows.append(
            {"input_text": a, "homba_text": b, "notes": f"round5_nomatch: {n}", "bidirectional": bi}
        )
        alias_keys.add(key)
        new_aliases += 1

    with ALIASES.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["input_text", "homba_text", "notes", "bidirectional"],
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(alias_rows)
    print(f"added {new_aliases} aliases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
