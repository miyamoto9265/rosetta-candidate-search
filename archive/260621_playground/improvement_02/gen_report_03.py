#!/usr/bin/env python3
"""Generate report_03.html for the changed top-1 independent review."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter
from pathlib import Path


HERE = Path(__file__).resolve().parent
REVIEW_DIR = HERE / "output" / "report_03_changed_top1_review"
CSV_PATH = REVIEW_DIR / "changed_top1_report03_review.csv"
SUMMARY_PATH = REVIEW_DIR / "summary.json"
OUT_PATH = HERE / "report_03.html"

IMPROVEMENT_JA = {
    "improved_better": "改善",
    "improved_worse": "悪化",
    "no_material_change": "実質変化なし",
    "both_wrong": "両方不整合",
    "needs_human_review": "要目視確認",
    "homba_gap_or_source_issue": "ソース/HOMBA要確認",
}

CONSISTENCY_JA = {
    "aligned": "整合",
    "broader_parent": "上位概念",
    "partial_or_narrower": "部分/狭すぎ",
    "wrong": "不整合",
    "ambiguous": "曖昧",
    "source_or_ontology_issue": "ソース/HOMBA",
}

CLASS = {
    "improved_better": "ok",
    "improved_worse": "bad",
    "no_material_change": "neutral",
    "both_wrong": "bad2",
    "needs_human_review": "unknown",
    "homba_gap_or_source_issue": "issue",
    "aligned": "ok",
    "broader_parent": "parent",
    "partial_or_narrower": "warn",
    "wrong": "bad",
    "ambiguous": "unknown",
    "source_or_ontology_issue": "issue",
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


def pill(label: str, mapping: dict[str, str]) -> str:
    return f'<span class="pill {CLASS.get(label, "unknown")}">{esc(mapping.get(label, label))}</span>'


def bar_table(counts: Counter[str], total: int, mapping: dict[str, str]) -> str:
    rows = []
    for label, count in counts.most_common():
        pct = 0 if total == 0 else count * 100 / total
        rows.append(
            f"""
            <tr>
              <td>{pill(label, mapping)}</td>
              <td class="num">{count}</td>
              <td class="num">{pct:.1f}%</td>
              <td><div class="bar"><span style="width:{pct:.2f}%"></span></div></td>
            </tr>
            """
        )
    return "\n".join(rows)


def consistency_transition_table(rows: list[dict[str, str]]) -> str:
    counts = Counter(
        (r["final_baseline_consistency_label"], r["final_improved_consistency_label"])
        for r in rows
    )
    trs = []
    for (base, impr), count in counts.most_common():
        trs.append(
            f"""
            <tr>
              <td>{pill(base, CONSISTENCY_JA)}</td>
              <td>{pill(impr, CONSISTENCY_JA)}</td>
              <td class="num">{count}</td>
            </tr>
            """
        )
    return f"""
    <table class="compact">
      <thead><tr><th>baseline</th><th>improved</th><th>件数</th></tr></thead>
      <tbody>{''.join(trs)}</tbody>
    </table>
    """


def detail_rows(rows: list[dict[str, str]]) -> str:
    priority = {
        "improved_worse": 0,
        "both_wrong": 1,
        "needs_human_review": 2,
        "homba_gap_or_source_issue": 3,
        "no_material_change": 4,
        "improved_better": 5,
    }
    sorted_rows = sorted(
        rows,
        key=lambda r: (
            priority.get(r["final_improvement_label"], 9),
            r["final_certainty"] != "low",
            r["dataset"],
            r["query"],
        ),
    )
    trs = []
    for r in sorted_rows:
        label = r["final_improvement_label"]
        trs.append(
            f"""
            <tr data-label="{esc(label)}" data-certainty="{esc(r['final_certainty'])}">
              <td class="small">{esc(r['dataset'])}<br>{esc(r['role'])}</td>
              <td>{esc(r['query'])}</td>
              <td>
                <div><b>baseline:</b> {esc(r['baseline_top1_name'])}</div>
                <div class="muted">{esc(r['baseline_top1_id'])} / score {esc(r['baseline_score'])} / abs {esc(r['baseline_abs_label_from_top1_consistency_review'])}</div>
                <div class="sep"></div>
                <div><b>improved:</b> {esc(r['improved_top1_name'])}</div>
                <div class="muted">{esc(r['improved_top1_id'])} / score {esc(r['improved_score'])}</div>
              </td>
              <td>
                {pill(r['final_baseline_consistency_label'], CONSISTENCY_JA)}
                <span class="arrow">→</span>
                {pill(r['final_improved_consistency_label'], CONSISTENCY_JA)}
              </td>
              <td>{pill(label, IMPROVEMENT_JA)}</td>
              <td class="small">{esc(r['final_certainty'])}<br>{esc(r['vote_agreement'])}<br>{esc(r['uncertainty_tag'])}</td>
              <td class="reason">{esc(r['final_reason'])}</td>
            </tr>
            """
        )
    return "\n".join(trs)


def main() -> int:
    rows = read_rows()
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    total = len(rows)
    improvement = Counter(r["final_improvement_label"] for r in rows)
    baseline_consistency = Counter(r["final_baseline_consistency_label"] for r in rows)
    improved_consistency = Counter(r["final_improved_consistency_label"] for r in rows)
    certainty = Counter(r["final_certainty"] for r in rows)
    uncertainty = Counter(r["uncertainty_tag"] for r in rows)
    valid = summary.get("valid_3pass_records", 0)
    human_priority = (
        improvement["improved_worse"]
        + improvement["both_wrong"]
        + improvement["needs_human_review"]
        + improvement["homba_gap_or_source_issue"]
    )

    html_text = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Report 03: changed top-1 independent review</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --panel: #fff;
      --text: #172033;
      --muted: #667085;
      --line: #d9e0ec;
      --ok: #0b7a4b;
      --parent: #2f6fed;
      --warn: #b7791f;
      --bad: #b42318;
      --bad2: #7a271a;
      --issue: #7a3fb4;
      --unknown: #475467;
      --neutral: #344054;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: var(--bg); color: var(--text); }}
    header {{ padding: 30px 36px 20px; background: #101828; color: #fff; }}
    header h1 {{ margin: 0 0 8px; font-size: 26px; }}
    header p {{ margin: 0; max-width: 1080px; line-height: 1.65; color: #d0d5dd; }}
    main {{ padding: 24px 36px 40px; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px; margin: 0 0 20px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }}
    h2 {{ margin: 0 0 14px; font-size: 20px; }}
    h3 {{ margin: 22px 0 10px; font-size: 16px; }}
    p {{ line-height: 1.65; }}
    code {{ background: #eef2f6; border-radius: 5px; padding: 1px 5px; }}
    .note {{ color: var(--muted); }}
    .context-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .context-box {{ border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; background: #fbfcfe; }}
    .context-box h3 {{ margin-top: 0; }}
    .context-box ul {{ margin: 8px 0 0; padding-left: 20px; line-height: 1.7; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(160px, 1fr)); gap: 12px; margin: 16px 0; }}
    .card {{ border: 1px solid var(--line); border-radius: 12px; padding: 14px; background: #fbfcfe; }}
    .card-title {{ color: var(--muted); font-size: 13px; }}
    .card-value {{ font-size: 25px; font-weight: 700; margin-top: 4px; }}
    .card-sub {{ color: var(--muted); font-size: 12px; min-height: 18px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: #f2f4f7; font-size: 13px; position: sticky; top: 0; z-index: 1; }}
    .compact th, .compact td {{ font-size: 13px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); font-size: 12px; }}
    .small {{ font-size: 12px; }}
    .reason {{ font-size: 12px; line-height: 1.45; max-width: 520px; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; color: #fff; font-size: 12px; font-weight: 600; white-space: nowrap; }}
    .pill.ok {{ background: var(--ok); }}
    .pill.parent {{ background: var(--parent); }}
    .pill.warn {{ background: var(--warn); }}
    .pill.bad {{ background: var(--bad); }}
    .pill.bad2 {{ background: var(--bad2); }}
    .pill.issue {{ background: var(--issue); }}
    .pill.unknown {{ background: var(--unknown); }}
    .pill.neutral {{ background: var(--neutral); }}
    .bar {{ height: 10px; background: #eef2f6; border-radius: 999px; overflow: hidden; min-width: 140px; }}
    .bar span {{ display: block; height: 100%; background: #6172f3; }}
    .filters {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0; }}
    select, input {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; background: #fff; }}
    input {{ min-width: 340px; }}
    .table-wrap {{ max-height: 760px; overflow: auto; border: 1px solid var(--line); border-radius: 10px; }}
    .sep {{ height: 5px; }}
    .arrow {{ margin: 0 5px; color: var(--muted); }}
  </style>
</head>
<body>
  <header>
    <h1>Report 03: changed top-1 independent review</h1>
    <p>
      top-1 が変化した55件だけを対象に、baseline candidate と improved candidate のどちらが
      元の query により整合するかを DeepSeek で再判定した独立レポートです。
      過去の改善判定ラベルは使っていません。
    </p>
  </header>
  <main>
    <section>
      <h2>このレポートの位置づけ</h2>
      <div class="context-grid">
        <div class="context-box">
          <h3>目的</h3>
          <p class="note">
            Report 03 は、前回の変化リスト <code>changed_top1_with_deepseek.csv</code> に含まれる
            55件だけを再評価します。このCSVは対象レコードの抽出にだけ使い、
            過去の <code>deepseek_label</code> は判定にも集計にも使っていません。
            評価対象は <code>query</code>、baseline top-1、improved top-1 の3点です。
          </p>
          <ul>
            <li>見るもの: top-1 変更が意味のある改善か、悪化か、実質変化なしか</li>
            <li>見ないもの: これまでの <code>changed_top1_with_deepseek.csv</code> の判定</li>
            <li>参考のみ: 直前の絶対整合性レビューにおける baseline 側ラベル</li>
          </ul>
        </div>
        <div class="context-box">
          <h3>判定方法</h3>
          <ul>
            <li>Pass 1: DeepSeek flash / strict prompt</li>
            <li>Pass 2: DeepSeek flash / specificity-aware prompt</li>
            <li>Pass 3: DeepSeek pro / conservative adjudication prompt</li>
            <li>最終判定: 3回の多数決、票割れは要目視寄りに扱う</li>
          </ul>
        </div>
      </div>
    </section>

    <section>
      <h2>概要</h2>
      <div class="cards">
        {card("対象件数", total, "changed top-1 only")}
        {card("3パス完了", f"{valid}/{total}", "flash x2 + pro x1")}
        {card("改善", improvement["improved_better"], f"{improvement['improved_better'] / total * 100:.1f}%")}
        {card("要確認/悪化系", human_priority, "worse + both wrong + uncertain")}
      </div>
      <p class="note">
        <code>final_reason</code> は3回分の理由を <code>|</code> で連結しています。
        個別理由はCSVの <code>pass1_reason</code>、<code>pass2_reason</code>、<code>pass3_reason</code> に残しています。
      </p>
    </section>

    <section>
      <h2>改善判定の分布</h2>
      <table class="compact">
        <thead><tr><th>ラベル</th><th>件数</th><th>割合</th><th>分布</th></tr></thead>
        <tbody>{bar_table(improvement, total, IMPROVEMENT_JA)}</tbody>
      </table>
    </section>

    <section>
      <h2>baseline / improved の絶対整合性</h2>
      <div class="context-grid">
        <div>
          <h3>baseline</h3>
          <table class="compact">
            <thead><tr><th>ラベル</th><th>件数</th><th>割合</th><th>分布</th></tr></thead>
            <tbody>{bar_table(baseline_consistency, total, CONSISTENCY_JA)}</tbody>
          </table>
        </div>
        <div>
          <h3>improved</h3>
          <table class="compact">
            <thead><tr><th>ラベル</th><th>件数</th><th>割合</th><th>分布</th></tr></thead>
            <tbody>{bar_table(improved_consistency, total, CONSISTENCY_JA)}</tbody>
          </table>
        </div>
      </div>
      <h3>整合性ラベルの遷移</h3>
      {consistency_transition_table(rows)}
    </section>

    <section>
      <h2>確実性</h2>
      <div class="cards">
        {card("high", certainty["high"], "final certainty")}
        {card("medium", certainty["medium"], "final certainty")}
        {card("low", certainty["low"], "final certainty")}
        {card("API failures", summary.get("api_failures", 0), "retry log included")}
      </div>
      <table class="compact">
        <thead><tr><th>不確実性タグ</th><th>件数</th></tr></thead>
        <tbody>{''.join(f'<tr><td>{esc(k)}</td><td class="num">{v}</td></tr>' for k, v in uncertainty.most_common())}</tbody>
      </table>
    </section>

    <section>
      <h2>55件詳細</h2>
      <div class="filters">
        <select id="labelFilter">
          <option value="">all improvement labels</option>
          {''.join(f'<option value="{esc(k)}">{esc(v)}</option>' for k, v in IMPROVEMENT_JA.items())}
        </select>
        <select id="certaintyFilter">
          <option value="">all certainty</option>
          <option value="high">high</option>
          <option value="medium">medium</option>
          <option value="low">low</option>
        </select>
        <input id="searchBox" placeholder="query / candidate / reason search">
      </div>
      <div class="table-wrap">
        <table id="detailTable">
          <thead>
            <tr>
              <th>dataset</th>
              <th>query</th>
              <th>candidates</th>
              <th>consistency</th>
              <th>improvement</th>
              <th>certainty</th>
              <th>reason</th>
            </tr>
          </thead>
          <tbody>{detail_rows(rows)}</tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const labelFilter = document.getElementById('labelFilter');
    const certaintyFilter = document.getElementById('certaintyFilter');
    const searchBox = document.getElementById('searchBox');
    const rows = Array.from(document.querySelectorAll('#detailTable tbody tr'));
    function applyFilters() {{
      const label = labelFilter.value;
      const certainty = certaintyFilter.value;
      const q = searchBox.value.toLowerCase();
      rows.forEach(row => {{
        const labelOk = !label || row.dataset.label === label;
        const certaintyOk = !certainty || row.dataset.certainty === certainty;
        const textOk = !q || row.innerText.toLowerCase().includes(q);
        row.style.display = labelOk && certaintyOk && textOk ? '' : 'none';
      }});
    }}
    [labelFilter, certaintyFilter, searchBox].forEach(el => el.addEventListener('input', applyFilters));
  </script>
</body>
</html>
"""
    OUT_PATH.write_text(html_text, encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

