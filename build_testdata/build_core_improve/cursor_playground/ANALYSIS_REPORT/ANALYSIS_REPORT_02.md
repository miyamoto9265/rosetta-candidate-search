# ROSETTA Candidate Search — 分析・改善レポート 02

**日付**: 2026-05-17  
**対象**: LLM-based Recursive Improvement — Round 2.5（`cursor_playground`）  
**前回レポート**: ANALYSIS_REPORT_01.md（Round 1–2）  
**内容**: ANALYSIS_REPORT_01 の「今後求められる対応」への対処

---

## 1. 実施内容の概要

前回レポートで挙げた課題のうち、優先度「高」の 2 件（5-1、5-2）とその他軽微な改善を実施した。

| 課題番号 | 内容 | 対応 |
|---------|------|------|
| 5-1 | hierarchy_parent 昇格スコアに raw method score を使っていた | 2-pass scoring に再設計 |
| 5-2 | LC 等 2〜3 文字略語の安全な対応 | query-only 略語テーブル新設 |
| 5-7（副次） | pure hierarchy_parent 候補に specificity_penalty が二重適用されていた | penalty 除外条件を修正 |
| alias 追加 | Insular cortex、Raphe nuclei の regression を修正 | alias_rules 2 件追加 |

---

## 2. 変更ファイル

### 2-1. `homba_abbrev_rules.csv`（新規ファイル）

**目的**: 略語展開を alias_rules から切り離し、query 側のみに適用する専用テーブルを新設。  
**alias_rules との違い**:

| | alias_rules | abbrev_rules |
|-|-------------|-------------|
| 展開方向 | **双方向**（query にも HOMBA alias にも適用） | **query のみ**（HOMBA alias インデックスには不適用） |
| 用途 | 同義語・別名称の対称的なマッピング | 略語 → フルネームの一方向展開 |
| リスク | 短い略語を登録すると HOMBA alias が汚染される | HOMBA alias は汚染されない |

**収録内容（37 ルール）**:

```
lc         → locus coeruleus
nts / nst  → solitary nucleus
pag        → periaqueductal gray
sn         → substantia nigra
snc        → substantia nigra compact division
snr        → substantia nigra reticular division
gp         → globus pallidus
gpe        → lateral segment of globus pallidus
gpi        → medial segment of globus pallidus
nac / nacc → nucleus accumbens
ofc        → orbital frontal cortex
pfc        → prefrontal cortex
dlpfc      → dorsolateral prefrontal cortex
mpfc       → medial prefrontal cortex
vmfc       → ventromedial frontal cortex
vlpfc      → ventrolateral prefrontal cortex
hpc        → hippocampus
amy        → amygdala
bla        → basolateral nuclear group of amygdala
cea        → central nucleus of amygdala
pvn / pvnh → paraventricular nucleus of hypothalamus
scn        → suprachiasmatic nucleus
arc        → arcuate nucleus
drn        → dorsal raphe nucleus
mnr        → median raphe nucleus
dg         → dentate gyrus
ca1 / ca2 / ca3 → cornu ammonis 1 / 2 / 3
sc         → superior colliculus
ic         → inferior colliculus
mfb        → medial forebrain bundle
vta        → ventral tegmental area
sth        → subthalamic nucleus
```

**展開ロジック（`apply_abbrev_rules` 関数）**:
- **完全一致**: クエリ全体が略語と一致 → 全長さで展開
- **ワード境界置換**: 略語が 3 文字以上の場合のみ、クエリ内の独立した単語として置換  
  例: `"dorsal stn pathway"` → `"dorsal subthalamic nucleus pathway"`
- 2 文字以下の略語（`lc`, `sn`, `gp`, `dg` など）はワード境界置換を行わず、クエリ全体一致のみ適用（偽陽性防止）

---

### 2-2. `rosetta_candidate_generator.py`（v0.2.0 → v0.3.0）

#### 変更点 1: `AbbrevRule` dataclass + ローダー・適用関数の追加

