# ROSETTA Candidate Search

脳領域・解剖学的構造名から HOMBA オントロジーの候補をスコア付きで返す検索システム（RCS）。

**エンジン**: v0.8.0（2026-07-11）

## ライブ環境

| 項目 | URL |
|---|---|
| 検索 UI | https://rcs.mymt.site/ |
| CloudFront（代替） | https://d5keesfj4srwa.cloudfront.net/ |
| API | `POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| Reports（最新） | https://rcs.mymt.site/reports/2026-08-02/summary_report.html |

```bash
curl -sS -X POST "https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates" \
  -H "Content-Type: application/json" \
  -d '{"query":"Pulvinar nucleus","top_k":5}'
```

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [API 仕様](docs/api_specification.md) | エンドポイント、リクエスト/レスポンス |
| [アルゴリズム仕様](docs/rcs_algorithm.md) | 候補生成・スコアリング |
| [テスト・品質管理](docs/test_and_quality.md) | テスト方針、品質基準 |
| [AWS 運用ガイド](docs/aws_operations_guide.md) | デプロイ、運用 |

## 構成

```
rcs/              コアアルゴリズム（正本。Lambda もここを import）
homex/            HOMBA 細分拡張（HOMEX）。本体 CSV は変更しない
web/              フロントエンド + Lambda HTTP アダプター
scripts/          デプロイ・運用スクリプト（package_lambda, build_generator_cache 等）
build_testdata/   コーパス構築・評価データ
docs/             仕様書
```

### コアデータ（`rcs/`）

| ファイル | 役割 |
|---|---|
| `rosetta_candidate_generator.py` | 候補生成エンジン |
| `HOMBA_v1_fixed.csv` | HOMBA 本体 |
| `homba_token_rules.csv` | stopword / laterality / modifier 等 |
| `homba_alias_rules.csv` | HOMBA 側別名 |
| `homba_abbrev_rules.csv` | クエリ側略語展開 |

## HOMBA ontology（帰属・利用条件）

本リポジトリに含まれる HOMBA（Harmonized Ontology of Mammalian Brain Anatomy）関連データは Allen Institute の著作物です。利用・再配布は [Allen Institute Terms of Use](https://alleninstitute.org/legal/terms-of-use) に従い、**研究・その他非商用目的**に限ります。商用での再配布・組み込みには Allen Institute の書面による許可が必要です（`terms@alleninstitute.org`）。公開利用時は [Citation Policy](https://alleninstitute.org/legal/citation-policy) に従って出典を明示してください。

- 出典: [CCF-MAP — HOMBA ontology](https://alleninstitute.github.io/CCF-MAP/docs/HOMBA_ontology_v1.html)
- 本リポジトリの `rcs/HOMBA_v1_fixed.csv` は公式 CSV に対しタイポ修正等を加えた派生物です

## v0.8.0 の要点

- 階層の共通親昇格（`_promote_common_parents`）と 2-pass スコアリングを廃止
- 領域アンカー罰則・構造クラス整合・辞書拡充で親ヒット過多を抑制
- 公開レポート: nodir auto-improve、親昇格アブレーション、v1 validation

## ローカル実行

```bash
# 対話
python rcs/rcs_test_interactive.py

# リスト評価
python rcs/rcs_test_list.py
```

## デプロイ（要約）

詳細は [AWS 運用ガイド](docs/aws_operations_guide.md)。

```powershell
# Lambda
.\scripts\package_lambda.ps1
aws lambda update-function-code --function-name rcs-api --zip-file fileb://dist/lambda.zip --region ap-northeast-1

# フロント
aws s3 sync web/frontend/ s3://rcs-api-web/ --exclude ".DS_Store"
aws cloudfront create-invalidation --distribution-id E103PFXH9IO864 --paths "/*"
```
