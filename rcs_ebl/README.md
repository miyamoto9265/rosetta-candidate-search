# RCS_EBL（ローカル / 本番テスト）

現行 RCS（HOMBA）とは独立したテスト版です。

- 照合: `RosettaCandidateGenerator`（normalize / variants / exact / fuzzy / BM25）
- 展開: EBL `rcs_ready` の名称 → BNA 確率分布
- AI 前後処理はオフ

## 公開 URL

- UI: https://rcs.mymt.site/ebl/index.html
- API: `POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl`

## ローカル起動

```bash
python rcs_ebl/local_server.py
```

- UI: http://127.0.0.1:8787/
- API: `POST /candidates-ebl`（`/candidates` も可）

## 再デプロイ

```powershell
.\scripts\package_lambda_ebl.ps1
aws lambda update-function-code --function-name rcs-ebl-api --zip-file fileb://dist/lambda_ebl.zip --region ap-northeast-1
aws s3 sync web/frontend/ s3://rcs-api-web/ --exclude ".DS_Store"
aws cloudfront create-invalidation --distribution-id E103PFXH9IO864 --paths "/*"
```
