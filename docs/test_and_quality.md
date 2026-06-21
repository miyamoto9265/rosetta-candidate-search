# ROSETTA Candidate Search — テスト・品質管理

**バージョン**: v0.3.0  
**最終更新**: 2026-06-07  
**詳細分析**: `build_testdata/build_core_improve/cursor_playground/ANALYSIS_REPORT/ANALYSIS_REPORT_SUMMARY.md`（LLM-based Recursive Improvement 総括）を参照

---

## 1. 現状精度サマリ（v0.3.0）

### round4_large_scale（213クエリ、最終評価）

| 区分 | 件数 | 割合 |
|---|---|---|
| high_confidence（スコア ≥ 0.90） | **206** | **96.7%** |
| needs_review（0.60 ≤ スコア < 0.90） | 6 | 2.8% |
| low_confidence（スコア < 0.60） | 1 | 0.5% |
| no_result | 0 | 0.0% |

### 既存テストセット（回帰チェック）

| テストセット | high_conf | needs_review | low_conf | 備考 |
|---|---|---|---|---|
| `level1.csv`（50件） | 50/50 = **100%** | 0 | 0 | 回帰なし |
| `round1_comprehensive.csv`（56件） | 52/56 = **92.9%** | 3 | 1 | 回帰なし |

全テストセット通じて v0.3.0 導入後に回帰は検出されていない。

### 精度推移

| ラウンド | 主な変更 | level1 high_conf | round1 high_conf |
|---|---|---|---|
| v0.1.0（初期） | 初期状態 | ~60% | ~60% |
| v0.2.0 | alias 辞書整備（38件）+ exact match penalty 修正 | ~90% | ~85% |
| v0.3.0 | 略語 lookup table + 2-pass scoring | 98% | 92.9% |
| v0.3.0+（辞書追加後） | alias 辞書 41 → 69 件（+28件） | **100%** | **92.9%** |
| round4_large_scale | 213件の新規総合テスト | — | **96.7%** |

---

## 2. テストインフラストラクチャ

テスト関連資産は **`build_testdata/`**（データセット）と **`rcs/`**（RCS エンジン）に分かれている。

| レイヤ | パス | 役割 |
|--------|------|------|
| RCS エンジン | `rcs/` | アルゴリズム本体・辞書・HOMBA データ・テスト CLI |
| データセット | `build_testdata/rcs_*.csv` | Core / Challenge / Species / Corpus |
| LLM-based Recursive Improvement | `build_testdata/build_core_improve/` | Round 別テスト入力・出力・分析ツール |
| 本番 | `web/backend/lambda_function.py` + `rcs/`（zip 同梱） | Lambda HTTP アダプター |

詳細なデータセット計画・プロセス命名は `build_testdata/PLAN.md` を参照。v0.3.0 の精度は LLM-based Recursive Improvement（Round 0–4）の成果。

### ディレクトリ構成

```
rcs/                              ← RCS エンジン（開発の正本）
  rosetta_candidate_generator.py
  homba_alias_rules.csv
  homba_abbrev_rules.csv
  homba_token_rules.csv
  HOMBA_v1_fixed.csv
  rcs_test_list.py
  rcs_test_interactive.py
  review.py                       ← review_flag（Lambda / CLI 共通）

build_testdata/
  PLAN.md
  build_rcs_core.py
  rcs_core.csv
  rcs_challenge.csv
  rcs_corpus_source.csv
  build_core_improve/
    input/                        ← ラウンド別テスト入力 CSV
    output/                       ← rcs_test_list の実行結果
    cursor_playground/            ← 分析・比較ツール（cursor_*）
      cursor_rcs_paths.py         ← rcs/ へのパス定義
      cursor_analyze_results.py
      cursor_compare_results.py
      cursor_check_abbrev.py
      cursor_check_regressions.py
      cursor_search_homba.py
      ANALYSIS_REPORT/
```

### テスト入力ファイル（`build_core_improve/input/`）

| ファイル | クエリ数 | 内容 |
|---|---|---|
| `level1.csv` | 50 | 基本的な脳構造名 |
| `round1_comprehensive.csv` | 56 | 一般的〜やや難しい名称 |
| `round3_edge_cases.csv` | 48 | エッジケース・略語 |
| `round4_large_scale.csv` | 217 | 包括的テスト（最終評価用） |

### Core データセットのビルド

```bash
cd build_testdata
python build_rcs_core.py
```

`build_core_improve/input/` を統合し、`rcs_core.csv` と `rcs_challenge.csv` を生成する。

---

## 3. テスト実行方法

### バッチテスト（推奨）

リポジトリルートから:

```bash
python rcs/rcs_test_list.py build_testdata/build_core_improve/input/round4_large_scale.csv
```

