# RCS_EBL（ローカル / 本番テスト）

文献上の領域名 → BNA（Brainnetome Atlas）候補を返すエンジン。現行 RCS（HOMBA）とは独立。
**SABRA における BNA 部分**（新皮質 210 ＋ 皮質下核 36）の解決に使う。DHBA 部分は RCS（HOMBA）が担う。
定義は [SABRA 定義](../docs/sabra.md)。

- 照合: `RosettaCandidateGenerator`（normalize / variants / exact / fuzzy / BM25）
- 展開: EBL `rcs_ready` の名称 → BNA 確率分布
- AI 前後処理はオフ
- 索引キャッシュ: `rcs_ebl/ebl_generator_cache.pkl`（`scripts/build_ebl_generator_cache.py`、git 管理外）。
  CSV からの構築は ~30 s かかるため Lambda では必須

## 公開 URL

- UI: https://rcs.cobrac.site/ebl/index.html
- API: `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl`
- MCP: `search_bna_candidates` ツール（`/mcp`、[運用ガイド 4-1b](../docs/aws_operations_guide.md#4-1b-mcp-サーバーrcs-mcp)）

## ローカル起動

```bash
python rcs_ebl/local_server.py
```

- UI: http://127.0.0.1:8787/
- API: `POST /candidates-ebl`（`/candidates` も可）

## 再デプロイ

通常は main へのマージで GitHub Actions が `rcs-ebl-api` を更新する（[運用ガイド 4-0](../docs/aws_operations_guide.md#4-0-通常のデプロイgithub-actions)）。以下は緊急時の手動手順。
Linux / macOS では `./scripts/package_lambda_ebl.sh` と `./scripts/deploy_lambda_code.sh rcs-ebl-api dist/lambda_ebl.zip` を使う。

```powershell
.\scripts\package_lambda_ebl.ps1
aws lambda update-function-code --function-name rcs-ebl-api --zip-file fileb://dist/lambda_ebl.zip --region ap-northeast-1 --profile rcs-org --query LastUpdateStatus --output text
aws s3 sync web/frontend/ s3://rcs-api-web-765959262011/ --exclude ".DS_Store" --profile rcs-org
aws cloudfront create-invalidation --distribution-id EQ1U5DPE1OAUA --paths "/*" --profile rcs-org
```

MCP（`rcs-mcp`）側の BNA ツールは `scripts/package_lambda.ps1` の zip に同梱される（rcs-ebl-api とは別デプロイ）。
