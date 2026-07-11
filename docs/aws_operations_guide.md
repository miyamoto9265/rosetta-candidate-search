# ROSETTA Candidate Search — AWS 運用ガイド

**バージョン**: v0.3.1  
**最終更新**: 2026-06-25

本ドキュメントは、**構築済みの RCS 本番環境**を AWS CLI で運用・更新する手順を記す。GUI 操作手順は対象外とする。

---

## 前提

| 項目 | 値 |
|---|---|
| AWS CLI | v2 以降 |
| デフォルトリージョン | `ap-northeast-1` |
| 作業ディレクトリ | リポジトリルート |
| アカウント ID | `618703232062` |

```bash
aws sts get-caller-identity
aws configure get region   # ap-northeast-1 であること
```

---

## 命名規則

| 対象 | プレフィックス | 例 |
|---|---|---|
| AWS リソース（S3 / Lambda / API Gateway / IAM） | `rcs-` | `rcs-api-data` |
| S3 内の CSV ファイル（HOMBA オントロジーデータ） | `homba_` / `HOMBA_` | `homba_abbrev_rules.csv` |

AWS リソース名は **ROSETTA Candidate Search (RCS)** に合わせて `rcs-` プレフィックスを使う。`homba` はオントロジー名であり、インフラの命名には使わない。

S3 バケット名はグローバルで一意である必要がある。`rcs-data` / `rcs-web` は他アカウントに取得済みのため、現行環境では `rcs-api-data` / `rcs-api-web` を使用している。

---

## 1. アーキテクチャ

```
利用者ブラウザ
  |
  | HTTPS（静的ファイル）
  v
CloudFront (E103PFXH9IO864)
  |  Alternate domain: rcs.mymt.site
  v
S3 rcs-api-web
  index.html, app.js, config.js, scoring-guide.html, ...

利用者ブラウザ
  |
  | HTTPS POST /candidates
  v
API Gateway HTTP API (rcs-http-api / zj7cl034xe)
  |  Integration timeout: 30 s
  v
Lambda rcs-api (Python 3.14, 512 MB, timeout 60 s)
  |
  | 1) generator_cache.pkl をデシリアライズ（通常・約 0.1 s）
  | 2) 失敗時: 同梱 CSV から索引構築
  | 3) それも不可: S3 rcs-api-data から CSV 取得して構築
  v
（フォールバック時のみ）S3 rcs-api-data
  HOMBA_v1_fixed.csv, homba_*_rules.csv
```

### 各サービスの役割

| サービス | 役割 |
|---|---|
| S3 `rcs-api-web` | 静的フロントエンド。CloudFront 経由で公開 |
| CloudFront | HTTPS 配信、`rcs.mymt.site` の TLS 終端 |
| Route 53 + ACM | カスタムドメイン DNS。ACM 証明書は **us-east-1** |
| API Gateway HTTP API | `POST /candidates` の HTTPS エンドポイント |
| Lambda `rcs-api` | 候補生成。デプロイ zip 内の `generator_cache.pkl` を優先ロード |
| S3 `rcs-api-data` | CSV のフォールバック保管。Lambda IAM ロールから読み取り |

---

## 2. 現行環境

| 項目 | 値 |
|---|---|
| 検索 UI（正規 URL） | `https://rcs.mymt.site/` |
| CloudFront URL | `https://d5keesfj4srwa.cloudfront.net/` |
| API エンドポイント | `POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| Lambda 関数名 | `rcs-api` |
| Lambda ランタイム | `python3.14` |
| Lambda メモリ / タイムアウト | 512 MB / 60 s |
| Lambda ハンドラ | `lambda_function.lambda_handler` |
| Lambda IAM ロール | `rcs-lambda-role` |
| API Gateway 名 / ID | `rcs-http-api` / `zj7cl034xe` |
| API Gateway 統合タイムアウト | 30 s（`TimeoutInMillis: 30000`） |
| S3 データバケット | `rcs-api-data` |
| S3 フロントエンドバケット | `rcs-api-web` |
| CloudFront ディストリビューション ID | `E103PFXH9IO864` |
| CloudFront オリジン | `rcs-api-web.s3.ap-northeast-1.amazonaws.com` |
| Route 53 ホストゾーン | `mymt.site`（`Z02353003AWQIVFUE50UY`） |
| ACM 証明書（us-east-1） | `arn:aws:acm:us-east-1:618703232062:certificate/f7cbc93e-59a2-4411-8272-14cb06378e8d` |

### Lambda 環境変数（現状）

| キー | 値 | 備考 |
|---|---|---|
| `HOMBA_BUCKET` | `rcs-api-data` | S3 フォールバック用 |
| `ALLOWED_ORIGIN` | `*` | 本番では `https://rcs.mymt.site` 推奨 |

