# ROSETTA Candidate Search — LLM-based Recursive Improvement 総括レポート

**期間**: 2026-05-17  
**対象**: `rcs/` および `build_testdata/build_core_improve/` における RCS の検証・改善  
**ベース**: ANALYSIS_REPORT_01 / 02 / 03 を統合

---

## 1. 何をしたか（全体像）

HOMBA 脳部位辞書へのクエリマッチングエンジン（RCS）を、`rcs/` + `build_core_improve/` 上で **LLM-based Recursive Improvement**（テスト → 問題分析 → 修正 → 再テスト）により段階的に改善した。Cursor 上の LLM エージェントが各 Round の分析・修正案を起草し、検証結果を次 Round の入力とした。

```
┌─────────────────────────────────────────────────────────────────┐
│  改善前（v0.1.0）                                                │
│  alias 4件 / 略語なし / 1-pass scoring                          │
│  → level1 約60% high_confidence、多数の誤マッチ・低スコア       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
    Round 0: playground セットアップ
    Round 1: 包括テスト(50件) → 問題パターン抽出
    Round 2: alias 拡充 + exact match penalty 修正 (v0.2.0)
    Round 2.5: 2-pass scoring + 略語テーブル (v0.3.0)
    Round 3: エッジケース(44件) + 大規模テスト(213件) + alias 追加
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  改善後（v0.3.0+）                                               │
│  alias 69件 / abbrev 37件 / 2-pass scoring                      │
│  → level1 100%、大規模テスト 96.7% high_confidence             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 改善前：何が問題だったか

改善前の RCS は、文献で使われる一般的な脳部位名と HOMBA の命名規則のズレにより、以下の5パターンで失敗していた。

| パターン | 典型例 | 症状 |
|---------|--------|------|
| **A. 命名差異** | Habenula → habenular nuclei、Insula → insular lobe | 誤マッチ or 低スコア |
| **B. hierarchy 過昇格** | Dentate nucleus → cerebellar deep nuclei (0.97) が正解を上回る | 親ノードが子より高スコア |
| **C. specificity_penalty 誤作動** | Locus coeruleus → nucleus coeruleus (0.86) | exact match でも減点 |
| **D. 略語・別綴り欠如** | STN マッチなし、grey/gray 不一致 | マッチ不能 or 低スコア |
| **E. HOMBA エントリ不在** | Limbic system、Brainstem | 対応構造が存在しない |

**改善前の資産**: `homba_alias_rules.csv` 4ルールのみ。略語テーブルなし。スコア計算は 1-pass（親昇格に penalty 前の raw score を使用）。

---

## 3. LLM-based Recursive Improvement の各 Round

### Phase 0 — 環境構築（Round 0）

- 本体 `rosetta_candidate_generator.py` と HOMBA データを playground にコピー
- バッチテスト（`rcs_test_list.py`）、結果比較（`cursor_compare_results.py`）、HOMBA 検索ヘルパーを整備

### Phase 1 — 問題の体系的把握（Round 1）

- **包括テスト CSV**（50クエリ）を作成し RCS を実行
- 上記5パターンを分類・文書化
- 改善の優先順位を設定

### Phase 2 — 辞書拡充 + 初回アルゴリズム修正（Round 2 → v0.2.0）

**辞書**: `homba_alias_rules.csv` を 4 → **38ルール**に拡充  
（命名差異、小脳深部核、扁桃体、pars compacta/reticulata、略語 STN、ラテン語語尾 caudalis 等）

**アルゴリズム**: exact match 時に `_specificity_penalty` を適用しないよう修正

```python
# 変更: exact match では penalty をスキップ
if not exact:
    final_score *= self._specificity_penalty(...)