出力は `build_testdata/build_core_improve/output/round4_large_scale_YYYYMMDD_HHMMSS.csv` に保存される。

オプション:
```bash
python rcs/rcs_test_list.py build_testdata/build_core_improve/input/round4_large_scale.csv --top-k 3
python rcs/rcs_test_list.py build_testdata/build_core_improve/input/round4_large_scale.csv --dhba-filter with
```

Core データセットを直接テストする場合:

```bash
python rcs/rcs_test_list.py build_testdata/rcs_core.csv --output-csv build_testdata/build_core_improve/output/rcs_core_result.csv
```

### 精度分類

```bash
cd build_testdata/build_core_improve/cursor_playground
python cursor_analyze_results.py ../output/round4_large_scale_YYYYMMDD_HHMMSS.csv
```

### 対話型テスト

```bash
python rcs/rcs_test_interactive.py
# query> LC
# query> Wernicke's area
```

### 特定クエリの上位 N 件確認

```bash
python cursor_check_abbrev.py
# コード内の queries リストを編集して使用
```

### 2 回分の結果比較

```bash
python cursor_compare_results.py \
  ../output/round4_large_scale_旧.csv \
  ../output/round4_large_scale_新.csv
```

---

## 4. 開発→本番への反映手順

`rcs/` が唯一の正本。Lambda は `scripts/package_lambda.ps1`（または `.sh`）で `rcs/` を zip 同梱してデプロイする。

| 開発版（`rcs/`） | 本番への反映 |
|---|---|
| `rcs/rosetta_candidate_generator.py` | zip 同梱（手動コピー不要） |
| `rcs/review.py` | zip 同梱 |
| `rcs/homba_alias_rules.csv` | S3 `homba_alias_rules.csv` |
| `rcs/homba_abbrev_rules.csv` | S3 `homba_abbrev_rules.csv` |
| `web/backend/lambda_function.py` | zip に含める（HTTP/S3 アダプター） |

Lambda への反映手順は `docs/aws_operations_guide.md` の「4. データファイルの更新手順」を参照。
---

## 5. 残存課題・優先度

### 優先度：高

| タスク | 内容 |
|---|---|
| T-1. HOMBA エントリ整備 | `brainstem`（単一エントリなし）、`limbic system`（機能的概念）、`IFOF`（HOMBA ギャップ）— HOMBA 管理者対応が必要 |
| T-2. 曖昧語の文脈依存解決 | `arcuate nucleus`（視床下部 vs 延髄）、`septum`、`paraventricular nucleus` — コンテキスト情報なしでは解決困難 |
| T-3. Curly quote 正規化 | `normalize_text` に U+2019（`'`）の削除を追加。`Wernicke's area` 等の curly quote 入力に対応 |

### 優先度：中

| タスク | 内容 |
|---|---|
| T-4. 汎用名称の曖昧解消 | `visual cortex`/`auditory cortex`/`somatosensory cortex` が現在 primary を返す。HOMBA 親ノード整備で改善可能 |
| T-5. Latin suffix 正規化の拡張 | `rostralis`、`ventralis`、`dorsalis` 等のラテン形容詞 → 英語形への変換（2〜5件の追加で対応可） |
| T-6. IFOF 代替マッピング | HOMBA に IFOF がない間の暫定 alias（external capsule? extreme capsule?）を検討 |
| T-7. HOMBA 略称の逆引きルール追加 | HOMBA が正式名に `HTH`、`CP` 等の略称を含む場合のスコア低下対応 |

### 優先度：低

| タスク | 内容 |
|---|---|
| T-8. Brodmann 領野の alias 拡充 | BA17、BA22、BA44 等（BA4 は対応済み） |
| T-9. 複数候補ランキングの説明強化 | なぜこの順序か を説明するデバッグ機能 |

---

## 6. RCS の強みと弱み

### 強み（高精度）

- 標準的な解剖学用語（基本脳構造名）
- 略語（LC、NTS、PAG、VTA、SNc/SNr 等）— `homba_abbrev_rules.csv` で対応
- 同義語・別表記（locus ceruleus、pallidum、medulla 等）— `homba_alias_rules.csv` で対応
- Laterality 付きクエリ（left hippocampus 等）
- 括弧付きクエリ（thalamus excluding pulvinar、nucleus accumbens shell 等）
- エポニム（Broca's area、Wernicke's area）
- 白質路（corpus callosum、fornix、SLF 等）

### 弱み（要人手確認）

- HOMBA にエントリが存在しない概念（limbic system、brainstem、IFOF）
- 同名の複数構造が存在する場合（arcuate nucleus、septum）
- HOMBA の命名規則が一般的な術語と大きく乖離している場合
