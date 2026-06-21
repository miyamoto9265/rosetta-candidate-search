# ROSETTA Candidate Search — AWS 運用ガイド

**バージョン**: v0.3.0  
**最終更新**: 2026-06-16

---

## 命名規則

| 対象 | プレフィックス | 例 |
|---|---|---|
| AWS リソース（S3 / Lambda / API Gateway / IAM） | `rcs-` | `rcs-api-data` |
| S3 内の CSV ファイル（HOMBA オントロジーデータ） | `homba_` / `HOMBA_` | `homba_abbrev_rules.csv` |

AWS リソース名は **ROSETTA Candidate Search (RCS)** に合わせて `rcs-` プレフィックスを使う。`homba` はオントロジー名であり、インフラの命名には使わない。

S3 バケット名はグローバルで一意である必要がある。`rcs-data` / `rcs-web` は他アカウントに取得済みのため、現行環境では `rcs-api-data` / `rcs-api-web` を使用している。

---

## 1. AWS 構成

```
利用者ブラウザ
  |
  | HTTPS（静的ファイル配信）
  v
CloudFront  →  S3 frontend bucket（index.html / app.js / styles.css / config.js）

利用者ブラウザ
  |
  | HTTPS POST /candidates
  v
API Gateway HTTP API
  |
  v
Lambda（rcs-api）
  |
  | 初回起動時に CSV を取得・キャッシュ
  v
S3 data bucket
  - HOMBA_v1_fixed.csv
  - homba_token_rules.csv
  - homba_alias_rules.csv
  - homba_abbrev_rules.csv
```

### 各サービスの役割

| サービス | 役割 |
|---|---|
| S3 data bucket | HOMBA データ（CSV 4ファイル）を保存。Lambda だけが読み取る |
| Lambda | RCS ロジックを実行。初回起動時に S3 から CSV を読み込みメモリキャッシュ |
| API Gateway HTTP API | ブラウザから Lambda を呼び出す HTTPS エンドポイント（`POST /candidates`） |
| S3 frontend bucket | 静的フロントエンド（4ファイル）を保存 |
| CloudFront | フロントエンドを HTTPS 配信。独自ドメイン対応 |
| Route 53 + ACM | 独自ドメインを使う場合のみ必要 |

### 費用感

小規模利用なら月額費用はほぼ無料枠内。主なコスト:
- S3: 数円〜数十円程度
- Lambda・API Gateway: 少量アクセスなら無料枠内
- CloudFront: 少量アクセスなら低額
- Route 53 hosted zone: 月額固定費（独自ドメインを使う場合のみ）

---

## 2. 現行環境

| 項目 | 値 |
|---|---|
| API エンドポイント | `https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| フロントエンド URL | `https://d5keesfj4srwa.cloudfront.net/` |
| Lambda 関数名 | `rcs-api` |
| API Gateway 名 | `rcs-http-api` |
| S3 データバケット | `rcs-api-data` |
| S3 フロントエンドバケット | `rcs-api-web` |
| IAM ロール | `rcs-lambda-role` |
| CloudFront ディストリビューション | `E103PFXH9IO864`（`d5keesfj4srwa.cloudfront.net`） |
| Lambda リージョン | `ap-northeast-1` |

---

## 3. 初期セットアップ（GUI ベース）

### 3-1. S3 データバケットを作成する

1. AWS コンソールで `S3` を開く
2. `バケットを作成` を押す
3. バケット名を入力する（例: `rcs-api-data`）
4. リージョンは Lambda と同じにする（`ap-northeast-1` 推奨）
5. `パブリックアクセスをすべてブロック` はオンのままでよい
6. 作成後、以下の **4 ファイル** をアップロードする:
   - `HOMBA_v1_fixed.csv`
   - `homba_token_rules.csv`
   - `homba_alias_rules.csv`
   - `homba_abbrev_rules.csv`

### 3-2. Lambda 用 IAM ロールを作成する

