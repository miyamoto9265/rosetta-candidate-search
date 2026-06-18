# ROSETTA Candidate Search — 分析・改善レポート

**日付**: 2026-05-17  
**対象**: LLM-based Recursive Improvement — Round 1–2（`cursor_playground`）  
**スコープ**: alias辞書の拡充 + スコア計算の改善（ロジック本体の軽微な修正）

---

## 1. 実施内容の概要

LLM-based Recursive Improvement の Round 1–2 として、`cursor_playground` 上で以下のサイクルを実施した。

| サイクル | 内容 |
|----------|------|
| Round 0 | playground セットアップ（ファイルコピー、スクリプト整備） |
| Round 1 | 包括的テストCSV作成（50クエリ）→ RCS実行 → 問題抽出 |
| Round 2 | alias rules 追加（23ルール）→ 再テスト → 効果検証 |
| Round 3 | edge caseテストCSV作成（44クエリ）→ スコア計算修正 + alias追加 → 最終検証 |

**最終状態（元バージョン比）**

| テストセット | 改善 | 悪化 | 新規マッチ |
|------------|------|------|-----------|
| level1.csv（50クエリ） | +8 | 0 | 0 |
| round1_comprehensive（50クエリ） | +26 | 0 | +1 |
| round3_edge_cases（44クエリ） | +20 | 1 | 0 |

---

## 2. 発見した問題パターン

### パターン A: 用語の命名差異（HOMBA固有の表現）

HOMBA の命名規則が一般的な文献用語と異なるため、そのままでは低スコアや誤マッチになる。

| クエリ | 誤マッチ（改善前） | 正解HOMBA | 根本原因 |
|--------|-------------------|-----------|---------|
| Habenula | habenular triangle (0.52) | habenular nuclei | HOMBAは "habenular nuclei"、一般用語は "habenula" |
| Insula | limen insula (0.69) | insular lobe | HOMBAは "insular lobe"、一般用語は "insula" |
| Cingulate gyrus | paracingulate gyrus (0.77) | cingulate cortex | HOMBAは "cingulate cortex"、文献では "gyrus" も使用 |
| Inferior olivary nucleus | inferior olive (0.80) | inferior olive | 同一構造の名称差（olivary nucleus vs olive） |
| Pituitary gland | pituitary body/gland (0.77) | pituitary body/gland | スコアが低いだけで正解はマッチしていた |
| Pulvinar nucleus | pulvinar of thalamus (0.74) | pulvinar of thalamus | 同上 |

### パターン B: hierarchy_parent 過昇格（アルゴリズム設計の課題）

複数の具体的な構造名が同一の親を持つ場合、`_promote_common_parents` が親ノードを raw スコア + 0.08 で昇格させる。一方、正解の直接マッチは `_specificity_penalty`（= 0.86）で減点される。結果として **親（0.97）が正解（0.86）を上回る** 現象が多数発生していた。

典型例（改善前）：

| クエリ | 誤1位 | 正解（2〜3位） |
|--------|--------|--------------|
| Vestibular nucleus | afferent nuclei of cranial nerves in pons (0.97) | vestibular nuclei in pons (0.97) |
| Dentate nucleus | cerebellar deep nuclei (0.97) | dentate (lateral) nucleus (0.86) |
| Fastigial nucleus | cerebellar deep nuclei (0.97) | fastigial (medial) nucleus (0.86) |
| Central amygdala | regions of amygdaloid complex (0.95) | central nucleus of amygdala (0.86) |
| Basolateral amygdala | regions of amygdaloid complex (0.97) | basolateral nuclear group (0.86) |
| Substantia nigra pars compacta | substantia nigra (0.83) | SN compact division (0.67) |

### パターン C: specificity_penalty の誤作動

`_specificity_penalty` は「クエリよりも候補が詳細すぎる」場合にスコアを 0.86 倍にする機能だが、以下のケースで誤作動する：

- クエリに含まれない "nucleus"（weak term）が候補の alias に含まれる場合  
  例：`Locus coeruleus` → `nucleus coeruleus (locus coeruleus)` で "nucleus" が extra specificity と判定されペナルティ
- クエリに含まれない directional term（"lateral"、"medial" 等）が括弧内で展開された alias にある場合  
  例：`Dentate nucleus` → `dentate (lateral) nucleus` で "lateral" がペナルティを引き起こす

### パターン D: 略語・別綴り対応の欠如

| クエリ | 問題 | 改善後 |
|--------|------|--------|
| STN | マッチなし（HOMBAの略語は STH） | subthalamic nucleus (1.0) |
| LC | マッチなし（HOMBAの略語は NC） | ※未対応（2文字略語はリスク高） |
| Periaqueductal grey | 0.65（"gray"とスペルが違う） | 0.94 |
| Spinal trigeminal nucleus caudalis | 0.77（"caudalis" ≠ "caudal"） | 1.0 |

### パターン E: HOMABに直接対応するエントリがない用語

以下は HOMBA の構成上、直接一対一でマッピングできる用語が存在しない：

