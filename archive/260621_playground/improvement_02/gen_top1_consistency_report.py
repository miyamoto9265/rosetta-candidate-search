#!/usr/bin/env python3
"""Generate a standalone HTML report for absolute top-1 consistency review."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path

from deepseek_top1_consistency_runner import PROMPT_A, PROMPT_B, PROMPT_C


HERE = Path(__file__).resolve().parent
REVIEW_DIR = HERE / "output" / "top1_consistency_review"
CSV_PATH = REVIEW_DIR / "all_records_top1_consistency.csv"
SUMMARY_PATH = REVIEW_DIR / "summary.json"
OUT_PATH = REVIEW_DIR / "top1_consistency_report.html"

LABEL_JA = {
    "aligned": "整合",
    "broader_parent": "上位概念として整合",
    "partial_or_narrower": "部分一致・狭すぎ",
    "wrong": "不整合",
    "ambiguous": "曖昧",
    "no_consensus": "判定不一致",
    "source_or_ontology_issue": "ソース/HOMBA要確認",
}

LABEL_CLASS = {
    "aligned": "ok",
    "broader_parent": "parent",
    "partial_or_narrower": "warn",
    "wrong": "bad",
    "ambiguous": "unknown",
    "no_consensus": "unknown",
    "source_or_ontology_issue": "issue",
}

PASS_NAMES = {
    "pass1": "Pass 1 / DeepSeek flash / prompt A",
    "pass2": "Pass 2 / DeepSeek flash / prompt B",
    "pass3": "Pass 3 / DeepSeek pro / prompt C",
}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def read_rows() -> list[dict[str, str]]:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def card(title: str, value: object, sub: str = "") -> str:
    return f"""
    <div class="card">
      <div class="card-title">{esc(title)}</div>
      <div class="card-value">{esc(value)}</div>
      <div class="card-sub">{esc(sub)}</div>
    </div>
    """


def prompt_block(title: str, model: str, prompt: str) -> str:
    return f"""
    <details class="prompt-box">
      <summary>{esc(title)} <span class="muted">{esc(model)}</span></summary>
      <pre>{esc(prompt.strip())}</pre>
    </details>
    """


def bar_table(counts: Counter[str], total: int) -> str:
    rows = []
    for label, count in counts.most_common():
        pct = 0 if total == 0 else count * 100 / total
        rows.append(
            f"""
            <tr>
              <td><span class="pill {LABEL_CLASS.get(label, 'unknown')}">{esc(LABEL_JA.get(label, label))}</span></td>
              <td class="num">{count}</td>
              <td class="num">{pct:.1f}%</td>
              <td><div class="bar"><span style="width:{pct:.2f}%"></span></div></td>
            </tr>
            """
        )
    return "\n".join(rows)


def source_table(rows: list[dict[str, str]]) -> str:
    sources = sorted({r["source_file"] for r in rows})
    labels = ["aligned", "broader_parent", "partial_or_narrower", "wrong", "ambiguous", "no_consensus", "source_or_ontology_issue"]
    trs = []
    for source in sources:
        subset = [r for r in rows if r["source_file"] == source]
        counts = Counter(r["final_consistency_label"] for r in subset)
        cells = "".join(f"<td class=\"num\">{counts.get(label, 0)}</td>" for label in labels)
        trs.append(f"<tr><th>{esc(source)}</th><td class=\"num\">{len(subset)}</td>{cells}</tr>")
    heads = "".join(f"<th>{esc(LABEL_JA[label])}</th>" for label in labels)
    return f"""
    <table class="compact">
      <thead><tr><th>入力CSV</th><th>件数</th>{heads}</tr></thead>
      <tbody>{''.join(trs)}</tbody>
    </table>
    """


def pass_summary(row: dict[str, str]) -> str:
    parts = []
    for idx in ("1", "2", "3"):
        label = row.get(f"pass{idx}_label", "")
        css = LABEL_CLASS.get(label, "unknown")
        title = PASS_NAMES[f"pass{idx}"]
        parts.append(
            f"""
            <div class="pass-line">
              <span class="pass-name">{esc(title)}</span>
              <span class="pill {css}">{esc(LABEL_JA.get(label, label))}</span>
              <span class="muted">{esc(row.get(f'pass{idx}_certainty'))} / {esc(row.get(f'pass{idx}_confidence'))}</span>
            </div>
            """
        )
    return "".join(parts)


def detail_table(rows: list[dict[str, str]]) -> str:
    priority = {
        "wrong": 0,
        "partial_or_narrower": 1,
        "source_or_ontology_issue": 2,
        "no_consensus": 3,
        "ambiguous": 4,
        "broader_parent": 5,
        "aligned": 6,
    }
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            priority.get(r["final_consistency_label"], 9),
            r.get("final_certainty") != "low",
            r["source_file"],
            int(r["review_record_id"]),
        ),
    )
    trs = []
    for r in sorted_rows:
        label = r["final_consistency_label"]
        trs.append(
            f"""
            <tr data-label="{esc(label)}" data-source="{esc(r['source_file'])}" data-certainty="{esc(r['final_certainty'])}" data-split="{esc(r.get('vote_split_pattern'))}">
              <td class="small">{esc(r['source_file'])}<br><span class="muted">row {esc(r['source_row'])}</span></td>
              <td>{esc(r['query'])}</td>
              <td>{esc(r['top_name'])}<br><span class="muted">{esc(r['top_homba_id'])} / score {esc(r.get('score'))}</span></td>
              <td><span class="pill {LABEL_CLASS.get(label, 'unknown')}">{esc(LABEL_JA.get(label, label))}</span></td>
              <td class="small">{esc(r['final_certainty'])}<br>{esc(r['vote_agreement'])}<br>{esc(r.get('vote_split_pattern'))}<br>{esc(r['uncertainty_tag'])}</td>
              <td class="pass-cell">{pass_summary(r)}</td>
              <td class="reason">{esc(r['final_reason'])}</td>
            </tr>
            """
        )
    return "\n".join(trs)


def main() -> int:
    rows = read_rows()
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    total = len(rows)
    labels = Counter(r["final_consistency_label"] for r in rows)
    uncertainty = Counter(r["uncertainty_tag"] for r in rows)
    certainty = Counter(r["final_certainty"] for r in rows)
    aligned_like = labels["aligned"] + labels["broader_parent"]
    strict_problem = labels["wrong"] + labels["partial_or_narrower"]
    valid_pass_total = sum(
        1
        for r in rows
        if r.get("pass1_label") and r.get("pass2_label") and r.get("pass3_label")
    )
    low_or_split = sum(
        1
        for r in rows
        if r["final_certainty"] == "low" or "split_vote" in r["uncertainty_tag"]
    )
    disagreement_total = sum(
        1
        for r in rows
        if r.get("has_vote_disagreement") == "True"
    )

    html_text = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RCS top-1 absolute consistency review</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #ffffff;
      --text: #172033;
      --muted: #667085;
      --line: #d9e0ec;
      --ok: #0b7a4b;
      --parent: #2f6fed;
      --warn: #b7791f;
      --bad: #b42318;
      --issue: #7a3fb4;
      --unknown: #475467;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 28px 36px 18px; background: #101828; color: #fff; }}
    header h1 {{ margin: 0 0 8px; font-size: 26px; }}
    header p {{ margin: 0; color: #d0d5dd; max-width: 980px; line-height: 1.6; }}
    main {{ padding: 24px 36px 40px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px; margin: 0 0 20px; box-shadow: 0 1px 2px rgba(16, 24, 40, .04); }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    h3 {{ margin: 22px 0 10px; font-size: 16px; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin: 16px 0; }}
    .card {{ border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #fbfcfe; }}
    .card-title {{ color: var(--muted); font-size: 13px; }}
    .card-value {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
    .card-sub {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f4f7; font-size: 13px; position: sticky; top: 0; z-index: 1; }}
    .compact th, .compact td {{ font-size: 13px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .reason {{ font-size: 12px; line-height: 1.45; max-width: 520px; }}
    .pass-cell {{ min-width: 260px; }}
    .pass-line {{ display: grid; grid-template-columns: minmax(150px, 1fr) auto; gap: 6px 8px; align-items: center; margin: 0 0 6px; }}
    .pass-name {{ color: var(--muted); font-size: 12px; }}
    .prompt-box {{ border: 1px solid var(--line); border-radius: 12px; background: #fbfcfe; margin: 10px 0; }}
    .prompt-box summary {{ cursor: pointer; padding: 12px 14px; font-weight: 700; }}
    .prompt-box pre {{ margin: 0; padding: 14px; border-top: 1px solid var(--line); white-space: pre-wrap; overflow-x: auto; font-size: 12px; line-height: 1.5; }}
    .context-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .context-box {{ border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: #fbfcfe; }}
    .context-box h3 {{ margin-top: 0; }}
    .context-box ul {{ margin: 8px 0 0; padding-left: 20px; line-height: 1.7; }}
    code {{ background: #eef2f6; border-radius: 5px; padding: 1px 5px; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; color: #fff; font-size: 12px; font-weight: 600; white-space: nowrap; }}
    .pill.ok {{ background: var(--ok); }}
    .pill.parent {{ background: var(--parent); }}
    .pill.warn {{ background: var(--warn); }}
    .pill.bad {{ background: var(--bad); }}
    .pill.issue {{ background: var(--issue); }}
    .pill.unknown {{ background: var(--unknown); }}
    .bar {{ height: 10px; background: #eef2f6; border-radius: 999px; overflow: hidden; min-width: 140px; }}
    .bar span {{ display: block; height: 100%; background: #6172f3; }}
    .note {{ color: var(--muted); line-height: 1.65; }}
    .filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }}
    select, input {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: #fff; }}
    input {{ min-width: 320px; }}
    .table-wrap {{ max-height: 760px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; }}
  </style>
</head>
<body>
  <header>
    <h1>RCS top-1 absolute consistency review</h1>
    <p>
      improvement_02 の差分評価ではなく、入力CSVに記録された各 query と top-1 candidate が
      そもそも整合しているかを DeepSeek で独立判定したレポートです。
      各レコードは DeepSeek flash 2回、DeepSeek pro 1回の計3回で判定し、
      投票一致度と不確実性タグを残しています。
    </p>
  </header>
  <main>
    <section>
      <h2>このレポートの位置づけ</h2>
      <div class="context-grid">
        <div class="context-box">
          <h3>目的</h3>
          <p class="note">
            RCS の top-1 が、元の入力テキストである <code>query</code> と整合しているかを確認するための
            絶対評価レポートです。ここでは <code>improvement_02</code> によって良くなったか悪くなったかは見ていません。
          </p>
          <ul>
            <li>判定対象: <code>query</code> と <code>top_name / top_homba_id</code> の対応</li>
            <li>判定しないもの: baseline と improved の差分、スコア改善量、アルゴリズム変更の効果</li>
            <li>注意: この結果も確立済みの正解データではなく、LLM によるレビュー結果です</li>
          </ul>
        </div>
        <div class="context-box">
          <h3>入力CSV</h3>
          <ul>
            <li><code>1_highconf_correct.csv</code></li>
            <li><code>2_highconf_incorrect.csv</code></li>
            <li><code>3_unresolved_correct.csv</code></li>
            <li><code>4_unresolved_incorrect.csv</code></li>
          </ul>
          <p class="note">
            入力CSV名に含まれる correct/incorrect は過去のレビュー分類であり、
            今回の判定ではその分類を正解として扱っていません。
          </p>
        </div>
      </div>
    </section>

    <section>
      <h2>判定方法</h2>
      <div class="cards">
        {card("Pass 1", "DeepSeek flash", "prompt A / strict")}
        {card("Pass 2", "DeepSeek flash", "prompt B / parent-aware")}
        {card("Pass 3", "DeepSeek pro", "prompt C / conservative adjudication")}
        {card("3パス完了", f"{valid_pass_total}/{total}", "all pass labels present")}
      </div>
      <p class="note">
        各パスは独立したプロンプトで判定し、最終ラベルは3票の多数決で決めています。
        3票一致は <code>stable</code>、2票一致は <code>majority_vote</code>、
        票が割れた場合は <code>split_vote</code> として残しています。
        つまり、3/3完全一致でないだけで最終ラベルを自動的に <code>ambiguous</code> にしているわけではありません。
        3者割れなど多数決が成立しない場合は <code>no_consensus</code> にします。
        <code>ambiguous</code> は、LLM自身が候補を曖昧と判定した場合のラベルとして残します。
        判定割れはCSVの <code>has_vote_disagreement</code> と <code>vote_split_pattern</code>
        （<code>3-0</code>, <code>2-1</code>, <code>1-1-1</code>）で確認できます。
        <code>final_reason</code> は3回分の理由を <code>|</code> で連結した列で、
        個別理由はCSVの <code>pass1_reason</code>、<code>pass2_reason</code>、<code>pass3_reason</code> にも残しています。
      </p>
      <p class="note">
        APIログ上の失敗は再試行前の失敗も含みます。最終CSVでは3パスすべての有効判定が
        <code>{valid_pass_total}/{total}</code> 件そろっています。
      </p>
      <h3>使用したPrompt</h3>
      <p class="note">
        以下はAPI呼び出しで実際に使ったsystem promptです。各リクエストでは、このsystem promptに加えて、
        レコードごとの <code>query</code>、<code>top1_name</code>、<code>top1_id</code> などをJSONで渡しています。
      </p>
      {prompt_block("Prompt A", "DeepSeek flash / strict", PROMPT_A)}
      {prompt_block("Prompt B", "DeepSeek flash / parent-aware", PROMPT_B)}
      {prompt_block("Prompt C", "DeepSeek pro / conservative adjudication", PROMPT_C)}
    </section>

    <section>
      <h2>概要</h2>
      <div class="cards">
        {card("レビュー件数", total, "4 input CSVs")}
        {card("整合または上位概念", aligned_like, f"{aligned_like / total * 100:.1f}%")}
        {card("不整合または部分一致", strict_problem, f"{strict_problem / total * 100:.1f}%")}
        {card("低確実性/投票割れ", low_or_split, "human review priority")}
        {card("判定割れ", disagreement_total, "has_vote_disagreement=true")}
      </div>
      <p class="note">
        「整合」は同一構造・同義語・表記揺れとみなせるものです。
        「上位概念として整合」は exact ではありませんが、解剖学的な親候補としては外れていないものです。
        「部分一致・狭すぎ」と「不整合」は、top-1 をそのまま採用すると誤りになりやすい候補です。
      </p>
    </section>

    <section>
      <h2>ラベル分布</h2>
      <table class="compact">
        <thead><tr><th>ラベル</th><th>件数</th><th>割合</th><th>分布</th></tr></thead>
        <tbody>{bar_table(labels, total)}</tbody>
      </table>
      <h3>入力CSV別</h3>
      {source_table(rows)}
    </section>

    <section>
      <h2>確実性</h2>
      <div class="cards">
        {card("high", certainty["high"], "LLM certainty")}
        {card("medium", certainty["medium"], "LLM certainty")}
        {card("low", certainty["low"], "LLM certainty")}
        {card("API failures", summary.get("api_failures", 0), "invalid/missing batches")}
      </div>
      <table class="compact">
        <thead><tr><th>不確実性タグ</th><th>件数</th></tr></thead>
        <tbody>{''.join(f'<tr><td>{esc(k)}</td><td class="num">{v}</td></tr>' for k, v in uncertainty.most_common())}</tbody>
      </table>
    </section>

    <section>
      <h2>全レコード詳細</h2>
      <div class="filters">
        <select id="labelFilter">
          <option value="">all labels</option>
          {''.join(f'<option value="{esc(k)}">{esc(LABEL_JA.get(k, k))}</option>' for k in LABEL_JA)}
        </select>
        <select id="certaintyFilter">
          <option value="">all certainty</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
        <select id="splitFilter">
          <option value="">all vote splits</option>
          <option value="2-1">2-1 split only</option>
          <option value="1-1-1">1-1-1 no consensus only</option>
          <option value="3-0">3-0 stable only</option>
        </select>
        <input id="searchBox" placeholder="query / top-1 / reason search">
      </div>
      <div class="table-wrap">
        <table id="detailTable">
          <thead>
            <tr>
              <th>source</th>
              <th>query</th>
              <th>top-1</th>
              <th>final label</th>
              <th>certainty</th>
              <th>3-pass labels</th>
              <th>reason</th>
            </tr>
          </thead>
          <tbody>{detail_table(rows)}</tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const labelFilter = document.getElementById('labelFilter');
    const certaintyFilter = document.getElementById('certaintyFilter');
    const splitFilter = document.getElementById('splitFilter');
    const searchBox = document.getElementById('searchBox');
    const rows = Array.from(document.querySelectorAll('#detailTable tbody tr'));
    function applyFilters() {{
      const label = labelFilter.value;
      const certainty = certaintyFilter.value;
      const split = splitFilter.value;
      const q = searchBox.value.toLowerCase();
      rows.forEach(row => {{
        const labelOk = !label || row.dataset.label === label;
        const certaintyOk = !certainty || row.dataset.certainty === certainty;
        const splitOk = !split || row.dataset.split === split;
        const textOk = !q || row.innerText.toLowerCase().includes(q);
        row.style.display = labelOk && certaintyOk && splitOk && textOk ? '' : 'none';
      }});
    }}
    [labelFilter, certaintyFilter, splitFilter, searchBox].forEach(el => el.addEventListener('input', applyFilters));
  </script>
</body>
</html>
"""
    OUT_PATH.write_text(html_text, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

