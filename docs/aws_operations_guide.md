# ROSETTA Candidate Search — AWS 運用ガイド

**バージョン**: v0.4.0  
**最終更新**: 2026-09-23

本ドキュメントは、**構築済みの RCS 本番環境**を AWS CLI で運用・更新する手順を記す。GUI 操作手順は対象外とする。

独自ドメイン（`rcs.mymt.site`）は使わない。公開 URL は CloudFront のデフォルトドメインのみ。

---

## 前提

| 項目 | 値 |
|---|---|
| AWS CLI | v2 以降（`aws login` 利用時は 2.32.0 以降） |
| CLI プロファイル | `rcs-org`（組織アカウント） |
| デフォルトリージョン | `ap-northeast-1` |
| 作業ディレクトリ | リポジトリルート |
| アカウント ID | `765959262011` |
| IAM ユーザー | `miyamoto` |

```bash
aws login --profile rcs-org
aws sts get-caller-identity --profile rcs-org
aws configure get region --profile rcs-org   # ap-northeast-1
```

以降のコマンド例は `--profile rcs-org` を省略している場合がある。未設定なら付与するか、`AWS_PROFILE=rcs-org` を使う。

---

## 命名規則

| 対象 | プレフィックス | 例 |
|---|---|---|
| AWS リソース（S3 / Lambda / API Gateway / IAM） | `rcs-` | `rcs-api-data-765959262011` |
| S3 内の CSV ファイル（HOMBA オントロジーデータ） | `homba_` / `HOMBA_` | `homba_abbrev_rules.csv` |

S3 バケット名はグローバルで一意である必要がある。個人アカウント時代の `rcs-api-data` / `rcs-api-web` は他で使用中のため、組織アカウントではアカウント ID サフィックス付きを使う。

---

## 1. アーキテクチャ

```
利用者ブラウザ
  |
  | HTTPS（静的ファイル）
  v
CloudFront (EQ1U5DPE1OAUA / d1kpmm576ika4i.cloudfront.net)
  |  独自ドメインなし（CloudFront デフォルト証明書）
  v
S3 rcs-api-web-765959262011
  index.html, app.js, config.js, scoring-guide.html, ...

利用者ブラウザ
  |
  | HTTPS POST /candidates
  v
API Gateway HTTP API (rcs-http-api / hg2se72l61)
  |  Integration timeout: 30 s
  v
Lambda rcs-api (Python 3.14, 512 MB, timeout 60 s)
  |
  | 1) generator_cache.pkl をデシリアライズ（通常・約 0.1 s）
  | 2) 失敗時: 同梱 CSV から索引構築
  | 3) それも不可: S3 rcs-api-data-765959262011 から CSV 取得して構築
  v
（フォールバック時のみ）S3 rcs-api-data-765959262011
  HOMBA_v1_fixed.csv, homba_*_rules.csv
```

### 各サービスの役割

| サービス | 役割 |
|---|---|
| S3 `rcs-api-web-765959262011` | 静的フロントエンド。CloudFront 経由で公開 |
| CloudFront | HTTPS 配信（デフォルト `*.cloudfront.net`） |
| API Gateway HTTP API | `POST /candidates` の HTTPS エンドポイント |
| Lambda `rcs-api` | 候補生成。デプロイ zip 内の `generator_cache.pkl` を優先ロード |
| S3 `rcs-api-data-765959262011` | CSV のフォールバック保管。Lambda IAM ロールから読み取り |

---

## 2. 現行環境

| 項目 | 値 |
|---|---|
| 検索 UI | `https://d1kpmm576ika4i.cloudfront.net/` |
| API エンドポイント | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| Lambda 関数名 | `rcs-api`（本番）、`rcs-ebl-api`（EBL テスト） |
| Lambda ランタイム | `python3.14` |
| Lambda メモリ / タイムアウト | `rcs-api`: 512 MB / 60 s · `rcs-ebl-api`: 1024 MB / 60 s |
| Lambda ハンドラ | `lambda_function.lambda_handler` |
| Lambda IAM ロール | `rcs-lambda-role` |
| API Gateway 名 / ID | `rcs-http-api` / `hg2se72l61` |
| API Gateway 統合タイムアウト | 30 s（`TimeoutInMillis: 30000`） |
| S3 データバケット | `rcs-api-data-765959262011` |
| S3 フロントエンドバケット | `rcs-api-web-765959262011` |
| CloudFront ディストリビューション ID | `EQ1U5DPE1OAUA` |
| CloudFront オリジン | `rcs-api-web-765959262011.s3.ap-northeast-1.amazonaws.com` |
| CloudFront OAC | `E1VWRRRFQZPIX6` |

独自ドメイン・Route 53・ACM（カスタム証明書）は使用しない。

### Lambda 環境変数（現状）

