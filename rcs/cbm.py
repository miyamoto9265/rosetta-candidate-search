"""CBM (Coordinate-to-Brain Mapper): MNI / Talairach coordinates -> SABRA regions.

The coordinate core of Suzuki's CBM_v0 (``SabraAtlas.resolve_coordinate``), served by the MCP tool
``map_coordinates``. The volume is CBM_v0's SABRA.nii.gz (MNI152 2009, 0.5 mm): BNA's cortical
labels 1-210 for neocortical gray matter and DHBA labels for everything else, including white
matter, ventricles and the thin band of DHBA gyrus labels around BNA's parcels.
``scripts/build_cbm_atlas.py`` turns it into ``rcs/cbm_atlas.bin`` (runs of equal labels along x)
so the Lambda needs no numpy.

Per point the result says what lies at the coordinate (``status``: gray_matter / white_matter /
ventricle / cortex_outside_bna / other / unassigned / out_of_bounds), the region there, the share
of each region inside a sphere around it (``overlap``) and, when the point is not in gray matter,
the nearest gray-matter regions. Regions carry the SABRA annotation and the UC anchor
(``BNA:<l>-<r>`` or ``HOMBA:<id>``) used by CoBRAC.

TAL -> MNI follows ROSETTA ``rosetta/coords.py``: the inverse of BrainMap's icbm_spm2tal
(Lancaster 2007, default) or Brett's tal2mni.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from array import array
from bisect import bisect_right
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Sequence

from rcs import sabra

if TYPE_CHECKING:
    from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

DEFAULT_ATLAS_PATH = Path(__file__).resolve().parent / "cbm_atlas.bin"
ATLAS_SOURCE = "CBM_v0 SABRA.nii.gz (MNI152 2009, 0.5 mm; BNA 210 + DHBA 314 labels; 2026-09-08)"
_MAGIC = b"CBMATLAS1\n"

TISSUE_GRAY_MATTER = "gray_matter"
TISSUE_WHITE_MATTER = "white_matter"
TISSUE_VENTRICLE = "ventricle"
TISSUE_CORTEX_OUTSIDE_BNA = "cortex_outside_bna"
TISSUE_OTHER = "other"
STATUS_UNASSIGNED = "unassigned"
STATUS_OUT_OF_BOUNDS = "out_of_bounds"

SPACE_MNI = "MNI"
SPACE_TAL = "TAL"
TAL_LANCASTER = "lancaster"
TAL_BRETT = "brett"

DEFAULT_RADIUS_MM = 3.0
MAX_RADIUS_MM = 10.0
DEFAULT_SEARCH_MM = 10.0
MAX_SEARCH_MM = 20.0
NEAREST_LIMIT = 3
OVERLAP_LIMIT = 8

Matrix = list[list[float]]

# BrainMap icbm_spm2tal (MNI(SPM) -> Talairach), Lancaster et al. 2007.
_ICBM_SPM2TAL: Matrix = [
    [0.9254, 0.0024, -0.0118, -1.0207],
    [-0.0048, 0.9316, -0.0871, -1.7667],
    [0.0152, 0.0883, 0.8924, 4.0926],
    [0.0, 0.0, 0.0, 1.0],
]
_BRETT_ROTN: Matrix = [[1.0, 0.0, 0.0, 0.0], [0.0, 0.9988, 0.05, 0.0], [0.0, -0.05, 0.9988, 0.0], [0.0, 0.0, 0.0, 1.0]]
_BRETT_UPZ: Matrix = [[0.99, 0.0, 0.0, 0.0], [0.0, 0.97, 0.0, 0.0], [0.0, 0.0, 0.92, 0.0], [0.0, 0.0, 0.0, 1.0]]
_BRETT_DOWNZ: Matrix = [[0.99, 0.0, 0.0, 0.0], [0.0, 0.97, 0.0, 0.0], [0.0, 0.0, 0.84, 0.0], [0.0, 0.0, 0.0, 1.0]]


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def _apply(m: Matrix, p: Sequence[float]) -> tuple[float, float, float]:
    v = (p[0], p[1], p[2], 1.0)
    return tuple(sum(m[i][k] * v[k] for k in range(4)) for i in range(3))  # type: ignore[return-value]


def _invert(m: Matrix) -> Matrix:
    n = 4
    a = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        a[col] = [v / p for v in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [vr - f * vc for vr, vc in zip(a[r], a[col])]
    return [row[n:] for row in a]


_ICBM_TAL2SPM = _invert(_ICBM_SPM2TAL)
_BRETT_INV_UP = _invert(_matmul(_BRETT_ROTN, _BRETT_UPZ))
_BRETT_INV_DOWN = _invert(_matmul(_BRETT_ROTN, _BRETT_DOWNZ))


def tal_to_mni(p: Sequence[float], method: str = TAL_LANCASTER) -> tuple[float, float, float]:
    """Talairach -> MNI (ROSETTA ``coords.tal_to_mni``)."""
    if method == TAL_BRETT:
        return _apply(_BRETT_INV_DOWN if p[2] < 0 else _BRETT_INV_UP, p)
    return _apply(_ICBM_TAL2SPM, p)


def write_atlas(
    path: Path,
    *,
    shape: tuple[int, int, int],
    affine: list[list[float]],
    labels: list[dict[str, object]],
    offsets: array,
    starts: array,
    ends: array,
    values: array,
) -> None:
    header = {"shape": list(shape), "affine": affine, "labels": labels, "source": ATLAS_SOURCE}
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(_MAGIC)
        f.write(json.dumps(header, ensure_ascii=False).encode("utf-8") + b"\n")
        for arr in (offsets, starts, ends, values):
            out = array(arr.typecode, arr)
            if sys.byteorder != "little":
                out.byteswap()
            f.write(len(out).to_bytes(4, "little"))
            f.write(out.tobytes())


def _read_array(raw: bytes, pos: int, typecode: str) -> tuple[array, int]:
    n = int.from_bytes(raw[pos : pos + 4], "little")
    pos += 4
    out = array(typecode)
    size = n * out.itemsize
    out.frombytes(raw[pos : pos + size])
    if sys.byteorder != "little":
        out.byteswap()
    return out, pos + size


class CbmAtlas:
    """The SABRA volume as runs of equal labels along x; one row per (y, z)."""

    def __init__(self, header: dict, offsets: array, starts: array, ends: array, values: array) -> None:
        self.shape: tuple[int, int, int] = tuple(header["shape"])  # type: ignore[assignment]
        self.labels: list[dict[str, object]] = header["labels"]
        self.source: str = header.get("source", ATLAS_SOURCE)
        affine = header["affine"]
        for i in range(3):
            for j in range(3):
                if i != j and abs(affine[i][j]) > 1e-6:
                    raise ValueError("CBM atlas affine must be axis-aligned")
        self.voxel_mm = tuple(abs(affine[i][i]) for i in range(3))
        self._scale = tuple(affine[i][i] for i in range(3))
        self._origin = tuple(affine[i][3] for i in range(3))
        self._offsets, self._starts, self._ends, self._values = offsets, starts, ends, values

    # --- voxel access ---------------------------------------------------------

    def to_voxel(self, p: Sequence[float]) -> tuple[float, float, float]:
        return tuple((p[i] - self._origin[i]) / self._scale[i] for i in range(3))  # type: ignore[return-value]

    def in_bounds(self, v: Sequence[float]) -> bool:
        return all(-0.5 <= v[i] < self.shape[i] - 0.5 for i in range(3))

    def _row(self, j: int, k: int) -> tuple[int, int]:
        r = k * self.shape[1] + j
        return self._offsets[r], self._offsets[r + 1]

    def label_index(self, i: int, j: int, k: int) -> int:
        nx, ny, nz = self.shape
        if not (0 <= i < nx and 0 <= j < ny and 0 <= k < nz):
            return 0
        lo, hi = self._row(j, k)
        r = bisect_right(self._starts, i, lo, hi) - 1
        return self._values[r] if r >= lo and i < self._ends[r] else 0

    def label(self, index: int) -> dict[str, object] | None:
        return self.labels[index - 1] if index > 0 else None

    def region_at(self, p: Sequence[float]) -> dict[str, object] | None:
        v = self.to_voxel(p)
        if not self.in_bounds(v):
            return None
        return self.label(self.label_index(*(int(round(c)) for c in v)))

    def scan(self, p: Sequence[float], radius_mm: float, search_mm: float) -> tuple[dict[int, int], int, dict[int, float]]:
        """Voxel counts per label inside the sphere of ``radius_mm`` (0 = unassigned, total = all voxels
        in the sphere) and each label's distance from ``p`` within ``search_mm``."""
        vx, vy, vz = self.voxel_mm
        ci, cj, ck = self.to_voxel(p)
        nx, ny, nz = self.shape
        reach = max(radius_mm, search_mm)
        counts: dict[int, int] = {}
        total = 0
        nearest: dict[int, float] = {}
        k0, k1 = max(0, math.ceil(ck - reach / vz)), min(nz - 1, math.floor(ck + reach / vz))
        j0, j1 = max(0, math.ceil(cj - reach / vy)), min(ny - 1, math.floor(cj + reach / vy))
        for k in range(k0, k1 + 1):
            dz = (k - ck) * vz
            for j in range(j0, j1 + 1):
                dy = (j - cj) * vy
                dyz2 = dy * dy + dz * dz
                if dyz2 > reach * reach:
                    continue
                lo, hi = self._row(j, k)
                in_sphere = radius_mm * radius_mm - dyz2
                i0 = i1 = 0
                if in_sphere >= 0:
                    half = math.sqrt(in_sphere) / vx
                    i0, i1 = max(0, math.ceil(ci - half)), min(nx - 1, math.floor(ci + half))
                    total += max(0, i1 - i0 + 1)
                for r in range(lo, hi):
                    start, end, value = self._starts[r], self._ends[r] - 1, self._values[r]
                    if in_sphere >= 0:
                        overlap = min(end, i1) - max(start, i0) + 1
                        if overlap > 0:
                            counts[value] = counts.get(value, 0) + overlap
                    dx = 0.0 if start <= ci <= end else min(abs(start - ci), abs(end - ci)) * vx
                    d = math.sqrt(dx * dx + dyz2)
                    if d <= search_mm and d < nearest.get(value, math.inf):
                        nearest[value] = d
        counts[0] = total - sum(counts.values())
        return counts, total, nearest