未設定時のデフォルトキー名: `HOMBA_v1_fixed.csv`, `homba_token_rules.csv`, `homba_alias_rules.csv`, `homba_abbrev_rules.csv`

---

## 3. Lambda のデータ読み込み

`web/backend/lambda_function.py` は次の順でジェネレータを初期化する。

1. **`rcs/generator_cache.pkl`**（デプロイ zip 同梱）をデシリアライズ
2. 失敗時 → zip 内の **`rcs/*.csv`** から索引を構築
3. それも不可 → **`HOMBA_BUCKET`** の S3 オブジェクトから CSV を `/tmp` に取得して構築

通常運用では **1 のみ** が実行される。CSV を更新した場合は **必ずキャッシュを再生成して Lambda を再デプロイ** する。S3 だけ更新しても、キャッシュが有効な間は反映されない。

### 索引キャッシュ

| 項目 | 値 |
|---|---|
| 生成スクリプト | `scripts/build_generator_cache.py` |
| 出力先 | `rcs/generator_cache.pkl`（約 2 MB、git 管理外） |
| 実装 | `rcs/generator_cache.py` |
| エンジンバージョン | `ENGINE_VERSION`（`rcs/rosetta_candidate_generator.py` と一致必須） |

`package_lambda` 実行時にキャッシュを自動生成する。Docker が利用可能なら `public.ecr.aws/lambda/python:3.14` でビルドし、Lambda ランタイムと Python バージョンを揃える。

---

## 4. デプロイ手順

### 4-1. Lambda（バックエンド）を更新する

コアロジックは `rcs/` に1か所だけあり、Lambda には zip 同梱で import する。`web/backend/lambda_function.py` はキャッシュ/CSV 読込・HTTP・CORS の薄いアダプター。

```powershell
# Windows
.\scripts\package_lambda.ps1
aws lambda update-function-code `
  --function-name rcs-api `
  --zip-file fileb://dist/lambda.zip `
  --region ap-northeast-1
```

```bash
# macOS / Linux
./scripts/package_lambda.sh
aws lambda update-function-code \
  --function-name rcs-api \
  --zip-file fileb://dist/lambda.zip \
  --region ap-northeast-1
```

索引キャッシュだけ再生成する場合:

```bash
python scripts/build_generator_cache.py
```

zip の構成:

```
lambda_function.py
rcs/
  rosetta_candidate_generator.py
  generator_cache.py
  generator_cache.pkl      ← 事前構築索引
  HOMBA_v1_fixed.csv
  homba_*_rules.csv
```

### 4-2. フロントエンドを更新する

```bash
aws s3 sync web/frontend/ s3://rcs-api-web/ --exclude ".DS_Store"

aws cloudfront create-invalidation \
  --distribution-id E103PFXH9IO864 \
  --paths "/*"
```

主な公開ファイル:

| パス | 役割 |
|---|---|
| `index.html`, `app.js`, `styles.css`, `config.js` | 検索 UI |
| `about.html` | サイト説明 |
| `scoring-guide.html`, `walkthrough-bla.html` | スコアリング解説 |
| `site-nav.css`, `site-trust.css` | 共通スタイル |
| `robots.txt`, `sitemap.xml`, `humans.txt` | クローラ向け |
| `.well-known/security.txt` | セキュリティ連絡先 |

`web/frontend/config.js` の `apiBaseUrl` が API Gateway の Invoke URL を指していることを確認する。

### 4-3. CSV / 辞書データを更新する

**alias / abbrev / token ルール、HOMBA 本体のいずれも同じ手順:**

1. ローカルで `rcs/` 内の該当 CSV を編集
2. （推奨）S3 フォールバック用に同期:

```bash
aws s3 cp rcs/HOMBA_v1_fixed.csv s3://rcs-api-data/HOMBA_v1_fixed.csv
aws s3 cp rcs/homba_token_rules.csv s3://rcs-api-data/homba_token_rules.csv
aws s3 cp rcs/homba_alias_rules.csv s3://rcs-api-data/homba_alias_rules.csv
aws s3 cp rcs/homba_abbrev_rules.csv s3://rcs-api-data/homba_abbrev_rules.csv
```

3. `package_lambda` → Lambda 再デプロイ（**必須**。キャッシュ再生成込み）

---

## 5. 検証コマンド

### API（本番）

```bash
curl -sS -X POST "https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates" \
  -H "Content-Type: application/json" \
  -d '{"query":"Pulvinar nucleus","top_k":5}'
