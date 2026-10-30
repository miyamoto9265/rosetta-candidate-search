#!/usr/bin/env python3
"""Build rcs/cbm_atlas.bin (the CBM coordinate lookup) from the SABRA volume in cbm_data/.

Input (from Suzuki's CBM_v0, 2026-09-08):
  cbm_data/SABRA.nii.gz      MNI152 2009, 0.5 mm, uint32 labels (BNA 1-210, DHBA 100000 + DHBA label value)
  cbm_data/SABRA_labels.csv  sabra_id, source (BNA / DHBA), orig_id, name

Output: runs of equal labels along x for every (y, z) row plus per-label metadata, so the
Lambda can resolve coordinates with the standard library only (no numpy / nibabel). Pure Python on
purpose: it runs inside the Lambda image like the other cache builds (about 30 s).
"""

from __future__ import annotations

import argparse
import csv
import gzip
import itertools
import json
import struct
import sys
import time
from array import array
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs import cbm  # noqa: E402

DATA_DIR = REPO_ROOT / "cbm_data"
HOMBA_CSV = REPO_ROOT / "rcs" / "HOMBA_v1_fixed.csv"
BNA_TABLE = REPO_ROOT / "ebl_for_rcs_v1.0_20260722" / "rcs_ready" / "bna_name_candidates.csv"

GRAY_MATTER_ROOT = "HOMBA:AA30000"
WHITE_MATTER_ROOT = "HOMBA:AA30482"
VENTRICLES_ROOT = "HOMBA:266441451"
CEREBRAL_GYRI_ROOT = "HOMBA:12112"
HIPPOCAMPAL_GYRUS = "HOMBA:AA30550"
CEREBELLUM_SURFACE_ROOT = "HOMBA:12827"

NIFTI_DTYPES = {2: "B", 4: "h", 8: "i", 512: "H", 768: "I"}


def read_nifti(path: Path) -> tuple[tuple[int, int, int], list[list[float]], array]:
    raw = gzip.decompress(path.read_bytes())
    if struct.unpack("<i", raw[:4])[0] != 348:
        raise ValueError(f"{path}: not a little-endian NIfTI-1 file")
    dim = struct.unpack("<8h", raw[40:56])
    datatype = struct.unpack("<h", raw[70:72])[0]
    vox_offset = int(struct.unpack("<f", raw[108:112])[0])
    slope, inter = struct.unpack("<2f", raw[112:120])
    sform_code = struct.unpack("<h", raw[254:256])[0]
    if dim[0] != 3 or sform_code <= 0 or datatype not in NIFTI_DTYPES or slope not in (0.0, 1.0) or inter != 0.0:
        raise ValueError(f"{path}: unsupported NIfTI layout (dim={dim}, datatype={datatype}, sform={sform_code})")
    srow = struct.unpack("<12f", raw[280:328])
    affine = [list(srow[0:4]), list(srow[4:8]), list(srow[8:12])]
    shape = (dim[1], dim[2], dim[3])
    data = array(NIFTI_DTYPES[datatype])
    count = shape[0] * shape[1] * shape[2]
    data.frombytes(raw[vox_offset : vox_offset + count * data.itemsize])
    if sys.byteorder != "little":
        data.byteswap()
    return shape, affine, data


def homba_chains() -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    rows: dict[str, dict[str, str]] = {}
    by_label_value: dict[str, list[str]] = {}
    with open(HOMBA_CSV, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["unified_ontology_id"]] = row
    for hid, row in rows.items():
        chain, cur = [], hid
        while cur and cur in rows and cur not in chain:
            chain.append(cur)
            cur = rows[cur]["parent_identifier"]
        by_label_value[row["unified_ontology_label_value"].strip()] = chain
    return rows, by_label_value