def load_atlas(path: Path = DEFAULT_ATLAS_PATH) -> CbmAtlas:
    raw = gzip.decompress(Path(path).read_bytes())
    if not raw.startswith(_MAGIC):
        raise ValueError(f"{path}: not a CBM atlas file")
    pos = raw.index(b"\n", len(_MAGIC)) + 1
    header = json.loads(raw[len(_MAGIC) : pos])
    offsets, pos = _read_array(raw, pos, "I")
    starts, pos = _read_array(raw, pos, "H")
    ends, pos = _read_array(raw, pos, "H")
    values, pos = _read_array(raw, pos, "H")
    return CbmAtlas(header, offsets, starts, ends, values)


# --- SABRA annotation ----------------------------------------------------------


def _side_of(x: float) -> str:
    return "midline" if abs(x) < 1.0 else ("left" if x < 0 else "right")


def describe_region(
    label: dict[str, object], x: float, generator: "RosettaCandidateGenerator | None" = None
) -> dict[str, object]:
    """Region summary with SABRA annotation and UC anchor (None when the region cannot anchor a UC)."""
    out = dict(label)
    out.pop("sabra_id", None)
    tissue = out["tissue"]
    if out["atlas"] == sabra.ATLAS_BNA:
        lid = int(out["bna_label_id"])  # type: ignore[arg-type]
        left = lid if lid % 2 else lid - 1
        info = sabra.sabra_for_bna_area(str(out["bna_l2_abbr"]), str(left), str(left + 1))
        out["sabra"] = info
        if info.get("sabra_unit"):
            out["anchor"] = f"BNA:{left}-{left + 1}"
        else:
            out["anchor"] = info.get("dhba_homba_id") or None
        return out
    out["side"] = _side_of(x)
    info = sabra.sabra_for_homba_term(generator, str(out["homba_id"])) if generator is not None else None
    out["sabra"] = info
    anchor = None
    if tissue == TISSUE_GRAY_MATTER and info and info.get("atlas") == sabra.ATLAS_DHBA:
        anchor = info.get("dhba_homba_id") or None
    out["anchor"] = anchor
    return out