```

`HOMBA:10409`（pulvinar of thalamus）、`score: 1.0` が返れば成功。

### Lambda 直接呼び出し

API Gateway 形式のイベントが必要（`event["body"]` から JSON を読むため）:

```bash
aws lambda invoke \
  --function-name rcs-api \
  --cli-binary-format raw-in-base64-out \
  --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"query\":\"Pulvinar nucleus\",\"top_k\":5}"}' \
  /tmp/rcs-response.json

cat /tmp/rcs-response.json
```

### リソース状態の確認

```bash
aws lambda get-function-configuration --function-name rcs-api \
  --query "{Runtime:Runtime,Timeout:Timeout,MemorySize:MemorySize,LastModified:LastModified}"

aws s3 ls s3://rcs-api-data/
aws s3 ls s3://rcs-api-web/ --recursive --human-readable --summarize
```

---

## 6. リポジトリ内スクリプト

| スクリプト | 用途 |
|---|---|
| `scripts/package_lambda.ps1` / `.sh` | キャッシュ生成 + デプロイ zip 作成 |
| `scripts/build_generator_cache.py` | `generator_cache.pkl` のみ再生成 |
| `scripts/update_cloudfront_rcs.py` | CloudFront の Alternate domain / ACM 証明書を `rcs.mymt.site` に更新 |
| `scripts/route53_rcs_change.json` | Route 53 変更セット（DNS 移行時の参考） |

---

## 7. トラブルシューティング

### 初回検索が遅い / `Service Unavailable`（504）

| 原因 | 対処 |
|---|---|
| コールドスタートで CSV から索引構築（約 30 s） | `generator_cache.pkl` が zip に含まれているか確認し、再デプロイ |
| キャッシュ読み込み失敗（pickle エラー） | CloudWatch Logs `/aws/lambda/rcs-api` で `Generator cache` を確認。`package_lambda` でキャッシュ再生成 |
| API Gateway 30 s 上限超過 | 複雑クエリ（多バリアント展開）は Lambda 512 MB では 30 s を超える場合あり。メモリ増またはクエリ短縮を検討 |

### `{"error": "query is required"}`

Lambda 直接呼び出しで `{"query":"..."}` のみ渡した場合に発生する。`body` フィールドに JSON 文字列を入れた API Gateway 形式を使う（[5. 検証コマンド](#5-検証コマンド) 参照）。

### 403 Forbidden / S3 アクセスエラー

```bash
aws lambda get-function-configuration --function-name rcs-api --query Role
aws iam list-role-policies --role-name rcs-lambda-role
```

ロール `rcs-lambda-role` に `rcs-api-data` の `s3:GetObject` / `s3:ListBucket` があること、`HOMBA_BUCKET` が `s3://` なしで `rcs-api-data` であることを確認する。

### `NoSuchKey` / 500 エラー

S3 フォールバック経路で CSV が欠けている。`aws s3 ls s3://rcs-api-data/` で4ファイルの存在を確認する。

### データ更新が反映されない

zip 内の `generator_cache.pkl` が古い。CSV 更新後に `package_lambda` → Lambda 再デプロイを実行する。環境変数の保存し直しだけでは索引は更新されない。

### CloudWatch Logs

```bash
aws logs tail /aws/lambda/rcs-api --since 30m --format short
```

---

## 8. 制限事項

| 制限 | 値 | 影響 |
|---|---|---|
| API Gateway 統合タイムアウト | 30 s | クライアントが受け取れる最大応答時間 |
| Lambda タイムアウト | 60 s | API Gateway より長く設定されていても、30 s で 504 になる |
| Lambda メモリ | 512 MB | CPU 割当も連動。重いクエリはメモリ増で改善する可能性あり |

---

## 9. DNS / CloudFront（参考）

カスタムドメイン `rcs.mymt.site` は Route 53 の A/AAAA エイリアスで CloudFront `d5keesfj4srwa.cloudfront.net` を指す。CloudFront の TLS 証明書は us-east-1 の ACM を使用する。

CloudFront 設定変更の例（`scripts/update_cloudfront_rcs.py` と同等）:

```bash
python scripts/update_cloudfront_rcs.py
```

Route 53 レコード変更:

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id Z02353003AWQIVFUE50UY \
  --change-batch file://scripts/route53_rcs_change.json
```

---

## 10. セキュリティ上の推奨

- `ALLOWED_ORIGIN` を `https://rcs.mymt.site` に限定する
- S3 バケットはパブリックアクセスブロックを維持する（CloudFront OAC 経由のみ配信）
- 追加のアクセス制限が必要な場合は CloudFront Functions または Cognito を検討する

---

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [API 仕様](api_specification.md) | リクエスト / レスポンス |
| [アルゴリズム仕様](rcs_algorithm.md) | 候補生成ロジック |
| [README](../README.md) | リポジトリ概要 |
