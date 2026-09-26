# ROSETTA Candidate Search — API 仕様

**バージョン**: v0.9.0  
**最終更新**: 2026-09-27

> **v0.9.0:** AI 統合を追加。`use_ai_preprocess` / `use_ai_postprocess`（いずれも既定 ON）、
> `preprocess` / `ai` / `meta` ブロック。詳細は [AI 統合仕様](ai_integration_spec.md)。
>
> **2026-09-27:** RCS_EBL（`POST /candidates-ebl`、§7）と MCP サーバー（`/mcp`、§8）を追記。
> `/candidates` のリクエスト・レスポンスに変更はない。SABRA との関係は [SABRA 定義](sabra.md)。

---

## 1. エンドポイント

| 用途 | URL |
|---|---|
| **API** | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates` |
| **RCS_EBL API**（BNA、§7） | `POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl` |
| **MCP**（Bearer 認証、§8） | `https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/mcp` |
| **フロントエンド（検索 UI）** | `https://rcs.cobrac.site/` |

```
POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates
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
| `dhba_name` | string | DHBA 対応名称（候補から補完） |
| `dhba_acronym` | string | DHBA 略語（候補から補完） |
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
curl -X POST https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates \
  -H "Content-Type: application/json" \
  -d '{"query": "Pulvinar nucleus", "top_k": 5}'
```

```python
import requests

API_URL = "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates"
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

## 7. RCS_EBL API（`POST /candidates-ebl`）

文献上の領域名 → BNA（Brainnetome Atlas）領域の**確率分布**を返す。SABRA の BNA 部分に相当。AI なし。
実装: `rcs_ebl/`、`web/backend/lambda_function_ebl.py`（Lambda `rcs-ebl-api`）。

### リクエスト

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `query` | string | **必須** | 領域名（left/right/bilateral を含めると `bna_label_id` が決まる） |
| `top_k` | integer | 任意 | 1〜30、既定 `10` |
| `level` | string | 任意 | `"l3"`（既定、BNA 領域）/ `"l2"`（脳回） |
| `name_top_k` | integer | 任意 | 統合する文献名の数 1〜15、既定 `5`（exact 一致があればそれを優先） |
| `context` | string | 任意 | エコーのみ（処理には使わない） |

### レスポンス

`query` / `context` / `top_k` / `level` / `use_ai_preprocess: false` / `use_ai_postprocess: false` /
`meta`（`rcs_ebl_version`, `base_rcs_version`, `engine: "RCS_EBL"`）/ `candidates`。

`candidates` の主なフィールド:

| フィールド | 説明 |
|---|---|
| `bna_area_abbr` / `bna_area_name` | BNA 領域（l2 のときは脳回） |
| `bna_l2_abbr` / `bna_l3_code` | 脳回略称 / L3 コード |
| `bna_label_id_l` / `bna_label_id_r` / `bna_label_id` | BNA ラベル ID（1–246）。`bna_label_id` はクエリの左右から決定（不明なら空） |
| `laterality` | `left` / `right` / `bilateral` / `unknown` |
| `p_raw` | 文献座標に基づく確率（主指標）。`p` は平滑化済み（参考） |
| `score` | 名前一致スコア × `p_raw` |
| `match_score` / `matched_lit_name` / `methods` | 文献名との照合結果 |
| `k_papers` / `eff_n` / `n_papers` | 信頼性（支持論文数、分布の広がり: 1 ≈ 一意） |
| `homba_id` / `name` / `acronym` / `dhba_name` / `dhba_acronym` | **Web UI 互換の別名**（`homba_id` は `BNA:<abbr>` 形式で HOMBA ID ではない）。MCP では除去 |

```bash
curl -sS -X POST "https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com/candidates-ebl" \
  -H "Content-Type: application/json" -d '{"query":"left DLPFC","top_k":3}'
```

---

## 8. MCP サーバー（`/mcp`）

AI エージェント（cobrac-web の Codex SDK 等）向けのリモート MCP サーバー。Lambda `rcs-mcp`、実装 `web/backend/mcp_function.py`。

| 項目 | 値 |
|---|---|
| トランスポート | Streamable HTTP（ステートレス）。POST 1 JSON-RPC メッセージ → `application/json` 1 件 |
| プロトコル版 | `2025-06-18` / `2025-03-26` / `2024-11-05` |
| 認証 | `Authorization: Bearer <token>`（不一致・なしは 401） |
| 非対応 | GET（SSE）/ DELETE は 405、セッション ID は発行しない |

### ツール

| ツール | 入力 | 出力 |
|---|---|---|
| `search_homba_candidates` | `query`（必須）, `context`, `top_k`（既定 5）, `dhba_filter`, `use_ai`（既定 true: pre/post 両方） | §3 と同じ本文 ＋ `candidates[]` と `ai.results[]` の各要素に `sabra` |
| `search_bna_candidates` | `query`（必須）, `top_k`（既定 10）, `level`, `name_top_k` | §7 と同じ本文（UI 互換別名を除く）＋ 各候補に `sabra` |
| `get_homba_term` | `homba_id`（`HOMBA:10339` / `10339`） | 名称・DHBA 対応・`sabra`・`ancestors`（ルートから）・`children` |
| `get_sabra_definition` | なし | SABRA 定義（`rcs/sabra.py`） |

ツール結果は `structuredContent`（JSON）と同内容の `content[0].text` で返す。入力不正は `isError: true`。

`sabra` 注釈（定義は [SABRA 定義](sabra.md)）:

| 形 | 意味 |
|---|---|
| `{"atlas":"DHBA","dhba_name","dhba_acronym","dhba_homba_id","dhba_exact"}` | SABRA では DHBA 名で表す。`dhba_exact: false` は祖先の DHBA 名 |
| `{"atlas":"BNA","bna_territory","bna_territory_root"}` | HOMBA 項が BNA 担当範囲。SABRA 名は `search_bna_candidates` で得る |
| `{"atlas":"BNA","bna_division":"cortical"\|"subcortical"}` | BNA 候補（ラベル 1–210 / 211–246） |

---

## 9. フロントエンド Web アプリ

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
