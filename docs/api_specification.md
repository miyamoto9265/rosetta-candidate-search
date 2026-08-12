# ROSETTA Candidate Search — API 仕様

**バージョン**: v0.9.0  
**最終更新**: 2026-08-12

> **v0.9.0:** AI 統合を追加。`use_ai_preprocess` / `use_ai_postprocess`（いずれも既定 ON）、
> `preprocess` / `ai` / `meta` ブロック。詳細は [AI 統合仕様](ai_integration_spec.md)。

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
| `context` | string | 任意 | AI の判断材料となる自由記述（例: 論文タイトル）。空欄可 |
| `top_k` | integer | 任意 | 返す候補数（1〜20、デフォルト: `10`） |
| `dhba_filter` | string | 任意 | `"both"`（デフォルト）/ `"with"`: DHBA_name あり / `"without"`: DHBA_name なし |
| `use_ai_preprocess` | boolean | 任意 | AI 前処理（本質外除去）の ON/OFF。既定 `true` |
| `use_ai_postprocess` | boolean | 任意 | AI 判定（候補 0–4 件＋関係）の ON/OFF。既定 `true` |

```json
{
  "query": "right NAc Drd1 neurons",
  "context": "Dopamine D1 receptor signaling in the striatum",
  "top_k": 10,
  "dhba_filter": "both",
  "use_ai_preprocess": true,
  "use_ai_postprocess": true
}
```

両フラグを `false` にすると純 RCS（従来どおり `candidates` のみ）。

---

## 3. レスポンス (200 OK)

| フィールド | 型 | 説明 |
|---|---|---|
| `query` | string | リクエストのクエリ |
| `context` | string | リクエストのコンテキスト（エコー） |
| `top_k` | integer | 指定した候補数 |
| `dhba_filter` | string | 適用した DHBA フィルター |
| `use_ai_preprocess` | boolean | 実効値のエコー |
| `use_ai_postprocess` | boolean | 実効値のエコー |
| `meta` | object | 常時付与。`rcs_version` / `ai_model` |
| `candidates` | array | **常に RCS 生の top_k**（AI フィルタ非適用） |
| `preprocess` | object | `use_ai_preprocess: true` かつ AI 利用可能時のみ |
| `ai` | object | `use_ai_postprocess: true` かつ AI 利用可能時のみ |

### meta

| フィールド | 型 | 説明 |
|---|---|---|
| `rcs_version` | string | RCS アルゴリズム版（`ENGINE_VERSION`） |
| `ai_model` | string \| null | 実際に呼んだ LLM モデル ID。AI 未使用時は `null` |

### preprocess

| フィールド | 型 | 説明 |
|---|---|---|
| `roi_query` | string | RCS に渡した清掃クエリ |
| `removed` | array | 除去トークン `{text, kind}`。kind: `laterality` / `gene_or_marker` / `cell_type` / `method_or_other` / `noise` |
| `reason` | string | 短い理由 |
| `error` | string \| null | 失敗時メッセージ（その場合 `roi_query` は原文） |

### ai

| フィールド | 型 | 説明 |
|---|---|---|
| `results` | array | 妥当候補 **0〜4 件**。先頭が最良。wrong は含めない |
| `error` | string \| null | 失敗時メッセージ |

`ai.results` の各要素:

| フィールド | 型 | 説明 |
|---|---|---|
| `homba_id` | string | 候補内の HOMBA ID |
| `name` | string | 名称 |
| `acronym` | string | 略語 |
| `relation` | string | `'='`（一致）/ `<`（クエリのほうが小さい）/ `>`（クエリのほうが大きい） |
| `reason` | string | 短い理由 |

> 一致の relation は **先頭アポストロフィ付き `'=`**（Excel が数式と誤認しないため）。
> `confidence` 数値は返さない。

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
| `hierarchy_reason` | string | **互換フィールド**。v0.8.0 以降は常に空文字（階層親昇格は廃止） |

### methods の種類

| 値 | 意味 |
|---|---|
| `exact` | 正規化後の文字列が完全一致 |
| `fuzzy` | 文字列類似度でマッチ |
| `bm25` | BM25 スコアでマッチ |

> **変更 (v0.8.0):** `hierarchy_parent`（共通親へのスコア昇格）はアルゴリズムから削除されました。
> レスポンスの `methods` に `hierarchy_parent` は現れません。`hierarchy_reason` は後方互換のため残していますが常に空です。
> 親へのフォールバックは、領域アンカー必須・構造クラス衝突・辞書ルールなどスコア側の罰則／別名で実現します。

### レスポンス例

```json
{
  "query": "right NAc Drd1 neurons",
  "top_k": 10,
  "dhba_filter": "both",
  "use_ai_preprocess": true,
  "use_ai_postprocess": true,
  "meta": {
    "rcs_version": "0.8.5",
    "ai_model": "deepseek-v4-flash"
  },
  "preprocess": {
    "roi_query": "NAc",
    "removed": [
      {"text": "right", "kind": "laterality"},
      {"text": "Drd1", "kind": "gene_or_marker"},
      {"text": "neurons", "kind": "cell_type"}
    ],
    "reason": "Removed laterality, gene marker, and cell type; kept core region.",
    "error": null
  },
  "candidates": [
    {
      "homba_id": "HOMBA:10339",
      "name": "nucleus accumbens",
      "acronym": "NAC",
      "dhba_name": "",
      "dhba_acronym": "",
      "parent_id": "HOMBA:…",
      "graph_order": "…",
      "depth": 0,
      "score": 1.0,
      "methods": "exact",
      "matched_alias": "nucleus accumbens",
      "matched_query": "nac",
      "modifier_terms": "",
      "modifier_match_score": 1.0,
      "hierarchy_reason": ""
    }
  ],
  "ai": {
    "results": [
      {
        "homba_id": "HOMBA:10339",
        "name": "nucleus accumbens",
        "acronym": "NAC",
        "relation": "'=",
        "reason": "NAc is standard abbreviation for nucleus accumbens."
      }
    ],
    "error": null
  }
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
