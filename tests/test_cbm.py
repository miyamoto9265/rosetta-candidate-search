"""CBM coordinate mapping (rcs/cbm.py) on the SABRA volume in cbm_data/.

Builds rcs/cbm_atlas.bin first when it is missing (about 10 s).
Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rcs import cbm  # noqa: E402
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402


class CbmTest(unittest.TestCase):
    atlas: cbm.CbmAtlas
    generator: RosettaCandidateGenerator

    @classmethod
    def setUpClass(cls) -> None:
        if not cbm.DEFAULT_ATLAS_PATH.exists():
            subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_cbm_atlas.py")], check=True)
        cls.atlas = cbm.load_atlas()
        cls.generator = RosettaCandidateGenerator(REPO_ROOT / "rcs" / "HOMBA_v1_fixed.csv")

    def map(self, x: float, y: float, z: float, **kwargs: object) -> dict:
        return cbm.map_coordinate(self.atlas, {"x": x, "y": y, "z": z}, generator=self.generator, **kwargs)

    def test_neocortex_is_a_bna_area(self) -> None:
        r = self.map(-38, -22, 56)  # left hand knob
        self.assertEqual(r["status"], cbm.TISSUE_GRAY_MATTER)
        self.assertEqual(r["region"]["bna_area_abbr"], "A4ul")
        self.assertEqual(r["region"]["side"], "left")
        self.assertEqual(r["region"]["anchor"], "BNA:57-58")
        self.assertNotIn("nearest_gray_matter", r)

    def test_subcortex_is_a_dhba_term(self) -> None:
        r = self.map(-24, 4, 2)  # left putamen
        self.assertEqual(r["status"], cbm.TISSUE_GRAY_MATTER)
        self.assertEqual(r["region"]["atlas"], "DHBA")
        self.assertEqual(r["region"]["sabra"]["atlas"], "DHBA")
        self.assertEqual(r["region"]["anchor"], "HOMBA:10338")  # middle putamen has no DHBA name -> putamen

    def test_white_matter_has_no_anchor_but_nearest_gray(self) -> None:
        r = self.map(0, 0, 24)  # corpus callosum
        self.assertEqual(r["status"], cbm.TISSUE_WHITE_MATTER)
        self.assertIsNone(r["region"]["anchor"])
        self.assertTrue(r["nearest_gray_matter"])
        self.assertEqual(r["nearest_gray_matter"][0]["region"]["tissue"], cbm.TISSUE_GRAY_MATTER)

    def test_outside_brain_and_volume(self) -> None:
        self.assertEqual(self.map(0, 0, 90)["status"], cbm.STATUS_UNASSIGNED)
        r = self.map(200, 0, 0)
        self.assertEqual(r["status"], cbm.STATUS_OUT_OF_BOUNDS)
        self.assertIsNone(r["region"])

    def test_overlap_fractions_sum_to_one(self) -> None:
        r = self.map(-24, 4, 2, radius_mm=4)
        self.assertAlmostEqual(sum(o["fraction"] for o in r["overlap"]), 1.0, delta=0.01)
        point = self.map(-22, -4, -18, radius_mm=0)["overlap"]
        self.assertEqual([o["fraction"] for o in point], [1.0])

    def test_talairach_is_converted(self) -> None:
        r = self.map(-40, -22, 52, space="TAL")
        self.assertEqual(r["conversion"], "lancaster_icbm_spm2tal_inverse")
        self.assertAlmostEqual(r["mni"][2], 56.04, places=1)
        mni = cbm.tal_to_mni((10.0, 20.0, -10.0), cbm.TAL_BRETT)
        self.assertNotEqual(mni, cbm.tal_to_mni((10.0, 20.0, -10.0)))

    def test_scan_matches_point_lookup(self) -> None:
        counts, total, nearest = self.atlas.scan((-38.0, -22.0, 56.0), 0.0, 0.0)
        self.assertEqual(total, 1)
        here = [i for i, c in counts.items() if c and i]
        self.assertEqual(self.atlas.label(here[0])["bna_label_id"], 57)
        self.assertIn(here[0], nearest)

    def test_summary_groups_gray_matter_points(self) -> None:
        results = [
            cbm.map_coordinate(self.atlas, p, generator=self.generator)
            for p in ({"x": -38, "y": -22, "z": 56, "stat": 5.1, "label": "M1"}, {"x": -38, "y": -23, "z": 56, "stat": 6.3},
                      {"x": 0, "y": 0, "z": 24})
        ]
        regions = cbm.summarize(results)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["anchor"], "BNA:57-58")
        self.assertEqual(regions[0]["peak_count"], 2)
        self.assertEqual(regions[0]["max_stat"], 6.3)
        self.assertEqual(regions[0]["labels"], ["M1"])

    def test_every_dhba_label_maps_to_a_homba_term(self) -> None:
        dhba = [lab for lab in self.atlas.labels if lab["atlas"] == "DHBA"]
        self.assertEqual(len(dhba), 314)
        self.assertTrue(all(self.generator.term_index_by_id.get(str(lab["homba_id"])) is not None for lab in dhba))


if __name__ == "__main__":
    unittest.main()
