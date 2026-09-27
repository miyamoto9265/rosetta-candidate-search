# ROSETTA Candidate Search — AWS 運用ガイド

**バージョン**: v0.5.0  
**最終更新**: 2026-09-27

> **v0.5.0:** MCP サーバー `rcs-mcp`（`/mcp`）を追加。RCS_EBL 索引キャッシュを導入。SABRA 用語を採用（[SABRA 定義](sabra.md)）。

本ドキュメントは、**構築済みの RCS 本番環境**を AWS CLI で運用・更新する手順を記す。GUI 操作手順は対象外とする。

公開 URL は `https://rcs.cobrac.site/`（CloudFront `EQ1U5DPE1OAUA`）。DNS は個人アカウント Route 53（`cobrac.site` / `Z03061213087DIHGCR2EP`）、証明書・CloudFront は組織アカウント。

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
CloudFront (EQ1U5DPE1OAUA / rcs.cobrac.site)
  |  カスタムドメイン + ACM（us-east-1）
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

同じ API Gateway の他ルート:
  POST /candidates-ebl → Lambda rcs-ebl-api（RCS_EBL: 文献名 → BNA。ebl_generator_cache.pkl を優先ロード）
  ANY  /mcp            → Lambda rcs-mcp（MCP。rcs-api と同じ zip。RCS と RCS_EBL の両方を import）

MCP クライアント（cobrac-web の Codex エージェント等）
  | HTTPS POST /mcp  Authorization: Bearer <token>
  v
API Gateway → Lambda rcs-mcp
```

### 各サービスの役割

| サービス | 役割 |
|---|---|
| S3 `rcs-api-web-765959262011` | 静的フロントエンド。CloudFront 経由で公開 |
| CloudFront | HTTPS 配信（`rcs.cobrac.site`） |
| API Gateway HTTP API | `POST /candidates`・`POST /candidates-ebl`・`ANY /mcp` の HTTPS エンドポイント |
| Lambda `rcs-api` | 候補生成。デプロイ zip 内の `generator_cache.pkl` を優先ロード |
| Lambda `rcs-ebl-api` | RCS_EBL（BNA 候補。SABRA の BNA 部分）。別 zip（`package_lambda_ebl.ps1`） |
| S3 `rcs-api-data-765959262011` | CSV のフォールバック保管。Lambda IAM ロールから読み取り |
| Lambda `rcs-mcp` | リモート MCP サーバー（`ANY /mcp`）。`rcs-api` と同じ zip。HOMBA（RCS）と BNA（RCS_EBL）の検索＝SABRA 化の部品 |

---

## 2. 現行環境

| 項目 | 値 |
|---|---|
| 検索 UI | `https://rcs.cobrac.site/` |
| API エンドポイント | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| Lambda 関数名 | `rcs-api`（本番）、`rcs-mcp`（MCP）、`rcs-ebl-api`（EBL テスト） |
| MCP エンドポイント | `https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp`（Bearer 認証） |
| Lambda ランタイム | `python3.14` |
| EBL API エンドポイント | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl` |
| Lambda メモリ / タイムアウト | `rcs-api`: 512 MB / 60 s · `rcs-mcp`: 512 MB / 60 s · `rcs-ebl-api`: 1024 MB / 60 s |
| Lambda ハンドラ | `lambda_function.lambda_handler`（`rcs-mcp` のみ `mcp_function.lambda_handler`） |
| Lambda IAM ロール | `rcs-lambda-role` |
| API Gateway 名 / ID | `rcs-http-api` / `hg2se72l61` |
| API Gateway 統合タイムアウト | 30 s（`TimeoutInMillis: 30000`） |
| S3 データバケット | `rcs-api-data-765959262011` |
| S3 フロントエンドバケット | `rcs-api-web-765959262011` |
| CloudFront ディストリビューション ID | `EQ1U5DPE1OAUA` |
| CloudFront オリジン | `rcs-api-web-765959262011.s3.ap-northeast-1.amazonaws.com` |
| CloudFront OAC | `E1VWRRRFQZPIX6` |

DNS: 個人アカウント Route 53 `cobrac.site`（`Z03061213087DIHGCR2EP`）。ACM: 組織 `us-east-1`（`cobrac.site` / `*.cobrac.site`）。apex `cobrac.site` は cobrac-web（`E294RWWP0C7KRS`）向け。

### Lambda 環境変数（現状）

| キー | 値 | 備考 |
|---|---|---|
| `HOMBA_BUCKET` | `rcs-api-data-765959262011` | S3 フォールバック用 |
| `ALLOWED_ORIGIN` | `https://rcs.cobrac.site` | CORS |
| `DEEPSEEK_API_KEY` | （秘匿） | AI 統合用。未設定なら AI は自動 soft-fail（RCS のみ返却） |
| `AI_MODEL` | `deepseek-v4-flash` | preprocess / postprocess に使う LLM |
| `AI_HTTP_TIMEOUT_SEC` | `8` | LLM 呼出しごとのタイムアウト（API GW 30s 制約内） |
| `MCP_BEARER_SECRET_ID` | `rcs/mcp-bearer-token` | **`rcs-mcp` のみ**。受理する Bearer トークン（カンマ区切り）を持つ Secrets Manager シークレット。5 分ごとに再読込 |
| `MCP_BEARER_TOKENS` | （未設定） | **`rcs-mcp` のみ・任意**。追加で受理するトークン（ローカル試験用。本番では使わない） |

