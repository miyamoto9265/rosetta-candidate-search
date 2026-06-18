# Corpus 初回 RCS 実行レポート（CORPUS_REPORT_01）

**作成日**: 2026-06-07  
**入力**: `build_testdata/rcs_corpus_source.csv`（559行 / 493ユニーク名称 / 12論文）  
**出力**: `build_testdata/build_core_improve/output/rcs_corpus_source_run1.csv`  
**RCS バージョン**: v0.3.0（`rcs/rosetta_candidate_generator.py`）  
**分析 JSON**: `build_testdata/build_core_improve/output/rcs_corpus_source_analysis.json`

---

## 1. エグゼクティブサマリ

Corpus ソース（実論文由来の脳部位名）に対して RCS を**初めて一括実行**した。

| 指標 | 559行（全行） | 493名称（ユニーク） |
|------|--------------|---------------------|
| **high_confidence**（≥0.90） | 262 (**46.9%**) | 201 (**40.8%**) |
| needs_review | 165 (29.5%) | 160 (32.5%) |
| modifier_conflict | 25 (4.5%) | 25 (5.1%) |
| low_confidence（<0.60） | 107 (19.1%) | 107 (21.7%) |

Core（標準名称集）との重複 91 名称は **exact match 91/91（100%）** で、Corpus 上でも Core の期待 ID と一致。回帰はなし。

一方、Corpus 全体の high_conf 率は **約 41%** と、LLM-based Recursive Improvement で整備した Core の基準（96% 前後）より大幅に低い。論文固有の parcellation 名・括弧付きサブリージョン・種差名称が主因。

---

## 2. 実行条件

```bash
python rcs/rcs_test_list.py build_testdata/rcs_corpus_source.csv \
  --top-k 1 \
  --output-csv build_testdata/build_core_improve/output/rcs_corpus_source_run1.csv
```

- HOMBA: `rcs/HOMBA_v1_fixed.csv`（2342 terms）
- alias / abbrev: `rcs/homba_alias_rules.csv` / `rcs/homba_abbrev_rules.csv`
- `dhba_filter=both`（デフォルト）

---

## 3. 全体分布

### 3-1. 種別（ユニーク 493 名称）

| 種 | high_conf | needs_review | modifier_conflict | low_conf | high_conf 率 |
|----|-----------|--------------|-------------------|----------|--------------|
| **Human** | 156 | 111 | 14 | 98 | **41.2%** |
| **Macaque** | 33 | 35 | 2 | 7 | **33.0%** |
| **Rat** | 12 | 14 | 9 | 2 | **27.3%** |

Human が最も高いが、Macaque / Rat は HOMBA（Human/DHBA 中心）との乖離が大きい。

### 3-2. カテゴリ（559行）

| category | high | needs_review | modifier_conflict | low |
|----------|------|--------------|-------------------|-----|
| gray_matter | 212 | 152 | 25 | 105 |
| white_matter | 42 | 9 | 0 | 2 |
| cranial_nerve | 2 | 3 | 0 | 0 |
| ventricle | 6 | 1 | 0 | 0 |

gray_matter がボトルネック（low_conf の 98% 超が gray_matter）。

### 3-3. 論文別 high_conf 率

| 論文 | 件数 | high | needs_review | low | high_conf 率 |
|------|------|------|--------------|-----|--------------|
| Adil2021（脳幹 atlas） | 49 | 42 | 6 | 0 | **85.7%** |
| Kiernan2012（側頭葉） | 26 | 21 | 2 | 2 | **80.8%** |
| Agostinelli2023 | 62 | 42 | 13 | 4 | **67.7%** |
| Yelnik2007（基底核） | 31 | 21 | 5 | 3 | **67.7%** |
| TzourioMazoyer2002（AAL） | 45 | 27 | 12 | 4 | **60.0%** |
| Hartig2020（Macaque SARM） | 100 | 55 | 36 | 7 | **55.0%** |
| Yushkevich2009（海馬） | 7 | 5 | 1 | 1 | 71.4% |
| Swanson2018（Rat） | 11 | 5 | 3 | 1 | 45.5% |
| Leergaard2023（Rat WHS） | 33 | 12 | 13 | 1 | 36.4% |
| Hwang2017（視床） | 15 | 6 | 9 | 0 | **40.0%** |
| Rushmore2022（HOA2 皮質） | 73 | 14 | 50 | 5 | **19.2%** |
| **Glasser2016（HCP MMP1.0）** | 107 | 12 | 15 | 79 | **11.2%** |