def _short(region: dict[str, object]) -> dict[str, object]:
    keys = ("atlas", "bna_label_id", "bna_area_abbr", "bna_area_name", "bna_l2_abbr", "name", "homba_id", "side", "tissue", "anchor")
    return {k: region[k] for k in keys if k in region}


def map_coordinate(
    atlas: CbmAtlas,
    point: dict,
    *,
    space: str = SPACE_MNI,
    tal_transform: str = TAL_LANCASTER,
    radius_mm: float = DEFAULT_RADIUS_MM,
    search_mm: float = DEFAULT_SEARCH_MM,
    generator: "RosettaCandidateGenerator | None" = None,
) -> dict[str, object]:
    xyz = (float(point["x"]), float(point["y"]), float(point["z"]))
    space = str(point.get("space") or space).upper()
    if space == SPACE_TAL:
        mni = tal_to_mni(xyz, tal_transform)
        conversion = "lancaster_icbm_spm2tal_inverse" if tal_transform != TAL_BRETT else "brett_tal2mni"
    else:
        mni, conversion = xyz, None
    out: dict[str, object] = {"input": {"x": xyz[0], "y": xyz[1], "z": xyz[2], "space": space}}
    for key in ("label", "stat"):
        if point.get(key) not in (None, ""):
            out["input"][key] = point[key]  # type: ignore[index]
    out["mni"] = [round(c, 2) for c in mni]
    if conversion:
        out["conversion"] = conversion

    v = atlas.to_voxel(mni)
    if not atlas.in_bounds(v):
        out["status"] = STATUS_OUT_OF_BOUNDS
        out["region"] = None
        return out

    here = atlas.label_index(*(int(round(c)) for c in v))
    counts, total, nearest = atlas.scan(mni, radius_mm, search_mm)
    described: dict[int, dict[str, object]] = {}

    def region(index: int) -> dict[str, object]:
        if index not in described:
            described[index] = describe_region(atlas.label(index), mni[0], generator)  # type: ignore[arg-type]
        return described[index]

    out["region"] = region(here) if here else None
    out["status"] = str(region(here)["tissue"]) if here else STATUS_UNASSIGNED
    if total:
        overlap = sorted(((c, i) for i, c in counts.items() if c), reverse=True)[:OVERLAP_LIMIT]
        out["overlap"] = [
            {"fraction": round(c / total, 3), **({"region": _short(region(i))} if i else {"region": None, "status": STATUS_UNASSIGNED})}
            for c, i in overlap
        ]
    if out["status"] != TISSUE_GRAY_MATTER:
        gray = sorted(
            (d, i) for i, d in nearest.items() if i and atlas.label(i)["tissue"] == TISSUE_GRAY_MATTER  # type: ignore[index]
        )[:NEAREST_LIMIT]
        out["nearest_gray_matter"] = [{"distance_mm": round(d, 1), "region": _short(region(i))} for d, i in gray]
    return out