```

**効果（この時点）**:

| テストセット | 改善 | 悪化 |
|------------|------|------|
| level1（50件） | +8 | 0 |
| round1_comprehensive（50件） | +26 | 0 |
| round3_edge_cases（44件） | +20 | 1 |

### Phase 3 — 構造的改善（Round 2.5 → v0.3.0）

Phase 2 で残った課題（hierarchy 過昇格の根本対策、2文字略語 LC 等）に対処。

| 変更 | 内容 |
|------|------|
| **2-pass scoring** | Pass 1 で全候補の final score を先に算出 → その score で親を昇格 → Pass 2 で最終ランキング |
| **略語テーブル新設** | `homba_abbrev_rules.csv`（37ルール、**query のみ**展開。HOMBA alias を汚染しない） |
| **penalty 条件精緻化** | pure hierarchy_parent 候補への二重ペナルティを除外 |
| **alias 追加** | insular cortex、raphe nuclei（2-pass 導入後の regression 修正） |

**効果（Phase 2 からの増分）**: LC・NTS が新規マッチ（1.0）。累計で round1 に +2 新規マッチ。

### Phase 4 — 大規模検証 + 辞書最終拡充（Round 3）

- **エッジケース CSV**（44クエリ）で回帰確認
- **大規模テスト CSV**（213クエリ、12カテゴリ）を新規作成
- `homba_alias_rules.csv` を 41 → **69ルール**（+28件：白質路、視床核、エポニム、皮質汎用名、別綴り等）

**大規模テスト結果（最終）**:

| 区分 | 件数 | 割合 |
|------|------|------|
| high_confidence（≥0.90） | **206** | **96.7%** |
| needs_review | 6 | 2.8% |
| low_confidence | 1 | 0.5% |
| no_result | 0 | 0% |

**回帰チェック**: level1 **100%**（50/50）、round1 **92.9%**（52/56）— 悪化なし。

---

## 4. 改善後：何がどうなったか

### 数値の変遷

| 段階 | 主な変更 | level1 high_conf | 大規模テスト |
|------|---------|-----------------|-------------|
| 改善前 (v0.1.0) | 初期状態 | ~60% | — |
| Phase 2 (v0.2.0) | alias 38件 + penalty 修正 | ~90% | — |
| Phase 3 (v0.3.0) | abbrev + 2-pass | ~98% | — |
| Phase 4 (v0.3.0+) | alias 69件 | **100%** | **96.7%** |

### 代表的な改善事例

| クエリ | 改善前 | 改善後 |
|--------|---------|---------|
| Vestibular nucleus | afferent nuclei... 0.97 ❌ | vestibular nuclei in pons 1.0 ✓ |
| Dentate / Fastigial nucleus | cerebellar deep nuclei 0.97 ❌ | 各深部核 1.0 ✓ |
| Central / Basolateral amygdala | regions of amygdaloid... 0.95–0.97 ❌ | 各正解核 1.0 ✓ |
| STN / LC / NTS | マッチなし | 1.0 ✓ |
| Substantia nigra pars compacta | substantia nigra 0.83 ❌ | SN compact division 1.0 ✓ |
| Raphe nuclei | pontine raphe 0.83 ❌ | raphe nuclei in midbrain 1.0 ✓ |

### 最終的な変更資産

| ファイル | 改善前 → 後 |
|---------|-------------|
| `homba_alias_rules.csv` | 4 → **69ルール** |
| `homba_abbrev_rules.csv` | なし → **37ルール**（新規） |
| `rosetta_candidate_generator.py` | v0.1.0 → **v0.3.0**（2-pass scoring、abbrev 対応、penalty 精緻化） |
| テスト CSV | level1 のみ → level1 + comprehensive + edge_cases + **large_scale(213件)** |
| **Core**（`rcs_core.csv`） | 上記 Round の入力を統合した標準名称集（230件） |

---

## 5. まだ残っていること

RCS のコアアルゴリズムは実用レベルに達したが、以下は辞書や HOMBA 側の整備が必要な領域。

### 解決困難（HOMBA ギャップ・意味的曖昧性）

| クエリ | スコア | 原因 |
|--------|--------|------|
| Limbic system | 0.24 | 機能的概念。HOMBA に単一エントリなし |
| Brainstem | 0.76 | midbrain/pons/medulla の集合。単一エントリなし |
| IFOF | 0.61（誤マッチ） | HOMBA にエントリ不在 |
| Septum | 0.60 | septum pellucidum vs septal area の曖昧性 |
| Arcuate nucleus | 0.79 | 視床下部 vs 延髄の同名構造 |

### 今後の改善候補（優先度順）

1. **HOMBA エントリ整備** — brainstem、limbic system、IFOF 等
2. **曖昧語の文脈依存解決** — arcuate nucleus、septum 等
3. **正規化の体系化** — curly quote 所有格、grey/gray、ラテン語語尾（-alis/-al）を個別 alias から `normalize_text` へ
4. **エポニム・Brodmann 領野** — 個別 alias で一部対応済み。体系テーブル化が望ましい
5. **alias 双方向展開のバリデーション** — target が source を含む規則での junk alias 生成（実害は限定的）

---

## 6. 本番反映時の注意

playground で検証済みの変更を本番に適用する際：

1. **`homba_alias_rules.csv`**（ルート）と **`homba_abbrev_rules.csv`**（`rosetta_candidate_generator.py` と同ディレクトリ）を反映
2. **`rosetta_candidate_generator.py`** の v0.3.0 変更（2-pass scoring、abbrev 対応、penalty 条件）を同期
3. **`web/backend/lambda_function.py`** に同一ロジックが inline コピーされているため、VERSION 含め両方を更新
4. alias_rules の**双方向展開**による副作用を確認してから反映
5. 既存テストセット + round4_large_scale で**回帰テスト**を実施

---

## 7. 結論

| 観点 | 改善前 | 改善後 |
|------|---------|---------|
| **精度** | 基準テスト ~60% | level1 100%、大規模 96.7% |
| **誤マッチ** | hierarchy 過昇格が頻発 | ほぼ解消（2-pass + alias） |
| **略語** | 未対応（STN, LC 等） | 37件の query-only テーブルで対応 |
| **辞書** | 4 alias rules | 69 alias + 37 abbrev |
| **アルゴリズム** | 1-pass、penalty 誤作動あり | 2-pass、penalty 条件精緻化 |
| **弱点** | 全般的に低精度 | HOMBA ギャップ・意味的曖昧性・機能的概念に限定 |

**LLM-based Recursive Improvement の成果**: テスト駆動で問題パターンを分類し、辞書拡充（主要手段）とアルゴリズム修正（2-pass scoring、penalty 除外）を段階的に適用することで、実用レベルの精度を達成した。成果は **Core**（`rcs_core.csv`）として結晶化されている。残課題は主に HOMBA データ側の整備と、コンテキストなしでは解決できない曖昧語への方針設計に集約される。

---

*出典: ANALYSIS_REPORT_01.md（Round 1–2）、ANALYSIS_REPORT_02.md（Round 2.5 / v0.3.0）、ANALYSIS_REPORT_03.md（Round 3–4 / 大規模検証）*
