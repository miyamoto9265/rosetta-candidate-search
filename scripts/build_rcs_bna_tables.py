#!/usr/bin/env python3
"""Build RCS-ready BNA lookup tables from EBL v1.0 deliverables.

Independent of the HOMBA-based RCS candidate generator. Idempotent.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EBL_DIR = REPO_ROOT / "ebl_for_rcs_v1.0_20260722"
DEFAULT_OUT_DIR = DEFAULT_EBL_DIR / "rcs_ready"

INDEX_FIELDS = [
    "lit_name",
    "lit_surface_top",
    "lit_hemi_seen",
    "k_papers",
    "eff_n",
    "n80",
    "n_candidates",
    "p_covered_top5",
    "l2_top_abbr",
    "l2_top_name",
    "l2_top_lobe",
    "l2_top_p_raw",
    "r1_area_abbr",
    "r1_L3",
    "r1_label_L",
    "r1_label_R",
    "r1_p",
    "hemi_U_p_coord_L",
    "hemi_U_k_papers",
    "hemi_U_k_coords",
    "hemi_U_agreement",
]

CANDIDATE_FIELDS = [
    "lit_name",
    "rank",
    "bna_l2_abbr",
    "bna_l3_code",
    "bna_area_abbr",
    "bna_area_name",
    "bna_label_id_l",
    "bna_label_id_r",
    "p_raw",
    "p",
    "n_papers",
    "n_coords",
    "k_papers",
    "n_support",
]

L2_FIELDS = [
    "lit_name",
    "rank",
    "bna_l2_abbr",
    "bna_l2_name",
    "bna_lobe",
    "p_raw",
    "p",
    "n_papers",
    "n_coords",
    "k_papers",
    "eff_n",
    "n80",
    "n_observed",
    "top1_p",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_hemi_u_map(hemi_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Prefer lit_hemisphere == U; otherwise keep first seen row per lit_name."""
    preferred: dict[str, dict[str, str]] = {}
    fallback: dict[str, dict[str, str]] = {}
    for row in hemi_rows:
        name = row["lit_name"]
        if row.get("lit_hemisphere") == "U":
            preferred.setdefault(name, row)
        else:
            fallback.setdefault(name, row)
    out = dict(fallback)
    out.update(preferred)
    return out


def build_l2_top_map(stage1_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    tops: dict[str, dict[str, str]] = {}
    for row in stage1_rows:
        if str(row.get("rank", "")).strip() != "1":
            continue
        tops[row["lit_name"]] = row
    return tops


def build_index(
    flat_rows: list[dict[str, str]],
    l2_tops: dict[str, dict[str, str]],
    hemi_u: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for flat in flat_rows:
        name = flat["lit_name"]
        l2 = l2_tops.get(name, {})
        hemi = hemi_u.get(name, {})
        rows.append(
            {
                "lit_name": name,
                "lit_surface_top": flat.get("lit_surface_top", ""),
                "lit_hemi_seen": flat.get("lit_hemi_seen", ""),
                "k_papers": flat.get("k_papers", ""),
                "eff_n": flat.get("eff_n", ""),
                "n80": flat.get("n80", ""),
                "n_candidates": flat.get("n_candidates", ""),
                "p_covered_top5": flat.get("p_covered_top5", ""),
                "l2_top_abbr": l2.get("bna_L2_abbr", ""),
                "l2_top_name": l2.get("bna_L2_name", ""),
                "l2_top_lobe": l2.get("bna_lobe", ""),
                "l2_top_p_raw": l2.get("p_raw", ""),
                "r1_area_abbr": flat.get("r1_area_abbr", ""),
                "r1_L3": flat.get("r1_L3", ""),
                "r1_label_L": flat.get("r1_label_L", ""),
                "r1_label_R": flat.get("r1_label_R", ""),
                "r1_p": flat.get("r1_p", ""),
                "hemi_U_p_coord_L": hemi.get("p_coord_L", ""),
                "hemi_U_k_papers": hemi.get("k_papers", ""),
                "hemi_U_k_coords": hemi.get("k_coords", ""),
                "hemi_U_agreement": hemi.get("hemi_agreement", ""),
            }
        )
    return rows


def build_candidates(long_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "lit_name": row["lit_name"],
            "rank": row.get("rank", ""),
            "bna_l2_abbr": row.get("bna_L2_abbr", ""),
            "bna_l3_code": row.get("bna_L3_code", ""),
            "bna_area_abbr": row.get("bna_area_abbr", ""),
            "bna_area_name": row.get("bna_area_name", ""),
            "bna_label_id_l": row.get("bna_label_id_L", ""),
            "bna_label_id_r": row.get("bna_label_id_R", ""),
            "p_raw": row.get("p_raw", ""),
            "p": row.get("p", ""),
            "n_papers": row.get("n_papers", ""),
            "n_coords": row.get("n_coords", ""),
            "k_papers": row.get("k_total", ""),
            "n_support": row.get("n_support", ""),
        }
        for row in long_rows
    ]


def build_l2_candidates(stage1_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "lit_name": row["lit_name"],
            "rank": row.get("rank", ""),
            "bna_l2_abbr": row.get("bna_L2_abbr", ""),
            "bna_l2_name": row.get("bna_L2_name", ""),
            "bna_lobe": row.get("bna_lobe", ""),
            "p_raw": row.get("p_raw", ""),
            "p": row.get("p", ""),
            "n_papers": row.get("n_papers", ""),
            "n_coords": row.get("n_coords", ""),
            "k_papers": row.get("k_papers", ""),
            "eff_n": row.get("eff_n", ""),
            "n80": row.get("n80", ""),
            "n_observed": row.get("n_observed", ""),
            "top1_p": row.get("top1_p", ""),
        }
        for row in stage1_rows
    ]