| クエリ | 状況 |
|--------|------|
| Limbic system | HOMBA にエントリなし（機能的集合体） |
| Brainstem | 単一エントリなし（midbrain + pons + medulla の集合） |
| Wernicke area | 直接対応なし（planum temporale に近似マッピング） |
| Broca area | 直接対応なし（ventrolateral prefrontal cortex に括弧内で言及） |

---

## 3. 実施した対応

### 3-1. alias rules の拡充（homba_alias_rules.csv: 4 → 38 ルール）

```
【命名差異の解消】
habenula → habenular nuclei
insula → insular lobe
cingulate gyrus → cingulate cortex
vestibular nucleus → vestibular nuclei in pons
inferior olivary nucleus → inferior olive
pituitary gland → pituitary body
pulvinar nucleus → pulvinar of thalamus

【階層昇格問題への対処（alias + scoring fix の組み合わせ）】
dentate nucleus → dentate lateral nucleus
fastigial nucleus → fastigial medial nucleus
globose nucleus → medial interpositus globose nucleus
emboliform nucleus → lateral interpositus emboliform nucleus
central amygdala → central nucleus of amygdala
basolateral amygdala → basolateral nuclear group of amygdala

【pars X 表記の対応】
pars compacta → compact division
pars reticulata → reticular division

【略語・別綴り】
stn → subthalamic nucleus
caudalis → caudal
oralis → oral
interpolaris → interpolar
periaqueductal grey → periaqueductal gray

【同義語・別名称】
nucleus of the solitary tract → solitary nucleus
entorhinal area → entorhinal cortex
lateral septum → lateral septal nucleus
medial septum → medial septal nucleus
nucleus basalis of meynert → basal nucleus of meynert
primary motor area → primary motor cortex
orbitofrontal cortex → orbital frontal cortex
fimbria of hippocampus → fimbria
その他
```

### 3-2. スコア計算の改善（rosetta_candidate_generator.py の局所的修正）

**変更箇所**: `generate()` メソッド内のスコア計算部（約 517 行目）

**変更前**:
```python
final_score *= self._specificity_penalty(query, modifier_terms, term)
```

**変更後**:
```python
if not exact:
    final_score *= self._specificity_penalty(query, modifier_terms, term)
```

**根拠**:  
exact match が成立した場合（クエリが HOMBA の alias に直接マッチした場合）、そのエントリはクエリが意図した構造そのものであることが確定的であり、alias 内の追加語句による specificity_penalty は誤作動となる。`_specificity_penalty` は「クエリより詳細な曖昧マッチを抑制する」目的の機能であり、exact match 後に適用するのは設計の意図と合致しない。

**効果**:
- exact match 時: 最低スコアが 0.86 → 1.0 に向上
- hierarchy_parent（上限 0.97）に exact match が必ず勝てるようになった
- 約 30 クエリのスコアが `needs_review` → `high_confidence` に昇格

---

## 4. 改善前後のスコア変化サマリ

### level1.csv（基準テスト）

| # | クエリ | 改善前 | 改善後 |
|---|--------|--------|--------|
| 1 | Vestibular nucleus | afferent nuclei... 0.97 ❌ | vestibular nuclei in pons 1.0 ✓ |
| 2 | Habenula | habenular triangle 0.52 ❌ | habenular nuclei 1.0 ✓ |
| 3 | Insula | limen insula 0.69 ❌ | insular lobe 1.0 ✓ |
| 4 | Cingulate gyrus | paracingulate gyrus 0.77 ❌ | cingulate cortex 1.0 ✓ |
| 5 | Inferior olivary nucleus | inferior olive 0.80 ⚠ | inferior olive 1.0 ✓ |
| 6 | Pituitary gland | pituitary body 0.77 ⚠ | pituitary body 1.0 ✓ |
| 7 | Pulvinar nucleus | pulvinar of thalamus 0.74 ⚠ | pulvinar of thalamus 1.0 ✓ |
| 8 | Locus coeruleus | nucleus coeruleus 0.86 ⚠ | nucleus coeruleus 1.0 ✓ |

### round1_comprehensive 追加事例（26件改善より抜粋）

| クエリ | 改善前 | 改善後 |
|--------|--------|--------|
| Dentate nucleus | cerebellar deep nuclei 0.97 ❌ | dentate (lateral) nucleus 1.0 ✓ |
| Fastigial nucleus | cerebellar deep nuclei 0.97 ❌ | fastigial (medial) nucleus 1.0 ✓ |
| Emboliform nucleus | lateral interpositus... 0.65 ✓（低スコア） | lateral interpositus... 1.0 ✓ |
| Globose nucleus | sensory relay nuclei... 0.64 ❌ | medial interpositus... 1.0 ✓ |
| Central amygdala | regions of amygdaloid... 0.95 ❌ | central nucleus of amygdala 1.0 ✓ |
| Basolateral amygdala | regions of amygdaloid... 0.97 ❌ | basolateral nuclear group 1.0 ✓ |
| STN | マッチなし | subthalamic nucleus 1.0 ✓ |
| VTA | 0.86 ⚠ | 1.0 ✓ |
| Substantia nigra pars compacta | substantia nigra 0.83 ❌ | SN compact division 1.0 ✓ |

