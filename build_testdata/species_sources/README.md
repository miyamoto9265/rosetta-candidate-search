# Species 入力ソース

Species データセット（`rcs_species.csv`）は **Corpus とは独立** し、Macaque / Rat の既存アトラス名称のみを対象とする。

## ファイル

| ファイル | 説明 |
|----------|------|
| `rcs_species_seed.csv` | 旧 `rcs_corpus_source.csv` から移管した論文抽出名称（144件） |
| `atlas_labels/WHS_SD_rat_atlas_v4.label` | Waxholm Space v4 公式ラベル（[NITRC](https://www.nitrc.org/projects/whs-sd-atlas/)） |
| `atlas_labels/SARM_key_table.csv` | SARM Level 6 ROI 表（AFNI `SARM.tgz` から抽出） |
| `atlas_labels/mHOA2_parcellation_units.csv` | mHOA2.0 40 PU（[Rushmore2022](https://doi.org/10.3389/fnana.2022.1035420) Table 6） |

## ビルド

```bash
cd build_testdata
python build_rcs_species.py
```

`SARM.tgz`（~900MB）はリポジトリに含めない。再取得する場合:

```bash
curl -O https://afni.nimh.nih.gov/pub/dist/atlases/macaque/SARM/SARM.tgz
tar -xvf SARM.tgz SARM/SARM/tables_SARM/SARM_key_table.csv
```