```python
@dataclass(frozen=True)
class AbbrevRule:
    """Query-only abbreviation expansion (never applied to HOMBA alias expansion)."""
    abbrev: str      # 正規化済み略語 ("lc", "nts" など)
    expansion: str   # 正規化済み展開形
    notes: str = ""

DEFAULT_ABBREV_RULES_CSV = Path(__file__).with_name("homba_abbrev_rules.csv")
```

`query_variants()` 関数に `abbrev_rules` 引数を追加。alias 展開後の最終ステップで適用：

```python
# Apply abbreviation expansion last (query-only; not used for HOMBA alias expansion).
abbrev_expanded: list[str] = []
for variant in expanded:
    abbrev_expanded.extend(apply_abbrev_rules(variant, abbrev_rules))
```

`RosettaCandidateGenerator.__init__` に `abbrev_rules_csv` パラメータを追加（デフォルト値あり、後方互換）。

---

#### 変更点 2: 2-pass scoring（5-1 対応）

**問題**: `_promote_common_parents` が各子候補の `best_method_score`（penalty 適用前の raw スコア）を使って親を昇格させていた。raw score は 1.0 でも、後で `_specificity_penalty` により 0.86 になる場合があるため、親が過剰に高いスコア（0.97）で昇格し、正解の子候補（0.86）を上回る誤動作が生じていた（今回の exact match 除外修正後も fuzzy match の場合に残存）。

**修正**: `generate()` を 2-pass 構造に変更。

```
Pass 1: exact/fuzzy/bm25 で候補収集
         ↓
prelim_scores[term_index] = 全候補の final_score を先算出（penalized 後）
         ↓
_promote_common_parents(..., prelim_scores)  ← final score をベースに親を昇格
         ↓
Pass 2: 全候補（hierarchy_parent を含む）の最終スコアを確定して ranked list を構築
```

`_promote_common_parents` の子スコア参照を変更：

```python
# Before (raw method score)
child_scores = [float(candidate_state[child_index]["best_method_score"]) for child_index in child_indexes]

# After (pass-1 final score)
child_scores = [
    prelim_scores.get(child_index, float(candidate_state[child_index]["best_method_score"]))
    for child_index in child_indexes
]
promoted_score = min(max(child_scores) + 0.08, 0.97)
```

**効果**: 子候補が fuzzy match + specificity_penalty により 0.77 の final score を持つ場合、
- 旧: 親の promoted_score = raw 0.89 + 0.08 = 0.97（親が子に勝つ）
- 新: 親の promoted_score = final 0.77 + 0.08 = 0.85（親は子より少し高いが、正確な差）

---

#### 変更点 3: `_score_candidate()` ヘルパーメソッドの追加と penalty 条件修正（5-7 対応）

スコア計算ロジックを `_score_candidate()` に切り出し、2-pass で再利用可能にした。  
同時に `_specificity_penalty` の適用条件を修正：

```python
# Before
if not exact:
    final_score *= self._specificity_penalty(query, modifier_terms, term)

# After
if not exact and (fuzzy or bm25):
    final_score *= self._specificity_penalty(query, modifier_terms, term)
```

**修正の根拠**:  
pure hierarchy_parent 候補（exact/fuzzy/bm25 の直接証拠なし）にペナルティを適用するのは誤り。親の promoted_score は子の penalized final score から算出されており、そこにさらに親自身のペナルティをかけると二重減点になる。

penalty の適用対象を整理すると：

| マッチ種別 | penalty 適用 | 理由 |
|-----------|:----------:|------|
| exact | ✗ | クエリが alias を直接指名しているため（前回修正） |
| fuzzy / bm25 のみ | ✓ | 曖昧マッチなので過特異性チェックが必要 |
| hierarchy_parent のみ | ✗ | promoted_score は既に子の penalized score を反映 |
| fuzzy/bm25 + hierarchy_parent | ✓ | 直接証拠があるため通常の penalty を適用 |

---

