# corpus / species top-1 validation

RCS が返した top-1 候補と query の整合性を、DeepSeek による独立3-passで検証した結果です。
過去トライの high/low confidence、correct/incorrect、unresolved といった分類には依存しません。

## ファイル

- `validation_results.csv`: 全921件の検証結果（`dataset` 列で `corpus` / `species` を絞り込み可能）
- `summary.json`: dataset別・全体のラベル、確実性、投票一致度の集計
- `validation_report.html`: ブラウザ確認用レポート（フィルタ・検索・3-pass詳細）
- `generate_report.py`: CSV / summary から HTML を再生成するスクリプト

CSVはExcelで文字化けしにくいUTF-8 BOM付きです。HTMLは単体で開けます。

## 3-pass validation

各レコードを温度0で独立に3回判定し、多数決で `final_label` を決定しています。

1. `pass1_*`: DeepSeek V4 Flash — 厳格判定
2. `pass2_*`: DeepSeek V4 Flash — exact/synonym と parent fallback を区別
3. `pass3_*`: DeepSeek V4 Pro — 保守的な専門判定

`vote_agreement` は3判定の一致数、`vote_split_pattern` は `3-0` / `2-1` / `1-1-1`、
`uncertainty_tag` は安定判定・多数決・分裂判定を示します。`1-1-1` の最終ラベルは
`no_consensus` です。

## ラベル

- `aligned`: 同一構造、同義語、表記ゆれ
- `broader_parent`: top-1が正しい上位構造
- `partial_or_narrower`: top-1が一部分または狭すぎる候補
- `wrong`: 異なる構造
- `ambiguous`: 複数解釈があり判定困難
- `source_or_ontology_issue`: 入力またはオントロジー粒度の問題
- `no_consensus`: 3-passで多数意見なし

## 主な列

- 対象: `validation_id`, `dataset`, `query`, `top_homba_id`, `top_name`
- RCS情報: `score`, `methods`, `matched_query`, `matched_alias`, `modifier_terms`
- 各判定: `pass1_*`, `pass2_*`, `pass3_*`
- 統合結果: `final_label`, `final_certainty`, `final_confidence`, `vote_*`, `uncertainty_tag`
