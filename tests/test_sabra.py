"""SABRA boundary (rcs/sabra.py): BNA = neocortex only, DHBA for everything else.

Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import csv
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rcs import sabra  # noqa: E402


@dataclass
class _Term:
    homba_id: str
    parent_id: str
    dhba_name: str
    dhba_acronym: str


class _Generator:
    """The two attributes of RosettaCandidateGenerator that sabra_for_homba_term reads."""

    def __init__(self) -> None:
        self.terms: list[_Term] = []
        with open(REPO_ROOT / "rcs" / "HOMBA_v1_fixed.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                self.terms.append(
                    _Term(
                        row["unified_ontology_id"],
                        row["parent_identifier"],
                        (row["DHBA_name"] or "").strip(),
                        (row["DHBA_acronym"] or "").strip(),
                    )
                )
        self.term_index_by_id = {t.homba_id: i for i, t in enumerate(self.terms)}


GEN = _Generator()


def atlas(homba_id: str) -> str:
    result = sabra.sabra_for_homba_term(GEN, homba_id)
    assert result is not None, homba_id
    return str(result["atlas"])


class HombaBoundaryTest(unittest.TestCase):
    def test_neocortex_is_bna(self) -> None:
        for hid in (
            "HOMBA:10160",  # neocortex
            "HOMBA:10172",  # prefrontal cortex
            "HOMBA:10269",  # V1
            "HOMBA:10328",  # agranular insular cortex
            "HOMBA:10281",  # subgenual cingulate (area 25)
            "HOMBA:10324",  # retrosplenial cortex
            "HOMBA:10320",  # perirhinal cortex (area 35)
            "HOMBA:10264",  # area TH (parahippocampal)
            "HOMBA:12116",  # middle frontal gyrus
            "HOMBA:12162",  # parahippocampal gyrus
        ):
            self.assertEqual(atlas(hid), "BNA", hid)

    def test_everything_else_is_dhba(self) -> None:
        for hid, acronym in (
            ("HOMBA:12170", "HiF"),  # hippocampal formation
            ("HOMBA:10297", "CA1"),
            ("HOMBA:10295", "DG"),
            ("HOMBA:10317", "EC"),  # entorhinal cortex (periarchicortex)
            ("HOMBA:10311", "Pir"),  # piriform cortex
            ("HOMBA:10330", "TI"),  # temporal agranular insular cortex (peripaleocortex)
            ("HOMBA:10307", "OB"),
            ("HOMBA:10361", "AMY"),
            ("HOMBA:10363", "CEN"),
            ("HOMBA:10339", "NAC"),
            ("HOMBA:10341", "NACs"),
            ("HOMBA:10338", "Pu"),
            ("HOMBA:10342", "GP"),
            ("HOMBA:10391", "DTH"),
            ("HOMBA:10398", "MD"),
            ("HOMBA:10346", "Cla"),  # claustrum (unchanged)
            ("HOMBA:12165", "UN"),  # uncus: allocortical gyrus
            ("HOMBA:266441673", "Subx"),
            ("HOMBA:12161", "PTG"),  # paraterminal gyrus (septal)
        ):
            result = sabra.sabra_for_homba_term(GEN, hid)
            self.assertEqual(result["atlas"], "DHBA", hid)
            self.assertEqual(result["dhba_acronym"], acronym, hid)
            self.assertTrue(result["dhba_exact"], hid)

    def test_unknown_id(self) -> None:
        self.assertIsNone(sabra.sabra_for_homba_term(GEN, "HOMBA:0"))


class BnaAreaTest(unittest.TestCase):
    def test_neocortical_labels(self) -> None:
        for left in (1, 15, 57, 109, 113, 119, 163, 165, 175, 187, 209):
            self.assertTrue(sabra.bna_label_is_neocortex(left), left)
            self.assertTrue(sabra.bna_label_is_neocortex(left + 1), left + 1)
            self.assertEqual(sabra.sabra_for_bna_area("", str(left), str(left + 1))["atlas"], "BNA")

    def test_non_neocortical_labels(self) -> None:
        for left in (115, 117, *range(211, 247, 2)):
            self.assertFalse(sabra.bna_label_is_neocortex(left), left)
            note = sabra.sabra_for_bna_area("", str(left), str(left + 1))
            self.assertEqual(note["atlas"], "DHBA", left)
            self.assertFalse(note["sabra_unit"], left)
            self.assertTrue(str(note["dhba_homba_id"]).startswith("HOMBA:"), left)

    def test_counterparts_are_dhba_terms(self) -> None:
        self.assertEqual(set(sabra.BNA_DHBA_COUNTERPARTS), {115, 117, *range(211, 247, 2)})
        for left, (hid, acronym) in sabra.BNA_DHBA_COUNTERPARTS.items():
            result = sabra.sabra_for_homba_term(GEN, hid)
            self.assertEqual((result["atlas"], result["dhba_acronym"], result["dhba_exact"]), ("DHBA", acronym, True), left)

    def test_side_and_l2_fallback(self) -> None:
        self.assertEqual(sabra.sabra_for_bna_area("Hipp", "", "216")["dhba_homba_id"], "HOMBA:12170")
        self.assertEqual(sabra.sabra_for_bna_area("Tha")["atlas"], "DHBA")
        self.assertEqual(sabra.sabra_for_bna_area("MFG")["atlas"], "BNA")
        self.assertIsNone(sabra.bna_label_is_neocortex(247))


if __name__ == "__main__":
    unittest.main()