def dhba_tissue(chain: list[str]) -> str:
    if WHITE_MATTER_ROOT in chain:
        return cbm.TISSUE_WHITE_MATTER
    if VENTRICLES_ROOT in chain:
        return cbm.TISSUE_VENTRICLE
    if GRAY_MATTER_ROOT in chain or HIPPOCAMPAL_GYRUS in chain or CEREBELLUM_SURFACE_ROOT in chain:
        return cbm.TISSUE_GRAY_MATTER
    if CEREBRAL_GYRI_ROOT in chain:
        # DHBA's gyrus labels fill the thin band (~1 mm) around BNA's gray-matter parcels.
        return cbm.TISSUE_CORTEX_OUTSIDE_BNA
    return cbm.TISSUE_OTHER


def label_table() -> list[dict[str, object]]:
    bna: dict[int, dict[str, str]] = {}
    with open(BNA_TABLE, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bna[int(row["bna_label_id_l"])] = row
    homba, by_label_value = homba_chains()

    labels: list[dict[str, object]] = []
    with open(DATA_DIR / "SABRA_labels.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sabra_id, orig = int(row["sabra_id"]), int(row["orig_id"])
            if row["source"] == "BNA":
                area = bna[orig if orig % 2 else orig - 1]
                labels.append({
                    "sabra_id": sabra_id,
                    "atlas": "BNA",
                    "bna_label_id": orig,
                    "bna_area_abbr": area["bna_area_abbr"],
                    "bna_area_name": area["bna_area_name"],
                    "bna_l2_abbr": area["bna_l2_abbr"],
                    "side": "left" if orig % 2 else "right",
                    "tissue": cbm.TISSUE_GRAY_MATTER,
                })
            elif row["source"] == "DHBA":
                chain = by_label_value.get(str(orig))
                if not chain:
                    raise ValueError(f"DHBA label {orig} ({row['name']}) has no HOMBA term with that label value")
                labels.append({
                    "sabra_id": sabra_id,
                    "atlas": "DHBA",
                    "dhba_label": orig,
                    "name": row["name"].strip(),
                    "homba_id": chain[0],
                    "homba_name": homba[chain[0]]["unified_ontology_name"].strip(),
                    "tissue": dhba_tissue(chain),
                })
            else:
                raise ValueError(f"unknown source {row['source']!r} for sabra_id {sabra_id}")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the CBM coordinate lookup.")
    parser.add_argument("--output", type=Path, default=cbm.DEFAULT_ATLAS_PATH)
    args = parser.parse_args()

    started = time.perf_counter()
    labels = label_table()
    index_of = {int(lab["sabra_id"]): i + 1 for i, lab in enumerate(labels)}  # 0 = unassigned
    shape, affine, data = read_nifti(DATA_DIR / "SABRA.nii.gz")
    nx, ny, nz = shape

    offsets = array("I", [0])
    starts, ends, values = array("H"), array("H"), array("H")
    unknown: set[int] = set()
    for row in range(ny * nz):
        x = 0
        for value, run in itertools.groupby(data[row * nx : (row + 1) * nx]):
            length = sum(1 for _ in run)
            if value:
                idx = index_of.get(value)
                if idx is None:
                    unknown.add(value)
                else:
                    starts.append(x)
                    ends.append(x + length)
                    values.append(idx)
            x += length
        offsets.append(len(starts))
    if unknown:
        raise ValueError(f"volume has labels missing from SABRA_labels.csv: {sorted(unknown)[:10]}")
    del data

    cbm.write_atlas(args.output, shape=shape, affine=affine, labels=labels, offsets=offsets, starts=starts, ends=ends, values=values)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} ({size_mb:.1f} MB, {len(starts)} runs, {len(labels)} labels) in {time.perf_counter() - started:.1f}s")

    atlas = cbm.load_atlas(args.output)
    probe = atlas.region_at((-38.0, -22.0, 56.0))  # left precentral gyrus, hand knob
    print(f"Probe (-38,-22,56): {json.dumps(probe, ensure_ascii=False)}")
    if not probe or probe.get("atlas") != "BNA":
        print("Verification failed: the probe is not in a BNA area", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
