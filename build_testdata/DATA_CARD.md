# build_testdata — データカード

**更新**: 2026-06-07  
**対象**: RCS（ROSETTA Candidate Search）評価用テストデータ一式（`build_testdata/`）

---

## 全体像

`build_testdata/` は、RCS の精度・回帰を用途別に測る **4 データセット**（Core / Challenge / Species / Corpus）と、その生成物・中間資産を置くディレクトリである。いずれも HOMBA v1（Human / DHBA 中心）への名称マッピングを前提とする。

| データセット | 出力 CSV | 件数 | 検証状況 |
|--------------|----------|------|----------|
| **Core** | `rcs_core.csv` | 230 | **検証済み** |
| **Challenge** | `rcs_challenge.csv` | 13 | 未検証 |
| **Species** | `rcs_species.csv` | 555 | 未検証 |
| **Corpus** | `rcs_corpus.csv` | 415 | 未検証 |

「検証済み」とは、LLM-based Recursive Improvement の各 Round で RCS を反復実行し、期待 HOMBA ID・スコア分布・回帰が確認された状態を指す。Core 以外は、ファイルは存在するが **正式な評価サイクル・人手レビューは未実施** とする。

---

## Core — 標準名称集

| 項目 | 内容 |
|------|------|
| **ファイル** | `rcs_core.csv` |
| **件数** | 230（ユニーク `structure_name`） |
| **検証** | **検証済み** |
| **スキーマ** | `structure_name`, `expected_homba_id`, `expected_homba_name`, `notes` |
| **ビルド** | `build_rcs_core.py` |

### 経緯

Core は **LLM-based Recursive Improvement**（テスト → 問題分析 → 辞書・アルゴリズム修正 → 再テスト）の**主要な成果物**である。

2026-05-17 頃、`build_core_improve/` 上で Cursor LLM エージェントが RCS を段階的に改善した。Round 0（環境構築）から Round 4（大規模検証）まで、テスト CSV を用意して実行し、`ANALYSIS_REPORT_01–03` に失敗パターンを分類、`rcs/homba_alias_rules.csv`（4 → 69 ルール）や 2-pass scoring などを反映した。

各 Round で使った入力名称を `build_core_improve/input/` に蓄積し、重複排除して **230 ユニーク名称** に統合したのが `rcs_core.csv` である。

| 入力ソース | 件数 | 性格 |
|------------|------|------|
| `level1.csv` | 50 | 基本構造名 |
| `round1_comprehensive.csv` | 56 | 一般〜中程度 |
| `round3_edge_cases.csv` | 48 | エッジケース |
| `round4_large_scale.csv` | 217 | 大規模包括（12 カテゴリ） |

### 現状

- 全 230 行に `expected_homba_id` が埋まっている（手動上書き 8 件 + RCS top-1 解決）。
- 改善後ベースライン: level1 **100%** high_confidence、大規模テスト（213 件）**96.7%** high_confidence（`ANALYSIS_REPORT_SUMMARY.md`）。
- `notes` は主にカテゴリタグ（cortex, fiber_tract, basal_ganglia, abbrev 等）。完全網羅・ゴールドスタンダードを目指した集合ではない。

### 領域カバレッジ（おおよそ）

大脳皮質・皮質下・視床・海馬・小脳・脳幹・白質路・脳神経など、**ヒト文献で頻出する標準名称**を横断的に含む。入力ラウンドごとに偏重はあるが、単一アトラスへの依存はない。

---

## Challenge — 改善課題集

| 項目 | 内容 |
|------|------|
| **ファイル** | `rcs_challenge.csv` |
| **件数** | 13 |
| **検証** | **未検証** |
| **スキーマ** | `structure_name`, `expected_homba_id`, `expected_homba_name`, `notes`, `由来` |
| **生成** | `build_rcs_core.py` が Core ビルド時に自動分離 |

### 経緯

Challenge は Core 統合の副産物である。LLM-based Recursive Improvement の過程で投入した名称のうち、**現行 RCS 出力をそのまま正解にできない**、または **期待 HOMBA ID を一意に定められない**行を `ISSUE_RECORDS` として識別し、Core（`rcs_core.csv`）から切り出した。

`由来` 列は一律「LLM-based Recursive Improvement において Core へ収録できなかったレコード」。`ANALYSIS_REPORT_03` の失敗パターン（T-1〜T-8：HOMBA ギャップ、同名複数構造、修飾語脱落、括弧未反映、集合名詞の過剰特化 等）に対応する。

### 現状

- `expected_homba_id` は **全件空**（改善後に到達すべき ID は未定義）。
- 代表例: Brainstem, Limbic system, Septum, Arcuate nucleus, Motor cortex, Lenticular nucleus, Thalamic nuclei 等。
- 用途はリグレッション第一検証ではなく、**辞書・HOMBA・スコア改善の課題トラッキング**用。

