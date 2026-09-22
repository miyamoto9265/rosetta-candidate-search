# RCS_EBL（ローカル / 本番テスト）

現行 RCS（HOMBA）とは独立したテスト版です。

- 照合: `RosettaCandidateGenerator`（normalize / variants / exact / fuzzy / BM25）
- 展開: EBL `rcs_ready` の名称 → BNA 確率分布
- AI 前後処理はオフ

## 公開 URL

- UI: https://d1kpmm576ika4i.cloudfront.net/ebl/index.html
- API: `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl`

## ローカル起動

```bash
python rcs_ebl/local_server.py
```

- UI: http://127.0.0.1:8787/
- API: `POST /candidates-ebl`（`/candidates` も可）

## 再デプロイ

```powershell
.\scripts\package_lambda_ebl.ps1
aws lambda update-function-code --function-name rcs-ebl-api --zip-file fileb://dist/lambda_ebl.zip --region ap-northeast-1 --profile rcs-org
aws s3 sync web/frontend/ s3://rcs-api-web-765959262011/ --exclude ".DS_Store" --profile rcs-org
aws cloudfront create-invalidation --distribution-id EQ1U5DPE1OAUA --paths "/*" --profile rcs-org
```
