"""SABRA Ontology — canonical definition in code.

SABRA (Standardized Ontology of Anatomies for Brain Reference Architecture) is the
organisation's mixed brain atlas used for region names (e.g. CoBRAC circuit names).
It is *not* a new ontology with its own IDs; every SABRA region is a region of one
of two existing atlases:

* **BNA** (Brainnetome Atlas) for the **neocortex** only: the cortical labels 1-210
  except the two areas that are not neocortex in HOMBA (A28/34 = entorhinal cortex,
  TI = temporal agranular insular cortex).
* **DHBA** (Developing Human Brain Atlas) for everything else: subcortical nuclei
  (amygdala, basal ganglia, thalamus, ...), hippocampal formation and other
  allocortex / periallocortex, hypothalamus, brainstem, cerebellum, ... DHBA terms
  are the subset of HOMBA that carry a ``DHBA_name`` (``dhba_filter="with"`` in RCS).

The BNA subcortical labels 211-246 (Amyg, Hipp, BG, Tha) still exist in BNA and
RCS_EBL still returns them, but they are not SABRA regions: name those regions with
their DHBA term (``BNA_DHBA_COUNTERPARTS`` gives the DHBA term that contains each).
Until 2026-10-04 SABRA used BNA for those labels too (``PREVIOUS_BNA_TERRITORY_HOMBA_ROOTS``).

Tooling: RCS (HOMBA) resolves names to HOMBA -> DHBA; RCS_EBL resolves names to BNA.
Human-readable definition and workflow: ``docs/sabra.md``. Keep both in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

SABRA_NAME = "SABRA"
SABRA_FULL_NAME = "Standardized Ontology of Anatomies for Brain Reference Architecture"
# Date of the BNA/DHBA boundary in force (2026-10-04: BNA = neocortex only).
SABRA_BOUNDARY_VERSION = "2026-10-04"

ATLAS_BNA = "BNA"
ATLAS_DHBA = "DHBA"

BNA_LABEL_COUNT = 246
BNA_CORTICAL_LABEL_IDS = range(1, 211)
BNA_SUBCORTICAL_LABEL_IDS = range(211, 247)
# BNA L2 (gyrus-level) groups that make up the 36 subcortical labels (not SABRA regions).
BNA_SUBCORTICAL_L2 = {
    "Amyg": "amygdala",
    "Hipp": "hippocampus",
    "BG": "basal ganglia",
    "Tha": "thalamus",
}
# Cortical BNA areas (left label ID -> area) that HOMBA places outside the neocortex
# (under "non-neocortex"): SABRA names them with DHBA.
BNA_NON_NEOCORTICAL_CORTICAL_AREAS = {
    115: "A28/34 (entorhinal cortex; HOMBA periarchicortex)",
    117: "TI (temporal agranular insular cortex; HOMBA peripaleocortex)",
}

# Neocortical BNA L2 groups that also contain non-neocortical areas: not usable as a whole-gyrus SABRA unit.
BNA_MIXED_L2: dict[str, str] = {
    "PhG": "parahippocampal gyrus: neocortical A35/36r, A35/36c, TL, TH plus A28/34 (EC) and TI, which are DHBA",
}
# Neocortical subregions of each mixed L2 group (left label -> area).
BNA_MIXED_L2_NEOCORTICAL_AREAS: dict[str, dict[int, str]] = {
    "PhG": {109: "A35/36r", 111: "A35/36c", 113: "TL", 119: "TH"},
}
HIPPOCAMPUS_HINT = (
    "use HiF (HOMBA:12170) for the whole hippocampus; when the source names a field "
    "(CA1, CA3, DG, subiculum, ...) use that finer DHBA term instead"
)

# DHBA term that contains each non-neocortical BNA area (left label ID -> (HOMBA ID, DHBA acronym)).
# A container, not an equivalent: BNA's subcortical subregions are connectivity-defined, so pick the
# DHBA nucleus the literature describes (search_homba_candidates) and use these only as a fallback.
BNA_DHBA_COUNTERPARTS: dict[int, tuple[str, str]] = {
    115: ("HOMBA:10317", "EC"),  # A28/34 -> entorhinal cortex
    117: ("HOMBA:10330", "TI"),  # TI -> temporal agranular insular cortex
    211: ("HOMBA:10361", "AMY"),  # mAmyg -> amygdaloid complex
    213: ("HOMBA:10361", "AMY"),  # lAmyg -> amygdaloid complex
    215: ("HOMBA:12170", "HiF"),  # rHipp -> hippocampal formation
    217: ("HOMBA:12170", "HiF"),  # cHipp -> hippocampal formation
    219: ("HOMBA:10334", "Ca"),  # vCa -> caudate nucleus
    221: ("HOMBA:10342", "GP"),  # GP -> globus pallidus
    223: ("HOMBA:10339", "NAC"),  # NAC -> nucleus accumbens
    225: ("HOMBA:10338", "Pu"),  # vmPu -> putamen
    227: ("HOMBA:10334", "Ca"),  # dCa -> caudate nucleus
    229: ("HOMBA:10338", "Pu"),  # dlPu -> putamen
    **{left: ("HOMBA:10391", "DTH") for left in range(231, 246, 2)},  # 8 thalamic subregions -> dorsal thalamus
}

# HOMBA subtrees that SABRA represents with BNA instead of DHBA: the neocortex and the
# surface (gyri / sulci) structures, minus BNA_TERRITORY_EXCLUDED_HOMBA. Anything else is DHBA.
BNA_TERRITORY_HOMBA_ROOTS: dict[str, str] = {
    "HOMBA:10160": "neocortex (isocortex)",
    "HOMBA:12112": "cerebral gyri and lobules",
    "HOMBA:10610": "cerebral sulci",
}
# Gyri inside BNA_TERRITORY_HOMBA_ROOTS that are allocortex or septal, not neocortex.
BNA_TERRITORY_EXCLUDED_HOMBA: dict[str, str] = {
    "HOMBA:AA30550": "hippocampal gyrus",
    "HOMBA:266441673": "subicular complex",
    "HOMBA:12165": "uncus of (para)hippocampal gyrus",
    "HOMBA:12161": "paraterminal gyrus",
}
# The boundary used until 2026-10-04 (BNA also for allocortex and the 36 subcortical labels).
PREVIOUS_BNA_TERRITORY_HOMBA_ROOTS: dict[str, str] = {
    "HOMBA:10159": "cerebral cortex (neocortex + allocortex incl. hippocampal formation)",
    "HOMBA:12112": "cerebral gyri and lobules",
    "HOMBA:10610": "cerebral sulci",
    "HOMBA:10361": "amygdaloid complex",
    "HOMBA:AA30190": "regions of basal ganglia (striatum, globus pallidus)",
    "HOMBA:10391": "dorsal thalamus",
}


def _label(label_id: int | str | None) -> int | None:
    try:
        value = int(str(label_id))
    except (TypeError, ValueError):
        return None
    return value if 1 <= value <= BNA_LABEL_COUNT else None


def bna_label_division(label_id: int | str | None) -> str | None:
    """Return ``"cortical"`` / ``"subcortical"`` for a BNA label ID, else None."""
    value = _label(label_id)
    if value is None:
        return None
    return "cortical" if value in BNA_CORTICAL_LABEL_IDS else "subcortical"


def bna_label_is_neocortex(label_id: int | str | None) -> bool | None:
    """Whether a BNA label is neocortex, i.e. a SABRA region (None for an invalid label)."""
    value = _label(label_id)
    if value is None:
        return None
    left = value if value % 2 == 1 else value - 1
    return value in BNA_CORTICAL_LABEL_IDS and left not in BNA_NON_NEOCORTICAL_CORTICAL_AREAS


def sabra_for_bna_area(bna_l2_abbr: str, label_id_l: str = "", label_id_r: str = "") -> dict[str, object]:
    """SABRA annotation for a BNA area: ``atlas`` BNA for neocortex, else DHBA with the containing DHBA term."""
    label = _label(label_id_l) or _label(label_id_r)
    division = bna_label_division(label)
    if division is None and bna_l2_abbr:
        division = "subcortical" if bna_l2_abbr in BNA_SUBCORTICAL_L2 else "cortical"
    if not label and bna_l2_abbr in BNA_MIXED_L2:
        areas = ", ".join(
            f"{name} (BNA:{left}-{left + 1})" for left, name in BNA_MIXED_L2_NEOCORTICAL_AREAS[bna_l2_abbr].items()
        )
        return {
            "atlas": ATLAS_BNA,
            "bna_division": "cortical",
            "sabra_unit": False,
            "note": f"{BNA_MIXED_L2[bna_l2_abbr]}; not a SABRA unit as a whole: name a subregion "
            f"({areas}) or the DHBA term (HOMBA:10317 EC, HOMBA:10330 TI)",
        }
    neocortex = bna_label_is_neocortex(label) if label else division == "cortical"
    if neocortex:
        return {"atlas": ATLAS_BNA, "bna_division": division, "sabra_unit": True}
    left = label if label is None or label % 2 == 1 else label - 1
    homba_id, acronym = BNA_DHBA_COUNTERPARTS.get(left or 0, ("", ""))
    note = (
        "not neocortex: SABRA uses DHBA here; resolve the region with search_homba_candidates "
        "(dhba_homba_id is only the DHBA term that contains this BNA area)"
    )
    if homba_id == "HOMBA:12170" or (not label and bna_l2_abbr == "Hipp"):
        note += "; " + HIPPOCAMPUS_HINT
    return {
        "atlas": ATLAS_DHBA,
        "bna_division": division,
        "sabra_unit": False,
        "dhba_homba_id": homba_id,
        "dhba_acronym": acronym,
        "note": note,
    }


def sabra_for_homba_term(generator: "RosettaCandidateGenerator", homba_id: str) -> dict[str, object] | None:
    """Classify a HOMBA term under SABRA.

    Returns ``atlas`` = ``"BNA"`` when the term lies in a BNA-territory subtree
    (the SABRA name must then come from RCS_EBL / BNA, not from DHBA), otherwise
    ``"DHBA"`` with the DHBA name to use. When the term itself has no DHBA name,
    the nearest ancestor that has one is returned and ``dhba_exact`` is False.
    """
    index = generator.term_index_by_id.get(homba_id)
    if index is None:
        return None

    chain = []
    seen: set[str] = set()
    current = generator.terms[index]
    while current is not None and current.homba_id not in seen:
        seen.add(current.homba_id)
        chain.append(current)
        parent_index = generator.term_index_by_id.get(current.parent_id) if current.parent_id else None
        current = generator.terms[parent_index] if parent_index is not None else None

    for term in chain:
        if term.homba_id in BNA_TERRITORY_EXCLUDED_HOMBA:
            break
        if term.homba_id in BNA_TERRITORY_HOMBA_ROOTS:
            return {
                "atlas": ATLAS_BNA,
                "bna_territory": BNA_TERRITORY_HOMBA_ROOTS[term.homba_id],
                "bna_territory_root": term.homba_id,
            }

    for term in chain:
        if term.dhba_name:
            return {
                "atlas": ATLAS_DHBA,
                "dhba_name": term.dhba_name,
                "dhba_acronym": term.dhba_acronym,
                "dhba_homba_id": term.homba_id,
                "dhba_exact": term.homba_id == homba_id,
            }
    return {"atlas": ATLAS_DHBA, "dhba_name": "", "dhba_acronym": "", "dhba_homba_id": "", "dhba_exact": False}