---

## Corpus — 論文コーパス（Human）

| 項目 | 内容 |
|------|------|
| **ファイル** | `rcs_corpus.csv` |
| **件数** | 415 行 / **379** ユニーク名称 |
| **検証** | **未検証** |
| **スキーマ** | `structure_name`, `species`, `paper` |

### 経緯

1. **論文発見**: LLM による文献調査で候補を洗い出した（一覧は `archive/articles/文献整理.md`）。
2. **PDF 選定**: 候補のうち対象論文の PDF を**人手で選定・ダウンロード**した。
3. **名称抽出**: 各論文の Methods / Figure 等から脳部位名称を**LLM により自動抽出**した。手作業転記ではない。
4. **整形**: 抽出結果を統合し、Macaque / Rat 分を Species へ移管したうえで Human のみを `rcs_corpus.csv` に整理した（旧称 `rcs_corpus_source.csv` は廃止）。

当初は Macaque / Rat 論文分も含んでいたが、種別カバレッジ用途と分離するため **Macaque 100 件・Rat 44 件を Species 側へ移管**し、現行は **Human のみ**。

### 現状 — データ数・出典

| 論文 ID | 件数 | アトラス・領域 |
|---------|------|----------------|
| Glasser2016 | 107 | ヒト大脳皮質（HCP MMP1.0 代表エリア） |
| Rushmore2022 | 73 | ヒト大脳皮質（hHOA2.0 サブリージョン） |
| Agostinelli2023 | 62 | 脳幹・小脳（細胞構築・化学構築） |
| Adil2021 | 49 | 脳幹（MRI インタラクティブアトラス） |
| TzourioMazoyer2002 | 45 | 全脳（AAL） |
| Yelnik2007 | 31 | 基底核・視床・白質 |
| Kiernan2012 | 26 | 側頭葉・海馬形成 |
| Hwang2017 | 15 | 視床核 |
| Yushkevich2009 | 7 | 海馬サブフィールド |

**カテゴリ内訳**: gray_matter 363 / white_matter 42 / cranial_nerve 5 / ventricle 5

**Core との関係**（名称一致）: Core ∩ Corpus **82** / Corpus のみ **297** / Core のみ **148**

### 補足資産

- `build_core_improve/output/rcs_corpus_source_run1.csv` — 旧 `rcs_corpus_source.csv` 構成での探索的 RCS 実行結果（現行 `rcs_corpus.csv` とはスキーマ・件数が異なる場合あり）

---

## Species — 種別カバレッジ（Macaque / Rat）

| 項目 | 内容 |
|------|------|
| **ファイル** | `rcs_species.csv` |
| **件数** | 555 行 / **542** ユニーク名称 |
| **検証** | **未検証** |
| **スキーマ** | `structure_name`, `species`, `source_atlas`, `category`, `expected_homba_id`, `expected_homba_name`, `coverage_status`, `notes` |
| **ビルド** | `build_rcs_species.py` |

### 経緯

HOMBA が Human 中心である前提で、**非ヒトの既存アトラス名称**がどこまで HOMBA に届くかを測るデータセット。テイラーメイドの名称リストは作らず、**公式ラベルファイル**と論文抽出 seed を組み合わせる方針。Allen Brain Atlas 系は対象外。Corpus とは分離（動物種レコードは Corpus に含めない）。

### 現状 — 種別・出典

| 種 | 件数 | 主な `source_atlas` | 由来 |
|----|------|---------------------|------|
| **Macaque** | 298 | SARM 158 / Hartig2020_SARM 100 / mHOA2 40 | 皮質下＋皮質 |
| **Rat** | 257 | WaxholmSpace_v4 213 / Leergaard2023_WHS 33 / Swanson2018 11 | 全脳 WHS ＋ seed |

#### 各 `source_atlas` の説明