SCHEMA_MD = """# RCS-ready BNA lookup tables (from EBL v1.0)

Generated from `ebl_for_rcs_v1.0_20260722/` by `scripts/build_rcs_bna_tables.py`.

**Not wired into the HOMBA-based RCS candidate generator.** These tables are for a
separate name→BNA lookup path (neocortex / cortical labels).

## Lookup flow

```
query
  → normalize_text (RCS §3.1; EBL keys already use this form)
  → lit_name exact match on bna_name_index / candidates
  → read candidate distribution (prefer p_raw)
  → caller picks laterality → bna_label_id_l or bna_label_id_r
```

Hemisphere is **not** encoded in the key. Keep both label IDs; resolve L/R upstream.

## Files

| File | Grain | Rows (expected) | Role |
|---|---|---|---|
| `bna_name_index.csv` | 1 name / 1 row | 3747 | Index + quality + L2 top + L3 rank-1 summary |
| `bna_name_candidates.csv` | name × L3 candidate | 9719 | **Primary** BNA L3 probability distribution |
| `bna_name_l2_candidates.csv` | name × L2 candidate | ~6507 | Gyrus-level fallback (~78% hold-out) |

## Probability and confidence

- Use **`p_raw`** as the primary probability (`p` is Dirichlet-smoothed, reference only).
- **`k_papers`**: support size / reliability.
- **`eff_n`**: how peaked the distribution is (1.0 ≈ unique; larger ≈ diffuse).
- **`n80`**: how many candidates cover 80% of mass (index / L2 tables).

Suggested filters (do not drop rows from these tables; filter at query time):

| Filter | Approx. names | Use |
|---|---|---|
| none | 3747 | Full vocabulary |
| `k_papers >= 5` | ~617 | Light production filter |
| `k_papers > 30` | ~115 | High-confidence subset; also check `eff_n` |

L3 fine regions are **not** unique in principle (EBL hold-out ~38%). Prefer L2 when a single label is required, or return a ranked distribution.

## Column reference

### `bna_name_index.csv`

| Column | Source | Notes |
|---|---|---|
| `lit_name` | flat | Lookup key |
| `lit_surface_top` | flat | Most common surface form |
| `lit_hemi_seen` | flat | Hemispheres seen in literature (L/R/B/U) |
| `k_papers`, `eff_n`, `n80`, `n_candidates`, `p_covered_top5` | flat | Quality |
| `l2_top_abbr`, `l2_top_name`, `l2_top_lobe`, `l2_top_p_raw` | stage1 rank=1 | Top L2 gyrus |
| `r1_area_abbr`, `r1_L3`, `r1_label_L`, `r1_label_R`, `r1_p` | flat r1 | Top L3 summary (`r1_p` is smoothed) |
| `hemi_U_p_coord_L`, `hemi_U_k_papers`, `hemi_U_k_coords`, `hemi_U_agreement` | hemisphere U row | Optional laterality meta |

### `bna_name_candidates.csv`

| Column | Source | Notes |
|---|---|---|
| `lit_name`, `rank` | long | Key + order |
| `bna_l2_abbr`, `bna_l3_code`, `bna_area_abbr`, `bna_area_name` | long | BNA labels |
| `bna_label_id_l`, `bna_label_id_r` | long | BNA label_id 1–246 |
| `p_raw`, `p` | long | Prefer `p_raw` |
| `n_papers`, `n_coords` | long | Per-candidate support |
| `k_papers` | long `k_total` | Name-level support |
| `n_support` | long | Name-level support nodes |

### `bna_name_l2_candidates.csv`

| Column | Source | Notes |
|---|---|---|
| `lit_name`, `rank` | stage1 | Key + order |
| `bna_l2_abbr`, `bna_l2_name`, `bna_lobe` | stage1 | Gyrus / lobe |
| `p_raw`, `p`, `n_papers`, `n_coords` | stage1 | Prefer `p_raw` |
| `k_papers`, `eff_n`, `n80`, `n_observed`, `top1_p` | stage1 | Name-level L2 quality |

## Sources used / not used

Used: `ebl_flat_name_to_bna.csv`, `ebl_flat_name_to_bna_long.csv`,
`reference/ebl_stage1_name_to_L2.csv`, `reference/ebl_hemisphere_axis.csv`.

Not used here: `ebl_alias_evidence.csv`, `ebl_synonym_map.csv`,
`reference/ebl_stage2_name_to_L3.csv` (HOMBA rules / conditional L3).

## Regenerate

```bash
python scripts/build_rcs_bna_tables.py
```
"""


