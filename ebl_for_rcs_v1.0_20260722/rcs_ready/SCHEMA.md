# RCS-ready BNA lookup tables (from EBL v1.0)

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
