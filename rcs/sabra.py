"""SABRA Ontology — canonical definition in code.

SABRA (Standardized Ontology of Anatomies for Brain Reference Architecture) is the
organisation's mixed brain atlas used for region names (e.g. CoBRAC circuit names).
It is *not* a new ontology with its own IDs; every SABRA region is a region of one
of two existing atlases:

* **BNA** (Brainnetome Atlas, 246 labels per both hemispheres = 123 areas x L/R)
  - neocortex and surrounding cortex: label IDs 1-210
  - subcortical nuclei: label IDs 211-246 — amygdala (Amyg), hippocampus (Hipp),
    basal ganglia (BG) and thalamus (Tha)
* **DHBA** (Developing Human Brain Atlas) for everything else (hypothalamus,
  brainstem, cerebellum, ...). DHBA terms are the subset of HOMBA that carry a
  ``DHBA_name`` (``dhba_filter="with"`` in RCS).

Tooling: RCS (HOMBA) resolves names to HOMBA -> DHBA; RCS_EBL resolves names to BNA.
Human-readable definition and workflow: ``docs/sabra.md``. Keep both in sync.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

SABRA_NAME = "SABRA"
SABRA_FULL_NAME = "Standardized Ontology of Anatomies for Brain Reference Architecture"

ATLAS_BNA = "BNA"
ATLAS_DHBA = "DHBA"

BNA_LABEL_COUNT = 246
BNA_CORTICAL_LABEL_IDS = range(1, 211)
BNA_SUBCORTICAL_LABEL_IDS = range(211, 247)
# BNA L2 (gyrus-level) groups that make up the 36 subcortical labels.
BNA_SUBCORTICAL_L2 = {
    "Amyg": "amygdala",
    "Hipp": "hippocampus",
    "BG": "basal ganglia",
    "Tha": "thalamus",
}

# HOMBA subtrees that SABRA represents with BNA instead of DHBA. Anything outside
# these roots is represented with DHBA. The thalamus root is the *dorsal*
# thalamus because BNA's 8 thalamic subregions are dorsal-thalamic nuclei;
# epithalamus (habenula), ventral thalamus and subthalamus have no BNA label.
# Basal ganglia is limited to striatum + globus pallidus for the same reason.
BNA_TERRITORY_HOMBA_ROOTS: dict[str, str] = {
    "HOMBA:10159": "cerebral cortex (neocortex + allocortex incl. hippocampal formation)",
    "HOMBA:12112": "cerebral gyri and lobules",
    "HOMBA:10610": "cerebral sulci",
    "HOMBA:10361": "amygdaloid complex",
    "HOMBA:AA30190": "regions of basal ganglia (striatum, globus pallidus)",
    "HOMBA:10391": "dorsal thalamus",
}


def bna_label_division(label_id: int | str | None) -> str | None:
    """Return ``"cortical"`` / ``"subcortical"`` for a BNA label ID, else None."""
    try:
        value = int(str(label_id))
    except (TypeError, ValueError):
        return None
    if value in BNA_CORTICAL_LABEL_IDS:
        return "cortical"
    if value in BNA_SUBCORTICAL_LABEL_IDS:
        return "subcortical"
    return None


def sabra_for_bna_area(bna_l2_abbr: str, label_id_l: str = "", label_id_r: str = "") -> dict[str, object]:
    """SABRA annotation for a BNA area (every BNA label is a SABRA region)."""
    division = bna_label_division(label_id_l or label_id_r)
    if division is None and bna_l2_abbr:
        division = "subcortical" if bna_l2_abbr in BNA_SUBCORTICAL_L2 else "cortical"
    return {"atlas": ATLAS_BNA, "bna_division": division}


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