def build(ebl_dir: Path, out_dir: Path) -> dict[str, int]:
    flat_path = ebl_dir / "ebl_flat_name_to_bna.csv"
    long_path = ebl_dir / "ebl_flat_name_to_bna_long.csv"
    stage1_path = ebl_dir / "reference" / "ebl_stage1_name_to_L2.csv"
    hemi_path = ebl_dir / "reference" / "ebl_hemisphere_axis.csv"

    for path in (flat_path, long_path, stage1_path, hemi_path):
        if not path.is_file():
            raise FileNotFoundError(f"Missing EBL input: {path}")

    flat_rows = read_csv(flat_path)
    long_rows = read_csv(long_path)
    stage1_rows = read_csv(stage1_path)
    hemi_rows = read_csv(hemi_path)

    l2_tops = build_l2_top_map(stage1_rows)
    hemi_u = build_hemi_u_map(hemi_rows)

    index_rows = build_index(flat_rows, l2_tops, hemi_u)
    candidate_rows = build_candidates(long_rows)
    l2_rows = build_l2_candidates(stage1_rows)

    flat_names = {r["lit_name"] for r in flat_rows}
    index_names = {r["lit_name"] for r in index_rows}
    if flat_names != index_names:
        missing = sorted(flat_names - index_names)
        extra = sorted(index_names - flat_names)
        raise RuntimeError(
            f"Index key mismatch vs flat: missing={len(missing)} extra={len(extra)}"
        )

    missing_l2_top = sorted(flat_names - set(l2_tops))
    if missing_l2_top:
        raise RuntimeError(
            f"stage1 rank=1 missing for {len(missing_l2_top)} names "
            f"(e.g. {missing_l2_top[:5]})"
        )

    write_csv(out_dir / "bna_name_index.csv", INDEX_FIELDS, index_rows)
    write_csv(out_dir / "bna_name_candidates.csv", CANDIDATE_FIELDS, candidate_rows)
    write_csv(out_dir / "bna_name_l2_candidates.csv", L2_FIELDS, l2_rows)
    (out_dir / "SCHEMA.md").write_text(SCHEMA_MD, encoding="utf-8")

    return {
        "index": len(index_rows),
        "candidates": len(candidate_rows),
        "l2_candidates": len(l2_rows),
        "l2_tops": len(l2_tops),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ebl-dir",
        type=Path,
        default=DEFAULT_EBL_DIR,
        help="EBL package directory",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for RCS-ready tables",
    )
    args = parser.parse_args()
    counts = build(args.ebl_dir.resolve(), args.out_dir.resolve())
    print(f"Wrote tables to {args.out_dir.resolve()}")
    for key, value in counts.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
