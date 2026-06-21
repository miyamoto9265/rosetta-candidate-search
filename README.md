# ROSETTA Candidate Search

脳領域・解剖学的構造名から HOMBA オントロジーの候補をスコア付きで返す検索システム（RCS）。

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
web/              フロントエンド + Lambda HTTP アダプター
scripts/          package_lambda.ps1 / .sh（デプロイ zip 作成）
build_testdata/   コーパス構築・評価データ
docs/             仕様書
```

## ライブ環境

- **検索 UI**: https://d5keesfj4srwa.cloudfront.net/
- **API**: `POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates`
