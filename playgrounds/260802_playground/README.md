# 260802 playground — non-neocortex suitable top-1 validation

精査済み `rcs_projection_corpus_curated_non_neocortex.csv`（suitable + non_neocortex）に対し、
RCS top-1 と query の整合性を DeepSeek **v4-flash（0731）× 3-pass** で独立判定する。

## RCS + AI rerank prototype (`rcs_ai_rerank_harness.py`)

将来の API `use_ai` オプション相当の **playground プロトタイプ**。
RCS エンジン本体は変更しない（精度改善エージェントとの競合回避）。

1. RCS `top_k=10` で候補取得
2. LLM（既定: `deepseek-v4-flash`）が候補内から最良を選択
3. 最良 HOMBA とクエリの関係を返す（HOMBA 側の向き）:
   - `match` — 一致
   - `larger` — より大きい（親／コンテナ）
   - `smaller` — より小さい（部分／下位）
   - `different` — 異なる

※ 3-pass validation（整合性評価）とは別物。こちらは RCS+AI システムの改善用。

```bash
# DEEPSEEK_API_KEY
python playgrounds/260802_playground/rcs_ai_rerank_harness.py --limit 5
python playgrounds/260802_playground/rcs_ai_rerank_harness.py --stage all
python playgrounds/260802_playground/rcs_ai_rerank_harness.py --query "BNST" --query "Pulvinar"
```

Outputs under `runs/rcs_ai_rerank/`:

- `rcs_results.json` — RCS top10
- `ai_results.json` — AI best + relation
- `results.json` — 結合レコード（将来 API レスポンス形に近い）
- `summary.json` / `costs.json`
- `rcs_ai_rerank_report.html`

公開記事（アーキテクチャ + `rcs_ai_compare.csv` 検証まとめ）:

- `web/frontend/reports/2026-08-02/rcs_ai_rerank_article.html`

## RCS vs 3-AI compare (`rcs_ai_compare.csv`, catalog-in-context)

AI プロンプトに HOMBA 全カタログを載せ、RCS と Flash / Pro / Luna を比較する
（Sol なし。目的は RCS の存在意義確認であり AI 運用ではない）。

```bash
# DEEPSEEK_API_KEY + OPENAI_API_KEY
python playgrounds/260802_playground/ai_compare_harness.py --stage all --workers 8
```

Outputs under `runs/ai_compare/`:

- `rcs_results.json` — RCS top-1（再利用）
- `mapping_results.json` — RCS + flash/pro/luna
- `costs.json` — 3AI 推論コスト（+ validation）
- `validation_results.csv` — flash×3 majority
- `summary.json`
- `ai_compare_report.html`

- **略語（`structure_name`）と正式名称（`fullname`）の両方**を別クエリとして評価
  （fullname が空、または略語と同一のときは略語側のみ）
- **pro は使わない**（3 pass とも `deepseek-v4-flash`）
- UI は `archive/260711_playground/top1_consistency_review/v1/validation_report.html` 準拠

## Run

```bash
# from repo root
set DEEPSEEK_API_KEY=...
python playgrounds/260802_playground/eval_harness.py --workers 128
python playgrounds/260802_playground/generate_report.py
```

Outputs:

- `runs/baseline/rcs_results.json` — RCS top-1/top-3
- `runs/baseline/validation_results.csv`
- `runs/baseline/summary.json`
- `runs/baseline/validation_report.html`
- `cache/judgements.json` — pass cache（再開用）

## Abbrev improvement

文献コーパス慣用を優先する abbrev 整備後の再検証:

```bash
python playgrounds/260802_playground/eval_harness.py --tag round3_abbrev --workers 128
python playgrounds/260802_playground/generate_report.py --tag round3_abbrev
python playgrounds/260802_playground/generate_abbrev_improve_report.py --before baseline --after round3_abbrev
```

主な成果物:

- `runs/round3_abbrev/validation_report.html`
- `runs/round3_abbrev/abbrev_improve_report.html` — baseline との差分・システム変更説明
- `runs/round4_abbrev/round4_improve_report.html` — round3→round4（P1–P2）差分
- `runs/round4_abbrev/validation_report.html`
- engine `rcs/rosetta_candidate_generator.py` (0.8.4)
- `rcs/homba_abbrev_rules.csv` — コーパス由来ルール追加済み

```bash
# round4
python playgrounds/260802_playground/eval_harness.py --tag round4_abbrev --workers 128
python playgrounds/260802_playground/generate_report.py --tag round4_abbrev
python playgrounds/260802_playground/generate_round4_report.py
```