**所見**

- **古典的 atlas 系**（Adil, AAL, 基底核）は 60〜86% と Core に近い挙動。
- **Glasser2016 / Rushmore2022** の fine-grained parcellation 名が全体を押し下げている（Corpus の主要リスク源）。

---

## 4. Core との整合

| 集合 | 件数 |
|------|------|
| Core ∩ Corpus（名称一致・ユニーク） | 91 |
| exact match（top-1 HOMBA ID） | **91 / 91** |
| mismatch | **0** |

Corpus 上で Core に含まれる名称はすべて RCS v0.3.0 で Core 期待どおりに到達。  
Corpus 評価の課題は **残り 402 ユニーク名称**（論文固有・未キュレーション部分）に集中する。

---

## 5. 改善すべき事項（259 ユニーク名称）

RCS・辞書・スコアリングで改善余地がある項目。Challenge データセット拡充の候補源。

### 5-1. Glasser2016（HCP MMP）名称 — 最優先

79/107 行が low_confidence。HOMBA には近い概念があるが、論文側の命名とずれている。

| クエリ例 | スコア | 現行 top-1 | 改善方向 |
|----------|--------|------------|----------|
| Visual area V3A / V3B / V4 / V8 | 0.54 | sixth visual area | MMP エリア名 → HOMBA 視覚野への alias 追加 |
| Somatosensory area 3a / 3b | 0.54 | somatosensory radiation | 「area 3a」→ primary somatosensory 等 |
| Area PH | 0.53 | subincertal nucleus (area) | 論文固有略称の alias |
| Premotor eye field | 0.55 | frontal eye field of premotor cortex | 近いがスコア不足 → alias で誘導 |
| Area 55b | 0.47 | area 55b of premotor cortex | 部分一致はあるが閾値未満 |

**対策**: `homba_alias_rules.csv` に Glasser MMP 命名パターンをバッチ追加。HCP エリア番号・「Visual area V*」系を優先。

### 5-2. Rushmore2022（HOA2）サブパーセル — 修飾語・括弧

50/73 行が needs_review（多くはスコア 0.88 で親 gyus にマッチ）。粒度が細かすぎて親構造に吸い込まれる。

| クエリ例 | スコア | top-1 | 問題 |
|----------|--------|-------|------|
| Angular gyrus (anterior/posterior) | 0.88 | angular gyrus | サブ区分が落ちる |
| Superior frontal gyrus (lateral anterior) 等 | 0.88 | superior frontal gyrus | 同上 |
| Cuneal cortex | 0.57 | external shell of inferior colliculus | 誤マッチ |
| Central opercular cortex (anterior) | 0.58 | cerebellar lobule | 完全誤マッチ |

**対策**

- 括弧内修飾（anterior / posterior / lateral）のスコア反映強化
- HOA2 固有サブリージョン → HOMBA 最善近似の alias（人手レビュー付き）
- 誤マッチ行は Challenge に登録

### 5-3. 括弧付き・複合修飾名称（89 名称）

parenthetical パターンが improvable タグで最多クラスタの一つ。

代表例:

- `Trigeminal nucleus (motor)` / `(principal sensory)` — 核の subdivision
- `Inferior olive (principal nucleus)` — modifier_conflict（principal が落ちる）
- `Lateral reticular nucleus (magnocellular/parvicellular)` — 層・細胞タイプ指定
- `Thalamus (excluding pulvinar)` — 除外句（後述 §6 も参照）

**対策**: `homba_token_rules.csv` の modifier 処理、括弧内トークンの重み付け、Challenge T-5 系の改善。

### 5-4. modifier_conflict（25 ユニーク）

修飾語と候補の粒度が不一致。Human 14 件、Rat 9 件。

例: `Temporal pole (middle temporal gyrus)` → temporal pole（修飾と候補のズレ）

**対策**: modifier_match_score のチューニング、または subdivision 用 alias。

### 5-5. 視床・皮質下（Hwang2017, Hartig2020 一部）

Hwang2017: high 6/15 のみ。視床核の細分化名称が特定核群 1 つに寄るパターン（Core Challenge の `Thalamic nuclei` と同系）。

**対策**: 視床核群 alias の拡充（ANALYSIS_REPORT_03 §6-1 系）。