### 2-3. `homba_alias_rules.csv` への追加（2 ルール）

2-pass scoring 導入により score が変動したケースを修正：

| 追加ルール | 効果 |
|-----------|------|
| `insular cortex → major insular cortex` | "Insular cortex" が exact match (1.0) で HOMBA:10288 に到達（旧: fuzzy+hierarchy 0.94） |
| `raphe nuclei → raphe nuclei in midbrain` | "Raphe nuclei" が exact match (1.0) で HOMBA:12222 に到達（旧: hierarchy 0.83 で不正確なエントリ） |

---

## 3. 改善効果（前回ベスト比）

本セッションの変更による増分効果：

| テストセット | 新規マッチ | 改善 | 悪化 |
|------------|:--------:|:---:|:---:|
| level1.csv（50 クエリ） | 0 | 0 | 0 |
| round1_comprehensive（50 クエリ） | **+1**（LC） | 0 | 0 |
| round3_edge_cases（44 クエリ） | **+1**（NTS） | **+2** | 3※ |

※ 悪化 3 件の内訳：
- **Arcuate nucleus**: score 0.78→0.72 だが entity が「sensory relay nuclei（完全に誤り）→ arcuate nucleus of hypothalamus（正しい）」に改善。実質は **精度向上**。compare_results.py が score 低下をもって "worsened" と判定しているが誤判定。
- **Septum**: 0.61→0.60。同水準の不正確なマッチで差は 0.005。無視できるレベル。
- **Thalamic nuclei**: 0.83→0.81。同一 entity で差は 0.02。無視できるレベル。

---

## 4. 累積改善効果（オリジナルからの総計）

前回(ANALYSIS_REPORT_01)との合算で、元バージョン比の総合成績：

| テストセット | 新規 | 改善 | 悪化 |
|------------|:---:|:---:|:---:|
| level1.csv（50 クエリ） | 0 | **+8** | 0 |
| round1_comprehensive（50 クエリ） | **+2** | **+26** | 0 |
| round3_edge_cases（44 クエリ） | **+1** | **+22** | 3※ |

主要な改善事例（全テストを通じて累計）：

| クエリ | 改善前スコア / entity | 改善後スコア / entity |
|--------|----------------------|----------------------|
| LC（略語） | マッチなし | 1.0 / nucleus coeruleus (locus coeruleus) |
| NTS（略語） | マッチなし | 1.0 / solitary nucleus |
| Dentate nucleus | 0.97 / cerebellar deep nuclei ❌ | 1.0 / dentate (lateral) nucleus ✓ |
| Fastigial nucleus | 0.97 / cerebellar deep nuclei ❌ | 1.0 / fastigial (medial) nucleus ✓ |
| Globose nucleus | 0.64 / sensory relay nuclei ❌ | 1.0 / medial interpositus (globose) nucleus ✓ |
| Emboliform nucleus | 0.65 / 正解（低信頼） | 1.0 / lateral interpositus (emboliform) nucleus ✓ |
| Central amygdala | 0.95 / regions of amygdaloid complex ❌ | 1.0 / central nucleus of amygdala ✓ |
| Basolateral amygdala | 0.97 / regions of amygdaloid complex ❌ | 1.0 / basolateral nuclear group ✓ |
| Substantia nigra pars compacta | 0.83 / substantia nigra ❌ | 1.0 / SN compact division ✓ |
| Raphe nuclei | 0.83 / pontine raphe region（不正確） | 1.0 / raphe nuclei in midbrain ✓ |
| Insular cortex | 0.94 / major insular cortex（同 entity） | 1.0 / major insular cortex ✓ |

---

## 5. 残存課題（引き続き今後の対応が必要）

### 優先度：高

**5-3. laterality 付き細分構造（ラテン語語尾）**  
`caudalis`/`oralis`/`interpolaris` は alias rules で個別対応済み。  
ただし他の -alis/-aris 語尾変形（例: `rostralis`, `ventralis`）が今後の入力に現れた場合は追加が必要。  
→ token_rules の modifier テーブルに登録 + alias rules で対応するのが現状の正攻法。