1. AWS コンソールで `IAM` → `ロール` → `ロールを作成`
2. 信頼エンティティ: `AWSのサービス` → `Lambda`
3. 権限ポリシー: `AWSLambdaBasicExecutionRole` を選択
4. ロール名を入力（例: `rcs-lambda-role`）
5. 作成後、ロールを開いて `インラインポリシーを作成` → JSON で以下を設定（`YOUR_DATA_BUCKET_NAME` を置き換える）:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::YOUR_DATA_BUCKET_NAME",
        "arn:aws:s3:::YOUR_DATA_BUCKET_NAME/*"
      ]
    }
  ]
}
```

### 3-3. Lambda 関数を作成する

1. AWS コンソールで `Lambda` → `関数の作成`
2. `一から作成` を選ぶ
3. 関数名: `rcs-api`
4. ランタイム: `Python 3.12`
5. 実行ロール: 上記で作成したロールを指定
6. `コード` タブで `lambda_function.py` の中身を `web/backend/lambda_function.py` の内容で全置換 → `Deploy`

### 3-4. Lambda 環境変数を設定する

`設定` → `環境変数` → `編集` で以下を追加:

| キー | 値の例 | 備考 |
|---|---|---|
| `HOMBA_BUCKET` | `rcs-api-data` | **必須** |
| `HOMBA_KEY` | `HOMBA_v1_fixed.csv` | 任意。未設定ならこの値 |
| `TOKEN_RULES_KEY` | `homba_token_rules.csv` | 任意。未設定ならこの値 |
| `ALIAS_RULES_KEY` | `homba_alias_rules.csv` | 任意。未設定ならこの値 |
| `ABBREV_RULES_KEY` | `homba_abbrev_rules.csv` | 任意。未設定ならこの値 |
| `ALLOWED_ORIGIN` | `https://d5keesfj4srwa.cloudfront.net` | 推奨。`*` でも可 |

### 3-5. Lambda のメモリとタイムアウトを設定する

`設定` → `一般設定` → `編集`:
- メモリ: `512 MB`
- タイムアウト: `30秒`

### 3-6. Lambda をテストする

`テスト` タブで以下のイベント JSON を使う（API Gateway 形式のラッパーが必要）:

```json
{
  "requestContext": {
    "http": {
      "method": "POST"
    }
  },
  "body": "{\"query\":\"Pulvinar nucleus\",\"top_k\":5}"
}
```

`HOMBA:10409`（pulvinar of thalamus）、`score: 1.0` が返れば成功。

### 3-7. API Gateway HTTP API を作成する

1. AWS コンソールで `API Gateway` → `APIを作成` → `HTTP API`
2. 統合: `Lambda` → `rcs-api`
3. API 名: `rcs-http-api`
4. ルート: `POST /candidates`
5. ステージ: `$default`
6. 作成後に表示される `Invoke URL` を控える

### 3-8. CORS を設定する

API Gateway の `CORS` を開き以下を設定:
- Access-Control-Allow-Origin: `*`（公開後は CloudFront の URL に絞る）
- Access-Control-Allow-Headers: `content-type`
- Access-Control-Allow-Methods: `POST, OPTIONS`

### 3-9. フロントエンドの API URL を設定する

`web/frontend/config.js` の `apiBaseUrl` を API Gateway の Invoke URL に設定:

```js
window.ROSETTA_SEARCH_CONFIG = {
  apiBaseUrl: "https://abc123.execute-api.ap-northeast-1.amazonaws.com",
};
```

### 3-10. S3 フロントエンドバケットを作成し CloudFront で配信する

1. S3 で新バケット作成（例: `rcs-api-web`）
2. `web/frontend/` の 4 ファイルをアップロード
3. CloudFront でディストリビューション作成 → Origin に S3 フロントエンドバケットを指定
4. Origin access control (OAC) を作成・設定
5. Default root object: `index.html`
6. 生成されたバケットポリシーを S3 バケットに貼り付ける

---

## 4. データファイルの更新手順

### 4-1. alias/abbrev 辞書を更新する（最も頻繁）

辞書ファイルを更新しても Lambda コードの変更は不要。

1. ローカルで `rcs/homba_alias_rules.csv` または `rcs/homba_abbrev_rules.csv` を編集
2. S3 データバケットの該当ファイルを上書きアップロード
3. Lambda の実行環境キャッシュを更新するため、環境変数を一度保存し直す（任意の変数を追加・変更でよい）

### 4-2. Lambda コードを更新する

コアロジックは `rcs/` に1か所だけあり、Lambda には zip 同梱で import する。`web/backend/lambda_function.py` は S3 読込・HTTP・CORS の薄いアダプター。

**方法 1: zip アップロード（推奨）**