### 5-6. 既知 Challenge 名称の Corpus 出現

| 名称 | 種 | 結果 | 備考 |
|------|-----|------|------|
| Arcuate nucleus | Macaque | needs_review 0.79 → 延髄 arcuate nucleus | 視床下部弓状核ではない。種・文脈依存 |

Human 向け Challenge 改善が Macaque 行にはそのまま効かないケース。

---

## 6. 改善が難しい／限定的な事項（33 ユニーク + 構造的要因）

HOMBA・RCS の現設計では、alias  alone では解決しにくい項目。

### 6-1. 種差・オントロジーギャップ（limited: 32 ユニーク）

HOMBA v1 は Human（DHBA）中心。Macaque / Rat 固有 parcellation は**到達率に上限**がある。

| 例 | 種 | スコア | 理由 |
|----|-----|--------|------|
| Lamina terminalis and vascular organ | Macaque | 0.33 | 複合構造・NHP 固有 |
| Centromedian and parafascicular thalamic complex | Macaque | 0.39 | 複数核の束ね表現 |
| Ventral striatal region (unspecified) | Rat | 0.60 | 曖昧ラベル |
| Fields of Forel | Rat | 0.45 | ラット命名と HOMBA の粒度差 |

**対策の現実性**

- Species データセット（`rcs_species.csv`）で `coverage_status=species_specific` として記録
- RCS に species 入力を将来追加するまで、**自動マッピングの期待値を下げる**

### 6-2. 除外・否定構文

| 名称 | 結果 | 限界 |
|------|------|------|
| Thalamus (excluding pulvinar) | 0.88 → thalamus | 「pulvinar を除く」意味を表現する HOMBA エントリなし。Core でも thalamus 近似が正解 |

RCS は除外句を解釈しない。**意図的な近似**として許容するか、Corpus 上は `review_status=approximate` とする。

### 6-3. HOMBA に 1:1 エントリがない fine-grained 区分

- Glasser MMP の一部エリア（HOMBA の cytoarchitectonic 体系と完全一致しない）
- Rushmore HOA2 の HOA サブリージョン（HOMBA より細かい）
- 複数構造の複合名（`A and B thalamic complex`）

**対策**: 「正解」ではなく**最善近似 + 人手 verified** として Corpus を運用。無理な exact match 追求は避ける。

### 6-4. 論文・ atlas 体系の違いそのもの

同一解剖を指していても、Glasser / HOA2 / AAL / HOMBA で**名称体系が異なる**。  
完全自動マッピングの上限は 100% にならない。Corpus の目的はそのギャップを**可視化**すること。

---

## 7. 推奨アクション（優先順）

| 優先 | アクション | 期待効果 |
|------|-----------|----------|
| 1 | `build_rcs_corpus.py` で run1 結果 + Core join → `rcs_corpus.csv` 生成 | Corpus データセット正式化 |
| 2 | Glasser2016 向け alias バッチ（20〜40 ルール） | low_conf 79 件の大半を改善可能 |
| 3 | Rushmore2022 誤マッチ行を Challenge 登録 + HOA2 alias | needs_review / low の精査 |
| 4 | 括弧・修飾語スコア改善（T-3, T-5） | 89 parenthetical 名称 |
| 5 | Species 軸レポート（`rcs_species.csv`） | Macaque/Rat の limited を体系化 |
| 6 | 人手レビュー（Human gray_matter 優先） | verified ラベル付与 |

---

## 8. 成果物一覧

| ファイル | 内容 |
|----------|------|
| `build_core_improve/output/rcs_corpus_source_run1.csv` | RCS 生結果（559行） |
| `build_core_improve/output/rcs_corpus_source_analysis.json` | 集計・分類 JSON |
| `build_testdata/analyze_corpus_run.py` | 再分析スクリプト |
| 本レポート | `build_testdata/reports/CORPUS_REPORT_01.md` |

---

## 9. 再実行方法

```bash
# RCS 実行
python rcs/rcs_test_list.py build_testdata/rcs_corpus_source.csv --top-k 1 \
  --output-csv build_testdata/build_core_improve/output/rcs_corpus_source_runN.csv

# 分析
python build_testdata/analyze_corpus_run.py
```

`analyze_corpus_run.py` 内の `RESULTS_CSV` を新しい run ファイルに差し替えて再集計可能。
