# ROSETTA Candidate Search — アルゴリズム仕様

**バージョン**: v0.8.5  
**最終更新**: 2026-08-12

> **注記（API v0.9.0）**: 本書は RCS エンジン本体の仕様。本番 API ではこの前後に
> LLM 補助レイヤ（preprocess: クエリ清掃 / postprocess: 候補裁定）が挟まるが、
> 本書のスコアリングは一切変更されない。AI レイヤの仕様は [AI 統合仕様](ai_integration_spec.md) を参照。

---

## 1. 概要

ROSETTA Candidate Search（RCS）は、脳領域・解剖学的構造名のテキストを入力として受け取り、HOMBA（Human Occipital-and-More Brain Atlas）オントロジーの候補 ID と名称をスコア付きで返すシステムである。

単一の入力テキスト（例: `Subthalamic nucleus`、`Internal capsule (posterior limb)`、`LC`）を、HOMBA 登録名・略語・階層名と照合し、最も適合するエントリを上位から返す。

---

## 2. 入力データファイル

RCS は **`rcs/`** ディレクトリ内の以下 4 つの CSV ファイルを読み込む（`rosetta_candidate_generator.py` と同ディレクトリ）。

| ファイル名 | 役割 |
|---|---|
| `HOMBA_v1_fixed.csv` | HOMBA 本体データ。ID・標準名・略語・DHBA名・階層情報を含む |
| `homba_token_rules.csv` | 語の扱いを定義。stopword・laterality語・weak_terms・modifier_terms を設定 |
| `homba_alias_rules.csv` | エントリ側の同義語・別表記ルール（75件）。HOMBA 側の別名を拡張するために使用 |
| `homba_abbrev_rules.csv` | クエリ側専用の略語展開ルール（37件）。`LC` → `locus coeruleus` のような展開 |

### 2-0. Lambda デプロイ時の索引キャッシュ

本番 Lambda では、起動時の索引構築を省略するため **`generator_cache.pkl`**（`scripts/build_generator_cache.py` で生成）をデプロイ zip に同梱する。キャッシュが無効な場合のみ上記 CSV から `_load_homba_csv()` → `_build_indexes()` を実行する。詳細は [AWS 運用ガイド](aws_operations_guide.md) を参照。

### 2-1. alias_rules の役割

`homba_alias_rules.csv` は HOMBA 側の検索対象別名を拡張するために使用する。

```csv
input_text,homba_text,notes
amygdala,amygdaloid complex,
pineal gland,pineal body,
locus ceruleus,locus coeruleus,alternate spelling
```

`input_text` に一致した HOMBA エントリの別名リストに `homba_text` が追加される。

### 2-2. abbrev_rules の役割

`homba_abbrev_rules.csv` はクエリ側のみに適用する略語展開である。HOMBA 側の別名には適用しない。

```csv
abbrev,expansion,notes
lc,locus coeruleus,
nts,nucleus of solitary tract,
pag,periaqueductal gray,
```

正規化後のクエリが abbrev に完全一致した場合に expansion へ置換し、そのバリアントでも検索を行う。

---

## 3. アルゴリズム概要

### 3-1. テキスト正規化

入力テキストを以下の手順で正規化する。

1. NFKC Unicode 正規化
2. `&` → `and`、`/` → スペース
3. アポストロフィ・ハイフン・アンダースコアを除去またはスペースに変換
4. 英数字以外を除去、連続スペースを1つに縮小
5. 小文字化

### 3-2. クエリバリアントの生成

正規化後の入力テキストから以下のバリアントを生成し、複数の表記で検索を行う。

- 正規化テキスト本体
- 括弧部分を除去したテキスト（括弧内の修飾語は modifier_terms として保持）
- laterality 語（left/right/bilateral 等）を除去したテキスト
- abbrev_rules にマッチした場合の展開形

### 3-3. HOMBA 側の別名生成

各 HOMBA エントリに対して以下から別名リストを構築する。