def map_coordinates(
    atlas: CbmAtlas,
    points: Iterable[dict],
    **kwargs: object,
) -> list[dict[str, object]]:
    return [map_coordinate(atlas, p, **kwargs) for p in points]  # type: ignore[arg-type]


def summarize(results: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """CBM ``records`` (aggregated): one entry per anchor of the gray-matter points, with the number of
    points (``peak_count``), the largest ``stat`` given (``max_stat``) and the input labels."""
    groups: dict[str, dict[str, object]] = {}
    for r in results:
        region = r.get("region")
        if r.get("status") != TISSUE_GRAY_MATTER or not isinstance(region, dict) or not region.get("anchor"):
            continue
        g = groups.setdefault(str(region["anchor"]), {"anchor": region["anchor"], "region": _short(region), "peak_count": 0, "labels": []})
        g["peak_count"] = int(g["peak_count"]) + 1  # type: ignore[call-overload]
        inp = r["input"]
        stat = inp.get("stat") if isinstance(inp, dict) else None
        if isinstance(stat, (int, float)) and not isinstance(stat, bool):
            g["max_stat"] = max(float(stat), float(g.get("max_stat", stat)))  # type: ignore[arg-type]
        label = inp.get("label") if isinstance(inp, dict) else None
        if label and label not in g["labels"]:  # type: ignore[operator]
            g["labels"].append(label)  # type: ignore[union-attr]
    return sorted(groups.values(), key=lambda g: (-int(g["peak_count"]), -float(g.get("max_stat", 0))))  # type: ignore[arg-type]
