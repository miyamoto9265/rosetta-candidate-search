# ROSETTA Candidate Search — API 仕様

**バージョン**: v0.3.1  
**最終更新**: 2026-06-25

---

## 1. エンドポイント

| 用途 | URL |
|---|---|
| **API** | `POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| **フロントエンド（検索 UI）** | `https://rcs.mymt.site/` |
| **CloudFront（代替 URL）** | `https://d5keesfj4srwa.cloudfront.net/` |

```
POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates
Content-Type: application/json
```

---

## 2. リクエスト

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `query` | string | **必須** | 検索したい脳領域名 |
| `top_k` | integer | 任意 | 返す候補数（1〜20、デフォルト: `5`） |
| `dhba_filter` | string | 任意 | `"both"`（デフォルト）/ `"with"`: DHBA_name あり / `"without"`: DHBA_name なし |

```json
{
  "query": "Pulvinar nucleus",
  "top_k": 5,
  "dhba_filter": "with"
}
```

---

## 3. レスポンス (200 OK)

| フィールド | 型 | 説明 |
|---|---|---|
| `query` | string | リクエストのクエリ |
| `top_k` | integer | 指定した候補数 |
| `dhba_filter` | string | 適用した DHBA フィルター |
| `candidates` | array | スコア降順の候補リスト |

### candidates の各要素

| フィールド | 型 | 説明 |
|---|---|---|
| `homba_id` | string | HOMBA ID（例: `HOMBA:10409`） |
| `name` | string | HOMBA 正式名称 |
| `acronym` | string | HOMBA 略語 |
| `dhba_name` | string | DHBA 対応名称 |
| `dhba_acronym` | string | DHBA 略語 |
| `parent_id` | string | 親ノードの HOMBA ID |
| `graph_order` | string | 階層グラフ上の順序番号 |
| `depth` | integer | 階層の深さ |
| `score` | float | マッチスコア（0〜1） |
| `methods` | string | 使用した検索手法（`+` 区切り） |
| `matched_alias` | string | 一致した HOMBA 側の別名 |
| `matched_query` | string | 実際に照合に使われたクエリバリアント |
| `modifier_terms` | string | 抽出された修飾語（`;` 区切り） |
| `modifier_match_score` | float | 修飾語の一致率（0〜1） |
| `hierarchy_reason` | string | 階層昇格の理由（該当する場合のみ） |

### methods の種類

| 値 | 意味 |
|---|---|
| `exact` | 正規化後の文字列が完全一致 |
| `fuzzy` | 文字列類似度でマッチ |
| `bm25` | BM25 スコアでマッチ |
| `hierarchy_parent` | 複数の子候補の共通親として昇格 |

### レスポンス例

```json
{
  "query": "Pulvinar nucleus",
  "top_k": 5,
  "dhba_filter": "with",
  "candidates": [
    {
      "homba_id": "HOMBA:10409",
      "name": "pulvinar of thalamus",
      "acronym": "Pul",
      "dhba_name": "pulvinar of thalamus",
      "dhba_acronym": "Pul",
      "parent_id": "HOMBA:AA30282",
      "graph_order": "728",
      "depth": 725,
      "score": 1.0,
      "methods": "exact",
      "matched_alias": "pulvinar of thalamus",
      "matched_query": "pulvinar nucleus",
      "modifier_terms": "",
      "modifier_match_score": 1.0,
      "hierarchy_reason": ""
    }
  ]
}
```

---

## 4. エラーレスポンス

| ステータス | 内容 | レスポンス例 |
|---|---|---|
| 400 | `query` が空または未指定 | `{"error": "query is required"}` |
| 500 | サーバー内部エラー | `{"error": "<エラーメッセージ>"}` |

---

## 5. 呼び出し例

```bash
curl -X POST https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates \
  -H "Content-Type: application/json" \
  -d '{"query": "Pulvinar nucleus", "top_k": 5}'
```

```python
import requests

API_URL = "https://zj7cl034xe.execute-api.ap-northeast-1.amazonaws.com/candidates"
resp = requests.post(API_URL, json={"query": "Pulvinar nucleus", "top_k": 5})
resp.raise_for_status()
for c in resp.json()["candidates"]:
    print(c["score"], c["homba_id"], c["name"])
```

---

## 6. Lambda 直接呼び出し（テスト）

API Gateway 経由では通常の JSON ボディで問題ない。Lambda を直接呼ぶ場合は `event["body"]` 形式が必要:

```bash
aws lambda invoke \
  --function-name rcs-api \
  --cli-binary-format raw-in-base64-out \
  --payload '{"requestContext":{"http":{"method":"POST"}},"body":"{\"query\":\"LC\",\"top_k\":1}"}' \
  /tmp/rcs-response.json
```

---

## 7. フロントエンド Web アプリ

`web/frontend/` に静的フロントエンドが存在し、S3 + CloudFront で配信している。

| ファイル | 役割 |
|---|---|
| `index.html` | 検索 UI |
| `app.js` | API 呼び出しと結果表示 |
| `styles.css` | スタイルシート |
| `config.js` | `apiBaseUrl`（API Gateway の Invoke URL） |
| `about.html` | サイト説明 |
| `scoring-guide.html` | スコアリング解説 |
| `walkthrough-bla.html` | 具体例ウォークスルー |
| `site-nav.css`, `site-trust.css` | 共通スタイル |

`config.js` の `apiBaseUrl` を API Gateway の Invoke URL に合わせること。運用手順は [AWS 運用ガイド](aws_operations_guide.md) を参照。