- HOMBA 標準名 (`unified_ontology_name`)
- HOMBA 略語 (`unified_ontology_acronym`)
- DHBA 名称 (`DHBA_name`)
- DHBA 略語 (`DHBA_acronym`)
- 階層フィールド (`hierarchy_*`) 内の名称
- 括弧内展開（`frontal polar cortex (FP, area 10)` → `frontal polar cortex`、`FP`、`area 10` 等）
- `alias_rules` による追加別名

### 3-4. 3 種類の検索手法

| 手法 | 説明 | methods フィールド値 |
|---|---|---|
| 完全一致 (exact) | 正規化後の文字列が完全一致 | `exact` |
| あいまい一致 (fuzzy) | bigram/trigram Dice 係数 + SequenceMatcher + トークン Jaccard の組み合わせ | `fuzzy` |
| BM25 スタイルトークン検索 | 単語の共起を利用。語順違いや複合語に強い | `bm25` |

複数手法でヒットした場合は同一 HOMBA エントリとして統合する。各手法のスコアは手法ごとに最大値を保持し、最終スコアは後述の式で合成する（単純加算ではない）。

#### 3-4-1. 倒排インデックスと候補の絞り込み

起動時に HOMBA 全別名から以下のインデックスを構築する。

| インデックス | 内容 |
|---|---|
| `alias_map` | 正規化別名 → HOMBA エントリ index（exact 用） |
| `alias_entries` | 別名ごとのトークン列・トークン頻度（BM25 / fuzzy 用） |
| `token_to_entries` | トークン → 別名 entry index の集合（fuzzy / BM25 用） |
| `_bm25_doc_freq` | トークンの document frequency（`df`） |

fuzzy と BM25 は全別名（約 9,000 件）に対して `string_similarity` / BM25 を毎回実行せず、クエリトークンで候補別名を絞り込んでからスコアリングする。絞り込み方式は手法ごとに異なる。

**fuzzy（v0.3.1 以降: INTERSECTION）**

1. クエリバリアントをトークン化（stopword 除去）
2. トークンが 3 個以上ある場合、document frequency が低い（レアな）**2 トークン**に限定（`rarest_limit=2`）
3. 選ばれた各トークンの posting list の **積集合（INTERSECTION）** を fuzzy 比較対象とする
4. 積集合が空で、正規化後バリアント長が 5 文字超の場合のみ **全別名スキャン** にフォールバック
5. 各別名に `string_similarity()` を適用し、スコア ≥ 0.45 のものを候補化（エントリごとに最大値）

INTERSECTION により、`nucleus` のような高頻度トークン単体では候補が膨らまない。例: `Subthalamic nucleus` は `subthalamic`（df≈3）と `nucleus`（df≈1,400）の積集合 ≈ 3 件のみを比較する（旧 UNION 方式では ≈ 1,400 件）。

**BM25（UNION）**

1. クエリバリアントの **全トークン** について posting list を取得
2. posting list の **和集合（UNION）** を BM25 比較対象とする（recall 重視）
3. 正規化 BM25 スコア > 0 のものを候補化（エントリごとに最大値）

| 手法 | トークン選択 | 集合演算 | フォールバック |
|---|---|---|---|
| fuzzy | レアな 2 トークン（3 トークン以上のとき） | **INTERSECTION** | 積集合が空 かつ バリアント長 > 5 → 全スキャン |
| bm25 | 全トークン | **UNION** | なし |
| exact | — | `alias_map` 直接参照 | — |

### 3-5. スコアリング（1-pass）

候補収集（exact / fuzzy / bm25）の後、各候補に対して `_score_candidate()` を **1 回**適用し、最終スコアとする。

v0.3〜v0.7 では、階層親昇格（`hierarchy_parent`）のために予備スコア → 親追加 → 再スコアの **2-pass** を行っていた。
v0.8.0 で親昇格を廃止したため、2-pass も不要になり削除した。

親への「安全な吸収」は次のスコア側機構で代替する（詳細は 3-8）:

