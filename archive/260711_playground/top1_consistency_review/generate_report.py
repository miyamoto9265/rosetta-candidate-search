#!/usr/bin/env python3
"""Generate a self-contained HTML report from validation_results.csv."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "validation_results.csv"
SUMMARY_PATH = ROOT / "summary.json"
OUT_PATH = ROOT / "validation_report.html"

LABEL_ORDER = [
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
    "no_consensus",
]
LABEL_CLASS = {
    "aligned": "ok",
    "broader_parent": "parent",
    "partial_or_narrower": "warn",
    "wrong": "bad",
    "ambiguous": "unknown",
    "source_or_ontology_issue": "issue",
    "no_consensus": "unknown",
}
LABEL_JA = {
    "aligned": "同一構造・同義語",
    "broader_parent": "正しい上位構造",
    "partial_or_narrower": "一部分・狭すぎる",
    "wrong": "異なる構造",
    "ambiguous": "判定困難",
    "source_or_ontology_issue": "入力/オントロジー問題",
    "no_consensus": "多数意見なし",
}


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "0%"


def ordered_keys(counts: dict[str, int], order: list[str] | None = None) -> list[str]:
    keys = [k for k in (order or []) if counts.get(k, 0)]
    for key in sorted(counts):
        if key not in keys and counts.get(key, 0):
            keys.append(key)
    return keys


def count_bar(counts: dict[str, int], total: int, order: list[str] | None = None) -> str:
    parts: list[str] = []
    for key in ordered_keys(counts, order):
        n = counts[key]
        cls = LABEL_CLASS.get(key, "unknown")
        width = 100 * n / total if total else 0
        parts.append(
            f'<div class="bar-seg {cls}" style="width:{width:.2f}%" '
            f'title="{esc(key)}: {n}"></div>'
        )
    return '<div class="bar">' + "".join(parts) + "</div>"


def count_table(
    counts: dict[str, int],
    total: int,
    order: list[str] | None = None,
    with_ja: bool = False,
) -> str:
    rows_html: list[str] = []
    for key in ordered_keys(counts, order):
        n = counts[key]
        pill = f'<span class="pill {LABEL_CLASS.get(key, "unknown")}">{esc(key)}</span>'
        ja = (
            f'<div class="muted small">{esc(LABEL_JA.get(key, ""))}</div>'
            if with_ja
            else ""
        )
        rows_html.append(
            f"<tr><td>{pill}{ja}</td>"
            f'<td class="num">{n}</td>'
            f'<td class="num">{pct(n, total)}</td></tr>'
        )
    return "".join(rows_html)


def main() -> None:
    with CSV_PATH.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))

    records = []
    for row in rows:
        records.append(
            {
                "id": row["validation_id"],
                "dataset": row["dataset"],
                "query": row["query"],
                "top_id": row["top_homba_id"],
                "top_name": row["top_name"],
                "score": row["score"],
                "methods": row["methods"],
                "matched_query": row["matched_query"],
                "matched_alias": row["matched_alias"],
                "modifier_terms": row["modifier_terms"],
                "final_label": row["final_label"],
                "final_certainty": row["final_certainty"],
                "final_confidence": row["final_confidence"],
                "vote_agreement": row["vote_agreement"],
                "has_vote_disagreement": row["has_vote_disagreement"],
                "vote_split_pattern": row["vote_split_pattern"],
                "uncertainty_tag": row["uncertainty_tag"],
                "p1": {
                    "label": row["pass1_label"],
                    "certainty": row["pass1_certainty"],
                    "confidence": row["pass1_confidence"],
                    "reason": row["pass1_reason"],
                },
                "p2": {
                    "label": row["pass2_label"],
                    "certainty": row["pass2_certainty"],
                    "confidence": row["pass2_confidence"],
                    "reason": row["pass2_reason"],
                },
                "p3": {
                    "label": row["pass3_label"],
                    "certainty": row["pass3_certainty"],
                    "confidence": row["pass3_confidence"],
                    "reason": row["pass3_reason"],
                },
            }
        )

    overall = summary["overall"]
    total = summary["total_records"]
    corpus = summary["datasets"]["corpus"]
    species = summary["datasets"]["species"]
    label_options = "".join(f'<option value="{k}">{k}</option>' for k in LABEL_ORDER)

    html_out = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>corpus / species top-1 validation</title>
  <style>
    :root {{
      --bg: #f4f6f9;
      --panel: #fff;
      --text: #1a2332;
      --muted: #667085;
      --line: #d8dee8;
      --ok: #0b7a4b;
      --parent: #2f6fed;
      --warn: #b7791f;
      --bad: #b42318;
      --issue: #7a3fb4;
      --unknown: #475467;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 28px 32px 20px;
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      color: #fff;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; font-weight: 700; }}
    header p {{
      margin: 0;
      color: #cbd5e1;
      max-width: 920px;
      line-height: 1.65;
      font-size: 14px;
    }}
    main {{ padding: 22px 32px 48px; max-width: 1400px; margin: 0 auto; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 18px 20px;
      margin: 0 0 16px;
    }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 16px 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(4, minmax(140px, 1fr));
      gap: 10px;
      margin: 12px 0 4px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 12px 14px;
      background: #fafbfd;
    }}
    .card-title {{ color: var(--muted); font-size: 12px; }}
    .card-value {{
      font-size: 24px;
      font-weight: 700;
      margin-top: 2px;
      font-variant-numeric: tabular-nums;
    }}
    .card-sub {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 10px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #f2f4f7;
      font-size: 12px;
      position: sticky;
      top: 0;
      z-index: 1;
      white-space: nowrap;
    }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      color: #fff;
      font-size: 11px;
      font-weight: 600;
      white-space: nowrap;
    }}
    .pill.ok {{ background: var(--ok); }}
    .pill.parent {{ background: var(--parent); }}
    .pill.warn {{ background: var(--warn); }}
    .pill.bad {{ background: var(--bad); }}
    .pill.issue {{ background: var(--issue); }}
    .pill.unknown {{ background: var(--unknown); }}
    .bar {{
      display: flex;
      height: 10px;
      background: #eef2f6;
      border-radius: 999px;
      overflow: hidden;
      margin: 8px 0 12px;
    }}
    .bar-seg.ok {{ background: var(--ok); }}
    .bar-seg.parent {{ background: var(--parent); }}
    .bar-seg.warn {{ background: var(--warn); }}
    .bar-seg.bad {{ background: var(--bad); }}
    .bar-seg.issue {{ background: var(--issue); }}
    .bar-seg.unknown {{ background: var(--unknown); }}
    .note {{ color: var(--muted); line-height: 1.6; font-size: 13px; }}
    .filters {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin: 10px 0 12px;
      align-items: center;
    }}
    select, input[type="search"] {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 10px;
      background: #fff;
      font-size: 13px;
    }}
    input[type="search"] {{ min-width: 260px; flex: 1; }}
    .filter-meta {{ color: var(--muted); font-size: 13px; margin-left: auto; }}
    .table-wrap {{
      max-height: 720px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
    }}
    .query-cell {{ font-weight: 600; }}
    .top-cell {{ font-size: 13px; }}
    .pass-block {{
      margin-top: 6px;
      padding-top: 6px;
      border-top: 1px dashed var(--line);
      display: none;
    }}
    tr.open .pass-block {{ display: block; }}
    .pass-line {{
      display: grid;
      grid-template-columns: 72px minmax(120px, auto) 1fr;
      gap: 6px 10px;
      align-items: start;
      margin: 0 0 4px;
      font-size: 12px;
    }}
    .pass-name {{ color: var(--muted); }}
    .toggle {{
      cursor: pointer;
      color: #2f6fed;
      font-size: 12px;
      border: none;
      background: none;
      padding: 0;
    }}
    .toggle:hover {{ text-decoration: underline; }}
    tr[data-hidden="1"] {{ display: none; }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin: 8px 0 0;
      font-size: 12px;
      color: var(--muted);
    }}
    .legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
    .dot.ok {{ background: var(--ok); }}
    .dot.parent {{ background: var(--parent); }}
    .dot.warn {{ background: var(--warn); }}
    .dot.bad {{ background: var(--bad); }}
    .dot.issue {{ background: var(--issue); }}
    .dot.unknown {{ background: var(--unknown); }}
    code {{
      background: #eef2f6;
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      main {{ padding: 16px; }}
      .cards, .grid2 {{ grid-template-columns: 1fr 1fr; }}
      input[type="search"] {{ min-width: 100%; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>corpus / species top-1 validation</h1>
    <p>
      RCS top-1 候補と query の整合性を DeepSeek 3-pass（Flash×2 + Pro×1）で独立判定した結果です。
      high/low confidence や correct/incorrect などの過去分類には依存しません。
    </p>
  </header>
  <main>
    <section>
      <h2>概要</h2>
      <div class="cards">
        <div class="card">
          <div class="card-title">総件数</div>
          <div class="card-value">{total}</div>
          <div class="card-sub">corpus {corpus["records"]} / species {species["records"]}</div>
        </div>
        <div class="card">
          <div class="card-title">aligned</div>
          <div class="card-value">{overall["label_counts"].get("aligned", 0)}</div>
          <div class="card-sub">{pct(overall["label_counts"].get("aligned", 0), total)}</div>
        </div>
        <div class="card">
          <div class="card-title">broader_parent</div>
          <div class="card-value">{overall["label_counts"].get("broader_parent", 0)}</div>
          <div class="card-sub">{pct(overall["label_counts"].get("broader_parent", 0), total)}</div>
        </div>
        <div class="card">
          <div class="card-title">wrong</div>
          <div class="card-value">{overall["label_counts"].get("wrong", 0)}</div>
          <div class="card-sub">{pct(overall["label_counts"].get("wrong", 0), total)}</div>
        </div>
      </div>
      {count_bar(overall["label_counts"], total, LABEL_ORDER)}
      <div class="legend">
        <span><i class="dot ok"></i>aligned</span>
        <span><i class="dot parent"></i>broader_parent</span>
        <span><i class="dot warn"></i>partial_or_narrower</span>
        <span><i class="dot bad"></i>wrong</span>
        <span><i class="dot issue"></i>source_or_ontology_issue</span>
        <span><i class="dot unknown"></i>ambiguous / no_consensus</span>
      </div>
    </section>

    <section>
      <h2>ラベル分布</h2>
      <div class="grid2">
        <div>
          <h3>全体 ({total})</h3>
          <table>
            <thead><tr><th>label</th><th class="num">件数</th><th class="num">割合</th></tr></thead>
            <tbody>{count_table(overall["label_counts"], total, LABEL_ORDER, True)}</tbody>
          </table>
          <h3>確実性</h3>
          <table>
            <thead><tr><th>certainty</th><th class="num">件数</th><th class="num">割合</th></tr></thead>
            <tbody>{count_table(overall["certainty_counts"], total, ["high", "medium", "low"])}</tbody>
          </table>
          <h3>投票パターン</h3>
          <table>
            <thead><tr><th>pattern</th><th class="num">件数</th><th class="num">割合</th></tr></thead>
            <tbody>{count_table(overall["vote_split_pattern_counts"], total, ["3-0", "2-1", "1-1-1"])}</tbody>
          </table>
        </div>
        <div>
          <h3>corpus ({corpus["records"]})</h3>
          {count_bar(corpus["label_counts"], corpus["records"], LABEL_ORDER)}
          <table>
            <thead><tr><th>label</th><th class="num">件数</th><th class="num">割合</th></tr></thead>
            <tbody>{count_table(corpus["label_counts"], corpus["records"], LABEL_ORDER)}</tbody>
          </table>
          <h3>species ({species["records"]})</h3>
          {count_bar(species["label_counts"], species["records"], LABEL_ORDER)}
          <table>
            <thead><tr><th>label</th><th class="num">件数</th><th class="num">割合</th></tr></thead>
            <tbody>{count_table(species["label_counts"], species["records"], LABEL_ORDER)}</tbody>
          </table>
        </div>
      </div>
      <p class="note" style="margin-top:14px">
        3-pass: pass1 Flash（厳格） / pass2 Flash（parent区別） / pass3 Pro（保守的）。
        <code>3-0</code> は全一致、<code>2-1</code> は多数決、<code>1-1-1</code> は <code>no_consensus</code>。
      </p>
    </section>

    <section>
      <h2>全レコード</h2>
      <div class="filters">
        <select id="f-dataset">
          <option value="">dataset: all</option>
          <option value="corpus">corpus</option>
          <option value="species">species</option>
        </select>
        <select id="f-label">
          <option value="">label: all</option>
          {label_options}
        </select>
        <select id="f-certainty">
          <option value="">certainty: all</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
        <select id="f-split">
          <option value="">vote: all</option>
          <option value="3-0">3-0</option>
          <option value="2-1">2-1</option>
          <option value="1-1-1">1-1-1</option>
        </select>
        <input type="search" id="f-q" placeholder="query / top_name / HOMBA id で検索">
        <span class="filter-meta" id="filter-count"></span>
      </div>
      <div class="table-wrap">
        <table id="records">
          <thead>
            <tr>
              <th>id</th>
              <th>dataset</th>
              <th>query → top-1</th>
              <th>final</th>
              <th>certainty</th>
              <th>vote</th>
              <th>score</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const LABEL_CLASS = {json.dumps(LABEL_CLASS, ensure_ascii=False)};
    const RECORDS = {json.dumps(records, ensure_ascii=False)};

    function pill(label) {{
      const cls = LABEL_CLASS[label] || "unknown";
      return `<span class="pill ${{cls}}">${{escapeHtml(label)}}</span>`;
    }}
    function escapeHtml(s) {{
      return String(s ?? "").replace(/[&<>"']/g, c => ({{
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
      }})[c]);
    }}
    function passLines(r) {{
      return [
        ["pass1", r.p1],
        ["pass2", r.p2],
        ["pass3", r.p3],
      ].map(([name, p]) => `
        <div class="pass-line">
          <span class="pass-name">${{name}}</span>
          <span>${{pill(p.label)}} <span class="muted">${{escapeHtml(p.certainty)}} · ${{escapeHtml(p.confidence)}}</span></span>
          <span class="muted">${{escapeHtml(p.reason)}}</span>
        </div>`).join("");
    }}

    const tbody = document.getElementById("tbody");
    tbody.innerHTML = RECORDS.map(r => `
      <tr data-id="${{escapeHtml(r.id)}}"
          data-dataset="${{escapeHtml(r.dataset)}}"
          data-label="${{escapeHtml(r.final_label)}}"
          data-certainty="${{escapeHtml(r.final_certainty)}}"
          data-split="${{escapeHtml(r.vote_split_pattern)}}"
          data-search="${{escapeHtml((r.query + " " + r.top_name + " " + r.top_id + " " + r.matched_alias).toLowerCase())}}">
        <td class="small muted">${{escapeHtml(r.id)}}</td>
        <td class="small">${{escapeHtml(r.dataset)}}</td>
        <td>
          <div class="query-cell">${{escapeHtml(r.query)}}</div>
          <div class="top-cell muted">→ ${{escapeHtml(r.top_name)}} <span class="small">(${{escapeHtml(r.top_id)}})</span></div>
          <div class="pass-block">
            ${{passLines(r)}}
            <div class="small muted" style="margin-top:6px">
              methods: ${{escapeHtml(r.methods)}}
              ${{r.matched_alias ? " · matched_alias: " + escapeHtml(r.matched_alias) : ""}}
              ${{r.modifier_terms ? " · modifier: " + escapeHtml(r.modifier_terms) : ""}}
              · uncertainty: ${{escapeHtml(r.uncertainty_tag)}}
            </div>
          </div>
        </td>
        <td>${{pill(r.final_label)}}</td>
        <td class="small">${{escapeHtml(r.final_certainty)}}<div class="muted">${{escapeHtml(r.final_confidence)}}</div></td>
        <td class="small">${{escapeHtml(r.vote_agreement)}}<div class="muted">${{escapeHtml(r.vote_split_pattern)}}</div></td>
        <td class="num small">${{escapeHtml(r.score)}}</td>
        <td><button type="button" class="toggle" data-toggle>詳細</button></td>
      </tr>
    `).join("");

    tbody.addEventListener("click", (e) => {{
      const btn = e.target.closest("[data-toggle]");
      if (!btn) return;
      const tr = btn.closest("tr");
      tr.classList.toggle("open");
      btn.textContent = tr.classList.contains("open") ? "閉じる" : "詳細";
    }});

    const filters = ["f-dataset", "f-label", "f-certainty", "f-split", "f-q"]
      .map(id => document.getElementById(id));
    const countEl = document.getElementById("filter-count");

    function applyFilters() {{
      const ds = document.getElementById("f-dataset").value;
      const label = document.getElementById("f-label").value;
      const cert = document.getElementById("f-certainty").value;
      const split = document.getElementById("f-split").value;
      const q = document.getElementById("f-q").value.trim().toLowerCase();
      let shown = 0;
      for (const tr of tbody.querySelectorAll("tr")) {{
        const ok =
          (!ds || tr.dataset.dataset === ds) &&
          (!label || tr.dataset.label === label) &&
          (!cert || tr.dataset.certainty === cert) &&
          (!split || tr.dataset.split === split) &&
          (!q || tr.dataset.search.includes(q));
        tr.dataset.hidden = ok ? "0" : "1";
        if (ok) shown++;
      }}
      countEl.textContent = shown + " / " + RECORDS.length + " 件";
    }}

    filters.forEach(el => el.addEventListener("input", applyFilters));
    applyFilters();
  </script>
</body>
</html>
"""

    OUT_PATH.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes, {len(records)} records)")


if __name__ == "__main__":
    main()