---

## 5. 今後求められる対応

### 優先度：高

**5-1. hierarchy_parent 昇格スコアの再設計**

現在の `_promote_common_parents` は raw `best_method_score`（penalty 前）を使って親を昇格させる。今回の修正（exact match のペナルティ除外）でほぼ回避できたが、根本的には **final score を使って親を昇格させる**設計が望ましい。ただしそのためには採点ループを2パスにする必要がある。

**5-2. LC（locus coeruleus の2文字略語）対応**

"LC" は文献でよく使われるが、HOMBA の acronym は "NC"。2文字の alias rule は偽陽性リスクが高いため慎重な対応が必要。専用の「abbreviation lookup テーブル」を別途用意する設計が安全。

**5-3. laterality 付き細分構造への対応**

`Spinal trigeminal nucleus caudalis` の例では、HOMBA の "caudal division" に "caudalis" が modifier として照合されない問題があった（`caudalis` alias で解決済み）。同様のラテン語 -is/-alis 語尾の対応が他の語にも必要な可能性がある（例: `nucleus tractus solitarius`、`nucleus basalis`）。

### 優先度：中

**5-4. HOMBA にエントリがない集合概念への対応**

- **Limbic system**: 機能的概念。HOMBA に対応エントリなし。「マッチなし」を明示的に返すか、最も近い親構造を提示するか、方針を決める必要がある。
- **Brainstem**: HOMBA は midbrain/pons/medulla を別ノードで管理。"brainstem" クエリへの期待を定義する。

**5-5. eponym（人名由来語）の体系的対応**

Broca's area, Wernicke's area, Nucleus of Meynert など。現状は個別の alias rule で対応しているが、eponym mapping テーブルとして体系的に管理する仕組みが望ましい。

**5-6. 綴り揺れへの体系的対応**

`grey` / `gray`、`-alis` / `-al`、`pars X` / `X division` など、体系的なルールが共通パターンとして繰り返し出現する。現状は個別の alias rule で対応しているが、normalize_text 関数への統合（または pre-normalization ステップ）を検討する価値がある。

### 優先度：低

**5-7. 双方向 alias rule の自己参照問題**

alias_rules は双方向に適用されるため、`emboliform nucleus` → `lateral interpositus emboliform nucleus` のように、target が source を substring として含む規則では、HOMBA の alias 展開時に `lateral interpositus lateral interpositus emboliform nucleus` のような junk alias が生成されることがある。影響は限定的だが、alias rule のバリデーションまたは展開ロジックの改善が望ましい。

**5-8. 大脳皮質 gyrus 表記の統一**

`Cingulate gyrus` が HOMBA の `cingulate cortex` に、`Insula` が `insular lobe` にマッピングされるなど、「gyrus/cortex/lobe 表記ゆれ」は多数の構造に跨がる共通問題。現在は個別 alias で対応しているが、`gyrus` ↔ `cortex` の汎用変換ルールを alias_rules に追加することも検討に値する。

---

## 6. playground ファイル構成（最終状態）

```
cursor_playground/
├── rosetta_candidate_generator.py  ← 本体コピー + scoring fix (line 517付近)
├── rcs_test_interactive.py         ← 拡張版インタラクティブテストスクリプト
├── rcs_test_list.py                ← バッチテストスクリプト
├── analyze_homba.py                ← HOMBA エントリ検索ヘルパー
├── compare_results.py              ← 結果比較スクリプト
├── HOMBA_v1_fixed.csv              ← HOMBAデータ（コピー）
├── homba_alias_rules.csv           ← 改善済み alias rules（4 → 38 ルール）
├── homba_token_rules.csv           ← トークンルール（変更なし）
└── test_list/
    ├── input/
    │   ├── level1.csv
    │   ├── round1_comprehensive.csv
    │   └── round3_edge_cases.csv
    └── output/
        └── （各テスト実行結果 CSV）
```

---

## 7. alias rules の本番反映に関する注意

playground で有効性を検証した alias rules を本番の `homba_alias_rules.csv`（ルート）に反映する際は以下に注意：

1. **bidirectional 展開の影響確認**: 各ルールは双方向に適用されるため、追加した規則が HOMBA の alias 展開時に望ましくない変換を引き起こしていないか確認する
2. **スコア計算修正の同期**: `rosetta_candidate_generator.py` の exact match ペナルティ除外の修正を本番スクリプトおよび `web/backend/lambda_function.py` にも反映する必要がある
3. **lambda_function.py との同期**: Web バックエンドには同一ロジックが inline でコピーされているため、両ファイルの VERSION を合わせて更新する

---

*このレポートは LLM-based Recursive Improvement Round 1–2 の実験結果に基づき作成。本番環境への適用前に追加の回帰テストを実施することを推奨。*
