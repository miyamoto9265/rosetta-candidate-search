# cbm_data

CBM（Coordinate-to-Brain Mapper）の SABRA ボリューム。鈴木さんの CBM_v0（2026-09-08、Google ドライブの CBM_v0 フォルダ）から取り込んだもの。

| ファイル | 内容 |
|---|---|
| `SABRA.nii.gz` | MNI152 2009、0.5 mm、形状 (394, 466, 378)、uint32。BNA の皮質ラベル 1–210 と DHBA（100000 ＋ DHBA のラベル値） |
| `SABRA_labels.csv` | `sabra_id, source (BNA / DHBA), orig_id, name`。524 ラベル（BNA 210 ＋ DHBA 314） |

`scripts/build_cbm_atlas.py` がこれを `rcs/cbm_atlas.bin`（x 方向の同一ラベルの区間）に変換し、MCP ツール `map_coordinates` が使う。
ボリュームを差し替えたら `python scripts/build_cbm_atlas.py` と `python -m unittest discover -s tests` を通すこと。説明は [SABRA 定義](../docs/sabra.md#座標から引くcbm)。