`rcs-mcp` は上記 `rcs-api` の変数をすべて複製して持つ（`DEEPSEEK_API_KEY` を更新したら両方に反映）。`rcs-ebl-api` は `ALLOWED_ORIGIN` のみ。

MCP トークンの正本は **Secrets Manager `rcs/mcp-bearer-token`**（`arn:aws:secretsmanager:ap-northeast-1:765959262011:secret:rcs/mcp-bearer-token-meaEcW`）。
`rcs-lambda-role` のインラインポリシー `read-rcs-mcp-secret` がこのシークレットの `GetSecretValue` のみを許可する。

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

`package_lambda` 実行時にキャッシュを自動生成する。Docker が利用可能なら `public.ecr.aws/lambda/python:3.14` でビルドし、Lambda ランタイムと Python バージョンを揃える（Docker なしのローカル Python 3.13 ビルドでも 3.14 で読み込めることを確認済み）。

### RCS_EBL 索引キャッシュ

RCS_EBL の照合器は CSV から構築すると約 30 s かかり API Gateway の 30 s 上限を超えるため、キャッシュを同梱する。
`lambda_function_ebl.py` は **`rcs_ebl/ebl_generator_cache.pkl`** → 失敗時 `ebl_data/*.csv` から構築、の順で初期化する。

| 項目 | 値 |
|---|---|
| 生成スクリプト | `scripts/build_ebl_generator_cache.py`（`package_lambda.*` / `package_lambda_ebl.ps1` が自動実行） |
| 出力先 | `rcs_ebl/ebl_generator_cache.pkl`（約 6 MB、git 管理外） |
| 実装 | `rcs_ebl/ebl_cache.py` |
| 検証キー | `rcs_ebl.ENGINE_VERSION` と `rcs` の `ENGINE_VERSION` |

EBL テーブル（`ebl_for_rcs_v1.0_20260722/rcs_ready/`）やルール CSV を変えたら、キャッシュ再生成 → `rcs-ebl-api` と `rcs-mcp` の両方を再デプロイする。

---

## 4. デプロイ手順

### 4-1. Lambda（バックエンド）を更新する

コアロジックは `rcs/` に1か所だけあり、Lambda には zip 同梱で import する。`web/backend/lambda_function.py` はキャッシュ/CSV 読込・HTTP・CORS の薄いアダプター。
`dist/lambda.zip` は **`rcs-api` と `rcs-mcp` の共通 zip**。`rcs/` や `web/backend/` を変えたら両方に反映する（下記）。

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
ai_pipeline.py
mcp_function.py          ← rcs-mcp のハンドラ
lambda_function_ebl.py   ← rcs-mcp の BNA ツールが import（rcs-ebl-api 本体は別 zip）
rcs_ebl/
  ebl_candidate_generator.py
  ebl_cache.py
  ebl_generator_cache.pkl  ← 事前構築索引（EBL）
ebl_data/
  bna_name_*.csv
rcs/
  sabra.py                 ← SABRA 定義
  rosetta_candidate_generator.py
  generator_cache.py
  generator_cache.pkl      ← 事前構築索引
  HOMBA_v1_fixed.csv
  homba_*_rules.csv
```

同じ zip を MCP サーバーにも反映する（ハンドラは `mcp_function.lambda_handler`）:

```powershell
aws lambda update-function-code `
  --function-name rcs-mcp `
  --zip-file fileb://dist/lambda.zip `
  --region ap-northeast-1 `
  --profile rcs-org
```

### 4-1b. MCP サーバー（`rcs-mcp`）

Streamable HTTP・ステートレスの MCP サーバー。cobrac-web の Codex エージェント等が利用する。
RCS（HOMBA → SABRA の DHBA 部分）と RCS_EBL（→ SABRA の BNA 部分）を 1 サーバーで提供する（[SABRA 定義](sabra.md)）。

| ツール | 処理 |
|---|---|
| `search_homba_candidates` | `POST /candidates` と同一処理（既定 `top_k=5`、`use_ai` で AI 一括 ON/OFF）＋ 各候補に `sabra` 注釈 |
| `search_bna_candidates` | `POST /candidates-ebl` と同一処理（UI 互換の HOMBA 形フィールドは除去）＋ `sabra` 注釈 |
| `get_homba_term` | HOMBA ID → 祖先・子・`sabra` 注釈 |
| `get_sabra_definition` | SABRA 定義（`rcs/sabra.py`） |