- **領域アンカー必須**（orbital / occipital / temporal 等）: クエリが命名した領域語を候補がカバーしない場合は減点
- **構造クラス衝突**（cortex↔claustrum、tract↔nucleus 等）
- **複数形 nuclei 減点**: クエリが複数核を指すのに単一 nucleus だけを返す場合
- **辞書**（`homba_alias_rules.csv` / `homba_abbrev_rules.csv`）による親・近傍語への誘導

詳細な計算式は 3-8 を参照。

### 3-6. specificity_penalty（過細候補の減点）

クエリに存在しない細分類語（`inferior`、`lateral`、`core`、`shell`、`molecular` 等）が候補側の別名に含まれる場合、そのスコアを減点する。

ただし **exact match** で発見された候補にはペナルティを適用しない。

### 3-7. modifier_terms によるスコア調整

括弧内から抽出した修飾語（`posterior limb`、`external`、`core` 等）が候補側の別名に含まれていれば加点し、含まれていなければスコアを減点する（詳細は 3-8-3）。

---

### 3-8. スコア計算の詳細

最終スコアは 0〜1 の浮動小数点数で、`_score_candidate()` により算出される。出力時は `min(score, 1.0)` を小数第 6 位で丸める。

#### 3-8-1. 各検索手法のスコア

| 手法 | 算出方法 | 候補化の条件 |
|---|---|---|
| `exact` | 正規化後のクエリバリアントと HOMBA 別名が完全一致 → **1.0** | 常に候補 |
| `fuzzy` | クエリバリアントと各別名の `string_similarity()` の最大値 | スコア ≥ **0.45** |
| `bm25` | トークン共起に基づく BM25 スコアを正規化した値 | 正規化スコア > 0 |

同一エントリ・同一手法で複数ヒットした場合、その手法のスコアは **最大値** を採用する（`_add_candidate()`）。

**fuzzy スコア（`string_similarity`）**

正規化後の文字列同士を比較する。完全一致なら 1.0。それ以外は以下の加重平均と部分文字列ボーナスの **最大値** を返す。

```
similarity = max(
  containment_bonus,
  0.35 × SequenceMatcher.ratio
+ 0.25 × bigram Dice
+ 0.20 × trigram Dice
+ 0.20 × token Jaccard
)
```

- **bigram / trigram Dice**: 空白除去後の文字列から n-gram 集合を作り、`2|A∩B| / (|A|+|B|)` を計算
- **token Jaccard**: stopword 除去後トークン集合の `|A∩B| / |A∪B|`
- **containment_bonus**: 一方が他方の部分文字列（長さ ≥ 4）のとき、`min(0.92, len(短)/len(長) + 0.25)` を付与

**BM25 スコア**

エントリごとに最もスコアの高い別名を採用する。パラメータは `k1 = 1.5`、`b = 0.75`。

```
IDF(t) = log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))
BM25_raw = Σ_t  IDF(t) × (freq × (k1+1)) / (freq + k1 × (1 - b + b × doc_len / avg_len)) × query_count(t)
BM25_norm = BM25_raw / (BM25_raw + 4.0)
```

`N` は全別名エントリ数、`df(t)` はトークン `t` を含む別名数、`avg_len` は別名の平均トークン長。

#### 3-8-2. 最終スコアの合成式

各候補について、クエリ全体と HOMBA 全別名の **token Jaccard 最大値** を `token_score` とする。

```
base = max(
  exact_score,
  0.5 × fuzzy + 0.3 × bm25 + 0.2 × token_score,
  0.75 × fuzzy + 0.25 × token_score
)
```

- `exact` が存在する場合: `base = max(base, 0.96)`（完全一致候補の下限を引き上げ）
- 上記 3 項のうち **最大値** を採る（手法スコアが未設定の項は 0 として扱う）

#### 3-8-3. modifier_terms による加減点

修飾語一致率 `modifier_match_score` は、抽出した修飾語のうち候補別名テキスト（正規化・連結）に含まれる割合（0〜1）。修飾語がない場合は 1.0。

