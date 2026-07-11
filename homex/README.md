# HOMEX — HOMBA Extensions

HOMBA の細分不足を補う拡張レイヤー。HOMBA 本体は変更せず、より細かい解剖学的区分を HOMBA 親の下に追加する。

## ファイル

| ファイル | 内容 |
|----------|------|
| `homex_terms.csv` | 細分エントリ本体（現状この1表のみ） |

## スキーマ（`homex_terms.csv`）

| 列 | 必須 | 説明 |
|----|------|------|
| `homex_id` | yes | 一意 ID。形式は `HOMEX:000001` からの連番 |
| `name` | yes | 標準名 |
| `acronym` | no | 略語（なければ空） |
| `homba_parent_id` | yes | ぶら下がる HOMBA 親 ID（例: `HOMBA:10368`） |

すべての HOMEX ノードは、必ず1つの HOMBA 親を持つ。関係は当面すべて part-of（細分）とみなす。

## 設計方針（最小）

- HOMBA CSV への行追加はしない
- 同義語表・status・level・relation 列は後回し
- 多段細分用の `homex_parent_id` も、必要になってから追加する
- RCS への組み込みは、エントリが溜まってから検討する

## 追加手順（案）

1. top-1 検証などで `broader_parent` となったクエリを候補にする
2. 対応する HOMBA 親 ID を決める
3. `homex_terms.csv` に1行追加する（`HOMEX:` 連番を振る）

## 関連

- HOMBA 正本: [`../rcs/HOMBA_v1_fixed.csv`](../rcs/HOMBA_v1_fixed.csv)
- top-1 整合性レビュー: [`../260711_playground/top1_consistency_review/`](../260711_playground/top1_consistency_review/)