| キー | 値 | 備考 |
|---|---|---|
| `HOMBA_BUCKET` | `rcs-api-data-765959262011` | S3 フォールバック用 |
| `ALLOWED_ORIGIN` | `https://d1kpmm576ika4i.cloudfront.net` | CORS |
| `DEEPSEEK_API_KEY` | （秘匿） | AI 統合用。未設定なら AI は自動 soft-fail（RCS のみ返却） |
| `AI_MODEL` | `deepseek-v4-flash` | preprocess / postprocess に使う LLM |
| `AI_HTTP_TIMEOUT_SEC` | `8` | LLM 呼出しごとのタイムアウト（API GW 30s 制約内） |

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
  --region ap-northeast-1 `
  --profile rcs-org
```

```bash
# macOS / Linux
./scripts/package_lambda.sh
aws lambda update-function-code \
  --function-name rcs-api \
  --zip-file fileb://dist/lambda.zip \
  --region ap-northeast-1 \
  --profile rcs-org
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
aws s3 sync web/frontend/ s3://rcs-api-web-765959262011/ --exclude ".DS_Store" --profile rcs-org

aws cloudfront create-invalidation \
  --distribution-id EQ1U5DPE1OAUA \
  --paths "/*" \
  --profile rcs-org
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
aws s3 cp rcs/HOMBA_v1_fixed.csv s3://rcs-api-data-765959262011/HOMBA_v1_fixed.csv --profile rcs-org
aws s3 cp rcs/homba_token_rules.csv s3://rcs-api-data-765959262011/homba_token_rules.csv --profile rcs-org
aws s3 cp rcs/homba_alias_rules.csv s3://rcs-api-data-765959262011/homba_alias_rules.csv --profile rcs-org
aws s3 cp rcs/homba_abbrev_rules.csv s3://rcs-api-data-765959262011/homba_abbrev_rules.csv --profile rcs-org
```

3. `package_lambda` → Lambda 再デプロイ（**必須**。キャッシュ再生成込み）

---

## 5. 検証コマンド

### API（本番）

```bash
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates" \
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
  --profile rcs-org \
  /tmp/rcs-response.json

cat /tmp/rcs-response.json
```

### リソース状態の確認

```bash
aws lambda get-function-configuration --function-name rcs-api --profile rcs-org \
  --query "{Runtime:Runtime,Timeout:Timeout,MemorySize:MemorySize,LastModified:LastModified}"

aws s3 ls s3://rcs-api-data-765959262011/ --profile rcs-org
aws s3 ls s3://rcs-api-web-765959262011/ --recursive --human-readable --summarize --profile rcs-org
```

---

## 6. リポジトリ内スクリプト

| スクリプト | 用途 |
|---|---|
| `scripts/package_lambda.ps1` / `.sh` | キャッシュ生成 + デプロイ zip 作成 |
| `scripts/package_lambda_ebl.ps1` | EBL 用 Lambda zip 作成 |
| `scripts/build_generator_cache.py` | `generator_cache.pkl` のみ再生成 |
| `scripts/update_cloudfront_rcs.py` | **廃止**（独自ドメイン設定用。使わない） |
| `scripts/route53_rcs_change.json` | **廃止**（DNS 移行参考。使わない） |

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
aws lambda get-function-configuration --function-name rcs-api --query Role --profile rcs-org
aws iam list-role-policies --role-name rcs-lambda-role --profile rcs-org
```

ロール `rcs-lambda-role` に `rcs-api-data-765959262011` の `s3:GetObject` / `s3:ListBucket` があること、`HOMBA_BUCKET` が `s3://` なしで `rcs-api-data-765959262011` であることを確認する。

### `NoSuchKey` / 500 エラー

S3 フォールバック経路で CSV が欠けている。`aws s3 ls s3://rcs-api-data-765959262011/ --profile rcs-org` で4ファイルの存在を確認する。

### データ更新が反映されない

zip 内の `generator_cache.pkl` が古い。CSV 更新後に `package_lambda` → Lambda 再デプロイを実行する。環境変数の保存し直しだけでは索引は更新されない。

### CloudWatch Logs

```bash
aws logs tail /aws/lambda/rcs-api --since 30m --format short --profile rcs-org
```

---

## 8. 制限事項

| 制限 | 値 | 影響 |
|---|---|---|
| API Gateway 統合タイムアウト | 30 s | クライアントが受け取れる最大応答時間 |
| Lambda タイムアウト | 60 s | API Gateway より長く設定されていても、30 s で 504 になる |
| Lambda メモリ | 512 MB（`rcs-api`） | CPU 割当も連動。重いクエリはメモリ増で改善する可能性あり |

---

## 9. セキュリティ上の推奨

- `ALLOWED_ORIGIN` を CloudFront URL に限定する（現行どおり）
- S3 バケットはパブリックアクセスブロックを維持する（CloudFront OAC 経由のみ配信）
- 追加のアクセス制限が必要な場合は CloudFront Functions または Cognito を検討する

---

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [API 仕様](api_specification.md) | リクエスト / レスポンス |
| [アルゴリズム仕様](rcs_algorithm.md) | 候補生成ロジック |
| [README](../README.md) | リポジトリ概要 |