| 項目 | 値 |
|---|---|
| ルート | `rcs-http-api` の `ANY /mcp`（統合 `d09zupl`、タイムアウト 30 s） |
| 認証 | `Authorization: Bearer <token>`。受理トークンは Secrets Manager `rcs/mcp-bearer-token`（カンマ区切り、空なら全拒否） |
| 環境変数 | `rcs-api` と同じ（`DEEPSEEK_API_KEY` 等）＋ `MCP_BEARER_SECRET_ID` |
| 応答 | POST 1 メッセージ → `application/json` 1 件。通知は 202、GET/DELETE は 405 |

トークン確認:

```powershell
aws secretsmanager get-secret-value --secret-id rcs/mcp-bearer-token --query SecretString --output text --profile rcs-org
```

ローテーション（無停止）:

1. シークレットを `旧,新` に更新（`aws secretsmanager put-secret-value --secret-id rcs/mcp-bearer-token --secret-string "<旧>,<新>"`）
2. 最大 5 分で `rcs-mcp` が再読込。利用側（cobrac-web worker 等）を新トークンに切替
3. シークレットを `新` のみに更新

Lambda の再デプロイや環境変数の変更は不要。

Codex（`~/.codex/config.toml`）からの接続例:

```toml
[mcp_servers.rcs]
url = "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp"
bearer_token_env_var = "RCS_MCP_TOKEN"
```

### 4-1c. RCS_EBL（`rcs-ebl-api`）

```powershell
.\scripts\package_lambda_ebl.ps1
aws lambda update-function-code --function-name rcs-ebl-api --zip-file fileb://dist/lambda_ebl.zip --region ap-northeast-1 --profile rcs-org
```

`rcs-ebl-api` の zip は `lambda_function_ebl.py` を `lambda_function.py` として同梱する別構成。詳細は [rcs_ebl/README.md](../rcs_ebl/README.md)。

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

3. `package_lambda` → `rcs-api` と `rcs-mcp` を再デプロイ（**必須**。キャッシュ再生成込み）
4. `homba_*_rules.csv` を変えた場合は RCS_EBL も同じルールで照合するため、`package_lambda_ebl.ps1` → `rcs-ebl-api` も再デプロイ

---

## 5. 検証コマンド

### API（本番）

```bash
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates" \
  -H "Content-Type: application/json" \
  -d '{"query":"Pulvinar nucleus","top_k":5}'
```

`HOMBA:10409`（pulvinar of thalamus）、`score: 1.0` が返れば成功。

```bash
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl" \
  -H "Content-Type: application/json" \
  -d '{"query":"left DLPFC","top_k":3}'
```

`A8vl`（`bna_label_id: 23`）などが返れば成功。コールドスタートでも数秒以内（キャッシュ有効時）。

### MCP（本番）

```bash
TOKEN=$(aws secretsmanager get-secret-value --secret-id rcs/mcp-bearer-token --query SecretString --output text --profile rcs-org)
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_homba_candidates","arguments":{"query":"locus coeruleus","top_k":1,"use_ai":false}}}'
```

ツール 4 件が列挙され、`sabra.atlas: "DHBA"`（`nucleus coeruleus`）が返れば成功。トークンなしは 401。

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
| `scripts/package_lambda.ps1` / `.sh` | HOMBA・EBL キャッシュ生成 + `rcs-api` / `rcs-mcp` 共通 zip 作成 |
| `scripts/package_lambda_ebl.ps1` | EBL キャッシュ生成 + `rcs-ebl-api` 用 zip 作成 |
| `scripts/build_generator_cache.py` | `generator_cache.pkl` のみ再生成 |
| `scripts/build_ebl_generator_cache.py` | `rcs_ebl/ebl_generator_cache.pkl` のみ再生成 |
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

### MCP が 401 / ツールが見えない

- 401: `Authorization: Bearer` のトークンがシークレット `rcs/mcp-bearer-token` の値と一致しているか確認。
  シークレット更新直後は最大 5 分反映待ち。読込失敗時は CloudWatch に `Failed to read MCP bearer secret` が出る（`rcs-lambda-role` の `read-rcs-mcp-secret` ポリシーを確認）
- 405: GET（SSE）は非対応。クライアントは POST のみで動作する（Codex は対応済み）
- BNA ツールだけ失敗: zip に `rcs_ebl/ebl_generator_cache.pkl` と `ebl_data/` があるか確認（`package_lambda` で再ビルド）

### CloudWatch Logs

```bash
aws logs tail /aws/lambda/rcs-api --since 30m --format short --profile rcs-org
aws logs tail /aws/lambda/rcs-mcp --since 30m --format short --profile rcs-org
aws logs tail /aws/lambda/rcs-ebl-api --since 30m --format short --profile rcs-org
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
- MCP トークンはサーバー側（cobrac-web worker の環境変数等）にのみ置き、ブラウザに出さない。漏洩時は 4-1b の手順でローテーション

---

## 関連ドキュメント

| ドキュメント | 内容 |
|---|---|
| [API 仕様](api_specification.md) | リクエスト / レスポンス（REST・MCP） |
| [SABRA 定義](sabra.md) | BNA＋DHBA 混合アトラスの定義と境界 |
| [アルゴリズム仕様](rcs_algorithm.md) | 候補生成ロジック |
| [README](../README.md) | リポジトリ概要 |