```powershell
# Windows（repo ルートから）
.\scripts\package_lambda.ps1
aws lambda update-function-code --function-name rcs-api --zip-file fileb://dist/lambda.zip --region ap-northeast-1
```

```bash
# macOS / Linux
./scripts/package_lambda.sh
aws lambda update-function-code --function-name rcs-api --zip-file fileb://dist/lambda.zip --region ap-northeast-1
```

zip の構成:

```
lambda_function.py      ← web/backend/ からコピー
rcs/                    ← エンジン本体 + CSV（テスト CLI は除外）
```

**方法 2: コンソールで直接貼り替え（非推奨）**

`rcs/` を同梱しないと動作しないため、通常は zip デプロイを使う。

### 4-3. HOMBA データ（`HOMBA_v1_fixed.csv`）を更新する

1. S3 データバケットの `HOMBA_v1_fixed.csv` を置き換える
2. Lambda のキャッシュを確実に更新したい場合は、環境変数 `DATA_VERSION` 等に任意の値を設定して保存する

### 4-4. フロントエンドを更新する

1. S3 フロントエンドバケットに `web/frontend/` のファイルを再アップロード
2. CloudFront でキャッシュ削除:
   - CloudFront ディストリビューション → `Invalidations` → `Create invalidation`
   - パスに `/*` を入力

---

## 5. トラブルシューティング

### `{"error": "query is required"}` が返る

Lambda コンソールのテスト GUI で `{"query": "LC"}` のように直接入力した場合に発生する。Lambda は `event["body"]` からペイロードを読むため、以下の形式が必要:

```json
{
  "requestContext": {"http": {"method": "POST"}},
  "body": "{\"query\": \"LC\", \"top_k\": 1}"
}
```

API Gateway 経由での呼び出し（curl/Python）では通常のリクエストボディで問題ない。

### 403 Forbidden が出る

Lambda の IAM ロールが S3 を読めていない。確認事項:

1. Lambda の `設定` → `アクセス権限` でロール名を確認
2. そのロールに S3 読み取りポリシーが付いているか確認
3. ポリシーの `Resource` にバケット本体とオブジェクト `/*` の両方があるか確認
4. S3 バケット名が環境変数 `HOMBA_BUCKET` と一致しているか確認（`s3://` は付けない）

### `NoSuchKey` や 500 エラーが出る

S3 に CSV ファイルが存在しない、またはキー名が環境変数と一致していない。

- S3 バケットに以下の 4 ファイルが全て存在するか確認: `HOMBA_v1_fixed.csv`、`homba_token_rules.csv`、`homba_alias_rules.csv`、`homba_abbrev_rules.csv`
- Lambda 環境変数のキー名と S3 オブジェクトキー名が一致しているか確認

### 以前の結果が出続ける

Lambda の実行環境が古いジェネレータをキャッシュしている可能性がある。

- Lambda コードを `Deploy` したか確認
- 数分待って再実行
- すぐ反映したい場合は環境変数を一度保存し直す

---

## 6. 独自ドメインを使う場合

### 6-1. Route 53 でドメインを用意する

Route 53 でドメインを取得するか、既存ドメインのホストゾーンを作成する。

### 6-2. ACM で証明書を作成する（`us-east-1` 必須）

CloudFront 用の証明書は必ず `us-east-1` リージョンで発行する。

1. リージョンを `us-east-1` に変更
2. ACM → `証明書をリクエスト` → パブリック証明書
3. ドメイン名を入力 → DNS 検証 → Route 53 でレコード自動作成
4. `発行済み` になるまで待つ

### 6-3. CloudFront にドメインを設定する

1. CloudFront ディストリビューション → `設定` → `編集`
2. Alternate domain name に独自ドメインを追加
3. Custom SSL certificate で ACM 証明書を選択

### 6-4. Route 53 で CloudFront へ向ける

1. Route 53 ホストゾーン → `レコードを作成`
2. レコードタイプ: `A`、`エイリアス` をオン
3. CloudFront ディストリビューションを選択

---

## 7. 公開時の注意事項

- `ALLOWED_ORIGIN` は公開 URL が決まったら `*` からフロントエンドの URL に絞ることを推奨（例: `https://d5keesfj4srwa.cloudfront.net`）
- 完全なアクセス制限が必要な場合は CloudFront Functions または Cognito を追加検討
- URL を知っている人だけが使える運用から始めるのが最も手軽