### 優先度：中

**5-4. HOMBA にエントリがない集合概念**  
- **Limbic system**: 機能的概念。HOMBA に対応エントリなし。
- **Brainstem**: 単一エントリなし（midbrain + pons + medulla の集合）。
- **Thalamic nuclei**: 個別の核はあるが「視床核全体」の集約エントリはない。  
→ 「マッチなし」を明示的に返す設計を検討（信頼度閾値以下は low_confidence として明示など）。

**5-5. eponym（人名由来語）の体系的対応**  
Broca's area、Wernicke's area は現状 low_confidence の近似マッピングのみ。  
個別の alias rule で対応しているが、eponym mapping テーブルとして体系的に管理する仕組みが望ましい。

**5-6. 綴り揺れへの体系的対応**  
`grey/gray`、`-alis/-al`、`pars X / X division` などは個別 alias rule で対応済み。  
normalize_text 関数への統合（pre-normalization ステップ）により体系化する余地がある。

### 優先度：低

**IC（inferior colliculus）の曖昧性**  
HOMBA 自体が "IC" を inferior colliculus と internal capsule の両方の acronym として保持しているため、"IC" クエリでは両者が 1.0 で同着になる。HOMBA 側の修正またはユーザーへの曖昧性提示が必要。

**5-7（残余）: alias_rules の双方向自己参照**  
`emboliform nucleus → lateral interpositus emboliform nucleus` のように target が source を substring に含む規則では、HOMBA alias 展開時に長い alias が生成される。実害は限定的だが alias rule バリデーションを整備することが望ましい。

---

## 6. 最終的なファイル構成

```
cursor_playground/
├── rosetta_candidate_generator.py  ← v0.3.0（2-pass scoring + abbrev_rules 対応）
├── homba_abbrev_rules.csv          ← 新規（37 ルール、query-only 略語テーブル）
├── homba_alias_rules.csv           ← 41 ルール（前回 38 → +2 ルール追加）
├── homba_token_rules.csv           ← 変更なし
├── HOMBA_v1_fixed.csv              ← 変更なし
├── rcs_test_interactive.py
├── rcs_test_list.py
├── analyze_homba.py
├── compare_results.py
├── search_homba.py                 ← 新規（HOMBA キーワード検索ヘルパー）
├── smoke_test.py                   ← 新規（略語テスト用 smoke test）
├── ANALYSIS_REPORT_01.md
├── ANALYSIS_REPORT_02.md           ← 本ドキュメント
└── test_list/
    ├── input/
    │   ├── level1.csv
    │   ├── round1_comprehensive.csv
    │   └── round3_edge_cases.csv
    └── output/
        └── （各テスト実行結果 CSV）
```

---

## 7. 本番反映時の注意事項

前回レポート（ANALYSIS_REPORT_01.md §7）の注意事項に加えて：

1. **`homba_abbrev_rules.csv` の配置**  
   `rosetta_candidate_generator.py` と同一ディレクトリに配置する必要がある（`DEFAULT_ABBREV_RULES_CSV = Path(__file__).with_name("homba_abbrev_rules.csv")`）。

2. **`abbrev_rules_csv` パラメータのデフォルト値**  
   `RosettaCandidateGenerator.__init__` に `abbrev_rules_csv` パラメータを追加したが、デフォルト値あり（後方互換）。既存の呼び出しコードの変更は不要。

3. **`lambda_function.py` との同期**  
   Web バックエンドにはロジックの inline コピーがある。今回の変更（2-pass scoring、`_score_candidate`、penalty 条件修正）を `lambda_function.py` にも反映すること。

4. **バージョン**: `rosetta_candidate_generator.py` の VERSION が 0.3.0 になっていることを確認し、`lambda_function.py` も合わせること。

---

*本番環境への適用前に追加の回帰テストを実施することを推奨。*
