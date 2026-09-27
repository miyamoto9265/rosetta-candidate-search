# ROSETTA Candidate Search

脳領域・解剖学的構造名から HOMBA オントロジーの候補をスコア付きで返す検索システム（RCS）。
API v0.9.0 から AI 統合（preprocess: クエリ清掃 / postprocess: 候補裁定＋関係ラベル）がデフォルト有効。

**エンジン**: v0.8.5 · **API**: v0.9.0（2026-08-12）

## ライブ環境

| 項目 | URL |
|---|---|
| 検索 UI | https://rcs.cobrac.site/ |
| API | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| RCS_EBL API（BNA） | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl`（UI: https://rcs.cobrac.site/ebl/index.html） |
| MCP（Bearer 認証） | `https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp`（[運用ガイド 4-1b](docs/aws_operations_guide.md#4-1b-mcp-サーバーrcs-mcp)） |
| Reports（最新） | https://rcs.cobrac.site/reports/2026-08-12.html |

AWS アカウント `765959262011`（CLI プロファイル `rcs-org`）。公開 UI は `rcs.cobrac.site`。

```bash
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates" \
  -H "Content-Type: application/json" \
  -d '{"query":"right NAc Drd1 neurons","top_k":10}'
# AI を切る場合: "use_ai_preprocess":false, "use_ai_postprocess":false
```

## SABRA との関係

組織内の標準領域名 **SABRA**（Standardized Ontology of Anatomies for Brain Reference Architecture）は
**BNA 246 ラベル（新皮質 210 ＋ 皮質下核 36: 扁桃体・海馬・大脳基底核・視床）＋ それ以外は DHBA** の混合アトラス。
DHBA は HOMBA の一部（`DHBA_name` を持つ項）。本リポジトリでは **RCS（HOMBA）が DHBA 部分**、**RCS_EBL が BNA 部分**を担い、
MCP サーバーが両方を提供する。定義・境界・手順は [SABRA 定義](docs/sabra.md)（コード上の正本は `rcs/sabra.py`）。

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [SABRA 定義](docs/sabra.md) | SABRA（BNA＋DHBA 混合アトラス）の定義、HOMBA 上の境界、SABRA 化手順 |
| [API 仕様](docs/api_specification.md) | エンドポイント、リクエスト/レスポンス |
| [AI 統合仕様](docs/ai_integration_spec.md) | preprocess / postprocess の LLM 仕様・プロンプト |
| [アルゴリズム仕様](docs/rcs_algorithm.md) | 候補生成・スコアリング |
| [テスト・品質管理](archive/test_and_quality.md) | テスト方針、品質基準（アーカイブ済み・参考） |
| [AWS 運用ガイド](docs/aws_operations_guide.md) | デプロイ、運用 |

## 構成

```
rcs/              コアアルゴリズム（正本。Lambda もここを import）。SABRA 定義 rcs/sabra.py
rcs_ebl/          RCS_EBL（文献名 → BNA）。SABRA の BNA 部分
homex/            HOMBA 細分拡張（HOMEX）。本体 CSV は変更しない
web/              フロントエンド + Lambda HTTP アダプター
scripts/          デプロイ・運用スクリプト（package_lambda, build_generator_cache, build_ebl_generator_cache 等）
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

## 2026-09-27 の追加（MCP・SABRA）

- MCP サーバー `/mcp`（Lambda `rcs-mcp`）: `search_homba_candidates` / `search_bna_candidates` / `get_homba_term` / `get_sabra_definition`
- HOMBA 候補に `sabra` 注釈（SABRA で BNA / DHBA のどちらで表すか）。定義は `rcs/sabra.py` と [SABRA 定義](docs/sabra.md)
- RCS_EBL に索引キャッシュ（`rcs_ebl/ebl_generator_cache.pkl`）を導入し、コールドスタートを約 30 s → 数秒に短縮
- `/candidates`・`/candidates-ebl` の入出力は変更なし

## v0.9.0 の要点（API）

- AI 統合: preprocess（laterality・遺伝子・細胞型などの除去）→ RCS → postprocess（候補 0–4 件＋関係ラベル `'=`/`<`/`>`）
- `use_ai_preprocess` / `use_ai_postprocess`（いずれも既定 ON）、`context`（自由記述の判断材料）
- `candidates` は常に RCS 生ランキング。AI は soft-fail（失敗時も検索は成功）
- 評価: [AI on/off 比較レポート](https://rcs.cobrac.site/reports/2026-08-12/ai_eval_report.html)

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

**通常は PR を main にマージすると GitHub Actions（`.github/workflows/deploy.yml`、OIDC）が変更箇所に応じて Lambda 3 本・CSV・フロントをデプロイし、スモークテストを実行する**（[運用ガイド 4-0](docs/aws_operations_guide.md#4-0-通常のデプロイgithub-actions)）。PR では `ci`（AWS 認証なしのビルドとオフライン検査）が走る。
以下の手動手順は緊急時用。手動でデプロイしたら同じ内容を PR で main に戻す。

```bash
# macOS / Linux
./scripts/package_lambda.sh && ./scripts/package_lambda_ebl.sh
export AWS_PROFILE=rcs-org AWS_REGION=ap-northeast-1
./scripts/deploy_lambda_code.sh rcs-api dist/lambda.zip
./scripts/deploy_lambda_code.sh rcs-mcp dist/lambda.zip
./scripts/deploy_lambda_code.sh rcs-ebl-api dist/lambda_ebl.zip
./scripts/smoke_test.sh
```

```powershell
# Lambda（rcs-api と rcs-mcp は共通 zip）
.\scripts\package_lambda.ps1
aws lambda update-function-code --function-name rcs-api --zip-file fileb://dist/lambda.zip --region ap-northeast-1 --profile rcs-org --query LastUpdateStatus --output text
aws lambda update-function-code --function-name rcs-mcp --zip-file fileb://dist/lambda.zip --region ap-northeast-1 --profile rcs-org --query LastUpdateStatus --output text

# RCS_EBL
.\scripts\package_lambda_ebl.ps1
aws lambda update-function-code --function-name rcs-ebl-api --zip-file fileb://dist/lambda_ebl.zip --region ap-northeast-1 --profile rcs-org --query LastUpdateStatus --output text

# フロント
aws s3 sync web/frontend/ s3://rcs-api-web-765959262011/ --exclude ".DS_Store" --profile rcs-org
aws cloudfront create-invalidation --distribution-id EQ1U5DPE1OAUA --paths "/*" --profile rcs-org
```