| `source_atlas` | 種 | 正式名称・論文 | 何のアトラスか | 領域・規模 | データの取り方 |
|----------------|-----|----------------|----------------|------------|----------------|
| **SARM** | Macaque | Hartig et al. 2021 — *Subcortical Atlas of the Rhesus Macaque* | マカク**皮質下**の MRI パーセレーション。Paxinos 系命名に準拠 | 210 primary ROI（Level 6 で 206 名称）— 線条体・視床・海馬・扁桃体・視床下部・中脳・小脳など | 公式 `SARM_key_table.csv`（AFNI 配布）をパース |
| **Hartig2020_SARM** | Macaque | 上記 SARM の NeuroImage 2020 論文（Corpus 時代の paper ID） | SARM と**同一アトラス**の論文由来名称 | 皮質下中心。修飾付き・複合表記が多い（例: 扁桃体亜区の dorsal/ventral） | 旧 `rcs_corpus_source.csv` から LLM 抽出で移管した **seed**（100 件）。SARM 公式ラベルと重複マージ |
| **mHOA2** | Macaque | Rushmore et al. 2022 — *HOA2.0-ComPaRe*（Frontiers in Neuroanatomy） | マカク**大脳皮質**の Harvard-Oxford 系パーセレーション（mHOA2.0） | **40 PU** — 前頭・頭頂・側頭・後頭・帯状・島・辺縁系オペキュラ | 論文 Table 6 の PU 一覧を `mHOA2_parcellation_units.csv` 化 |
| **WaxholmSpace_v4** | Rat | Papp et al. 2014 / Leergaard et al. 2023 — *Waxholm Space atlas*（EBRAINS 標準） | ラット全脳の**人口ベース MRI アトラス**（Sprague Dawley） | **222 構造** — 皮質・海馬・線条体・視床・視床下部・中脳・小脳・白質路など | NITRC の `WHS_SD_rat_atlas_v4.label` をパース |
| **Leergaard2023_WHS** | Rat | Leergaard et al. 2023 — WHS v4 拡張論文 | 上記 Waxholm Space の**追補・改訂**（線条体・視床・中脳の細分化など） | WHS v4 の一部領域をより細かく記述した名称 | 旧 Corpus から移管した **seed**（33 件）。WaxholmSpace_v4 と重複マージ |
| **Swanson2018_BrainMaps4** | Rat | Swanson 2018 — *Brain maps 4.0*（rat brain nomenclature ontology） | ラット脳の**命名法オントロジー**（解剖学図譜・文献体系） | 全脳の概念名・サブリージョン（WHS とは**別体系**） | 旧 Corpus から移管した **seed**（11 件）。オントロジー全体のサンプル |

**入力資産**（`species_sources/`）:

| ファイル | 内容 |
|----------|------|
| `rcs_species_seed.csv` | 旧 Corpus から移管した論文抽出 144 件 |
| `atlas_labels/SARM_key_table.csv` | SARM Level 6（AFNI 配布） |
| `atlas_labels/mHOA2_parcellation_units.csv` | mHOA2.0 40 PU（Rushmore2022 Table 6） |
| `atlas_labels/WHS_SD_rat_atlas_v4.label` | Waxholm Space v4 222 構造（NITRC） |

### 領域カバレッジ（おおよそ）

**Macaque**

- **皮質下（SARM）**: 線条体・視床・海馬・扁桃体・視床下部・中脳・小脳など皮質下〜脳幹
- **皮質（mHOA2.0）**: 前頭・頭頂・側頭・後頭・帯状・島・辺縁系オペキュラ 40 PU
- seed（Hartig2020）: SARM 論文由来の表記ゆれ・修飾付き名称

**Rat**

- **全脳（Waxholm Space v4）**: 皮質・海馬・線条体・視床・視床下部・中脳・小脳・白質路など 222 構造
- seed（Leergaard2023 / Swanson2018）: WHS 拡張論文・Brain Maps 4.0 オントロジーのサンプル

**カテゴリ内訳**: gray_matter 469 / white_matter 75 / ventricle 10（他 1）

### 期待値・カバレッジ（暫定・未検証）

- `expected_homba_id` は RCS top-1 で**機械仮埋め**（全 555 行 filled）。
- `coverage_status` もスコア閾値による**自動暫定**: mapped 222 / approximate 258 / unmapped 75。
- 人手レビュー・`species_specific` タグ付けは未実施。

---

## ディレクトリ構成（主要ファイル）

```
build_testdata/
  DATA_CARD.md              ← 本ドキュメント
  PLAN.md                   ← 整備計画（設計メモ）
  rcs_core.csv              ← Core（検証済み）
  rcs_challenge.csv         ← Challenge（未検証）
  rcs_species.csv           ← Species（未検証）
  rcs_corpus.csv            ← Corpus（未検証）
  build_rcs_core.py
  build_rcs_species.py
  species_sources/            ← Species 入力
  build_core_improve/         ← LLM-based Recursive Improvement 作業痕跡
    input/                    ← Core 元入力
    output/                   ← 各 Round 実行結果
    cursor_playground/        ← 分析スクリプト・ANALYSIS_REPORT
```

---

## 参照

| ドキュメント | 内容 |
|--------------|------|
| `build_core_improve/cursor_playground/ANALYSIS_REPORT/ANALYSIS_REPORT_SUMMARY.md` | Core 改善プロセス総括 |
| `PLAN.md` | 4 データセットの設計・スキーマ定義 |
| `species_sources/README.md` | Species アトラスラベルの入手元 |
| `archive/articles/文献整理.md` | Corpus / Species 論文選定の背景 |