| 条件 | 調整 |
|---|---|
| 修飾語なし | 調整なし |
| 修飾語あり & 一致率 > 0 | `base + 0.12 × modifier_match_score`（上限 1.0） |
| 修飾語あり & 一致率 = 0 | `base × 0.88`（上限 0.88） |

#### 3-8-4. specificity_penalty（過細候補の減点）

修飾語調整後、以下を **すべて** 満たす候補にのみ乗算する。

- `exact` マッチがない
- `fuzzy` または `bm25` マッチがある
- クエリに修飾語（`modifier_terms`）が **ない**
- 候補に親 ID がある

候補別名に含まれる specificity 語（`homba_token_rules.csv` の `modifier` / `weak` 種別）のうち、クエリに存在しない語が 1 つでもあれば **× 0.86**。該当なしなら **× 1.0**（減点なし）。

`exact` マッチの候補は減点対象外。

#### 3-8-5. 追加の減点（親昇格の代替）

exact 以外の候補に対し、必要に応じて次を乗算する。

| ルール | 条件 | 倍率 |
|---|---|---|
| 構造クラス衝突 | クエリと候補のヘッド構造クラスが不一致（cortex↔gray/claustrum、tract↔nucleus 等） | × 0.50 |
| 接頭辞不一致 | クエリに pre-/retro-/juxta- 等があり候補が裸語幹のみ | × 0.62 |
| 領域アンカー欠落 | クエリの orbital / occipital / temporal 等を候補別名がカバーしない | × 0.48 |
| 複数形 nuclei 不一致 | クエリが `nuclei` なのに候補名が単一 `nucleus`（group/complex 等を除く） | × 0.72 |
| weak-only キャップ | 識別語の共有がなく方向・汎用語だけが重なる | 上限 0.38 |

#### 3-8-6. 処理の流れ

```
1. exact / fuzzy / bm25 で候補収集（手法別最大スコアを保持）
   - fuzzy: token インデックス INTERSECTION で別名を絞り込み → string_similarity
   - bm25: token インデックス UNION で別名を絞り込み → BM25
2. 全候補に _score_candidate() を適用（修飾語・penalty・アンカー等込み）
3. score 降順 → name 昇順 → homba_id 昇順 でソート
```

> **廃止 (v0.8.0):** `_promote_common_parents` / `hierarchy_parent` / 2-pass スコアリング。

---

## 4. generate() の出力フィールド

`RosettaCandidateGenerator.generate()` が返す候補リストの各エントリ:

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
| `methods` | string | 使用した検索手法（`+` 区切り）。値: `exact` / `fuzzy` / `bm25` |
| `matched_query` | string | 実際に照合に使われたクエリバリアント |
| `matched_alias` | string | 一致した HOMBA 側の別名 |
| `modifier_terms` | string | 抽出された修飾語（`;` 区切り） |
| `modifier_match_score` | float | 修飾語の一致率（0〜1） |
| `hierarchy_reason` | string | 互換フィールド。v0.8.0 以降は常に空 |

---

## 5. 既知の動作特性

| パターン | 挙動 |
|---|---|
| laterality 付きクエリ | `left`/`right`/`bilateral` 等を除去した形でも検索 |
| 括弧付きクエリ | 括弧部分を除去した形でも検索。括弧内語句を modifier_terms として活用 |
| 曖昧略語（例: Septum） | 文脈なしでは複数候補のうち最上位を返すのみ |
| HOMBA に存在しない概念 | `limbic system`、`brainstem`（単一エントリなし）、`IFOF` 等は低スコアになる |
| 所有格クエリ（Broca's 等） | 標準的な ASCII アポストロフィ（`'` U+0027）は正規化時に削除される。Curly quote（`'` U+2019）は部分的に対応 |
| 高頻度語を含む複合語（例: `* nucleus`） | fuzzy は INTERSECTION によりレアトークン共起の別名のみ比較。BM25 / exact は従来どおり動作 |
