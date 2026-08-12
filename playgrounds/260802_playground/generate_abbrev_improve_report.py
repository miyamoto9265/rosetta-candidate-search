#!/usr/bin/env python3
"""Baseline vs abbrev-improvement HTML report (validation_report taste)."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BEFORE = "baseline"
DEFAULT_AFTER = "round3_abbrev"

LABEL_ORDER = [
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
    "no_consensus",
    "no_match",
]
LABEL_CLASS = {
    "aligned": "ok",
    "broader_parent": "parent",
    "partial_or_narrower": "warn",
    "wrong": "bad",
    "ambiguous": "unknown",
    "source_or_ontology_issue": "issue",
    "no_consensus": "unknown",
    "no_match": "issue",
}
LABEL_JA = {
    "aligned": "同一構造・同義語",
    "broader_parent": "正しい上位構造",
    "partial_or_narrower": "一部分・狭すぎる",
    "wrong": "異なる構造",
    "ambiguous": "判定困難",
    "source_or_ontology_issue": "入力/オントロジー問題",
    "no_consensus": "多数意見なし",
    "no_match": "RCS no_match",
}
RANK = {
    "aligned": 0,
    "broader_parent": 1,
    "partial_or_narrower": 2,
    "wrong": 3,
    "ambiguous": 4,
    "source_or_ontology_issue": 5,
    "no_consensus": 5,
    "no_match": 6,
}


def esc(value: object) -> str:
    return html.escape(str(value or ""))


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "0%"


def delta(a: int, b: int) -> str:
    d = b - a
    if d > 0:
        return f"+{d}"
    return str(d)


def load_rows(tag: str) -> list[dict]:
    path = HERE / "runs" / tag / "validation_results.csv"
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_summary(tag: str) -> dict:
    return json.loads(
        (HERE / "runs" / tag / "summary.json").read_text(encoding="utf-8")
    )


def lab(row: dict) -> str:
    if not row.get("top_homba_id"):
        return "no_match"
    return row.get("final_label") or "uncertain"


def label_counts(rows: list[dict], kind: str | None = None) -> dict[str, int]:
    c: Counter[str] = Counter()
    for r in rows:
        if kind and r.get("query_kind") != kind:
            continue
        c[lab(r)] += 1
    return dict(c)


def compare(before: list[dict], after: list[dict]):
    bm = {(r["query_kind"], r["query"]): r for r in before}
    am = {(r["query_kind"], r["query"]): r for r in after}
    improved, regressed, changed_top = [], [], []
    for k, ar in am.items():
        br = bm.get(k)
        if not br:
            continue
        bl, al = lab(br), lab(ar)
        top_changed = (br.get("top_homba_id") or "") != (ar.get("top_homba_id") or "")
        if top_changed:
            changed_top.append((k[0], k[1], br, ar, bl, al))
        if bl == al:
            continue
        row = (k[0], k[1], bl, al, br, ar)
        if RANK.get(al, 9) < RANK.get(bl, 9):
            improved.append(row)
        elif RANK.get(al, 9) > RANK.get(bl, 9):
            regressed.append(row)
    return improved, regressed, changed_top


def count_bar(counts: dict[str, int], total: int) -> str:
    parts = []
    for key in LABEL_ORDER:
        n = counts.get(key, 0)
        if not n:
            continue
        width = 100 * n / total if total else 0
        parts.append(
            f'<div class="bar-seg {LABEL_CLASS.get(key, "unknown")}" '
            f'style="width:{width:.2f}%" title="{esc(key)}: {n}"></div>'
        )
    return '<div class="bar">' + "".join(parts) + "</div>"


def metric_table(
    before_c: dict[str, int], after_c: dict[str, int], total: int
) -> str:
    rows = []
    keys = [k for k in LABEL_ORDER if before_c.get(k) or after_c.get(k)]
    for key in keys:
        b, a = before_c.get(key, 0), after_c.get(key, 0)
        d = a - b
        dcls = "ok" if (
            (key in {"aligned", "broader_parent"} and d > 0)
            or (key in {"wrong", "no_match", "source_or_ontology_issue"} and d < 0)
        ) else ("bad" if (
            (key in {"aligned", "broader_parent"} and d < 0)
            or (key in {"wrong", "no_match", "source_or_ontology_issue"} and d > 0)
        ) else "unknown")
        pill = f'<span class="pill {LABEL_CLASS.get(key, "unknown")}">{esc(key)}</span>'
        ja = f'<div class="muted small">{esc(LABEL_JA.get(key, ""))}</div>'
        rows.append(
            f"<tr><td>{pill}{ja}</td>"
            f'<td class="num">{b}</td><td class="num">{pct(b, total)}</td>'
            f'<td class="num">{a}</td><td class="num">{pct(a, total)}</td>'
            f'<td class="num"><span class="pill {dcls}">{delta(b, a)}</span></td></tr>'
        )
    return "".join(rows)


def example_rows(items: list, limit: int = 25) -> str:
    out = []
    for kind, query, bl, al, br, ar in items[:limit]:
        out.append(
            "<tr>"
            f'<td><span class="pill {"parent" if kind == "abbrev" else "unknown"}">{esc(kind)}</span></td>'
            f'<td class="query-cell">{esc(query)}</td>'
            f'<td><span class="pill {LABEL_CLASS.get(bl, "unknown")}">{esc(bl)}</span>'
            f'<div class="muted small">{esc((br.get("top_name") or "(no_match)")[:80])}</div></td>'
            f'<td><span class="pill {LABEL_CLASS.get(al, "unknown")}">{esc(al)}</span>'
            f'<div class="muted small">{esc((ar.get("top_name") or "(no_match)")[:80])}</div></td>'
            "</tr>"
        )
    return "".join(out) if out else '<tr><td colspan="4" class="muted">なし</td></tr>'


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--before", default=DEFAULT_BEFORE)
    p.add_argument("--after", default=DEFAULT_AFTER)
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Default: runs/<after>/abbrev_improve_report.html",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    before_rows = load_rows(args.before)
    after_rows = load_rows(args.after)
    before_sum = load_summary(args.before)
    after_sum = load_summary(args.after)
    out = args.out or (HERE / "runs" / args.after / "abbrev_improve_report.html")

    total = len(after_rows)
    b_all = label_counts(before_rows)
    a_all = label_counts(after_rows)
    b_ab = label_counts(before_rows, "abbrev")
    a_ab = label_counts(after_rows, "abbrev")
    improved, regressed, changed_top = compare(before_rows, after_rows)
    imp_ab = [x for x in improved if x[0] == "abbrev"]
    reg_ab = [x for x in regressed if x[0] == "abbrev"]

    # Highlight showcase examples
    showcase = [
        "VP", "DMS", "PPN", "CA1", "ARC", "III", "DCN interpositus",
        "EC III", "lateral NAcc", "dorsolateral PAG", "NAc shell", "LHb",
    ]
    showcase_html = []
    bm = {(r["query_kind"], r["query"]): r for r in before_rows}
    am = {(r["query_kind"], r["query"]): r for r in after_rows}
    for q in showcase:
        br = bm.get(("abbrev", q))
        ar = am.get(("abbrev", q))
        if not br or not ar:
            continue
        showcase_html.append(
            "<tr>"
            f'<td class="query-cell"><code>{esc(q)}</code></td>'
            f'<td><span class="pill {LABEL_CLASS.get(lab(br), "unknown")}">{esc(lab(br))}</span>'
            f'<div class="muted small">{esc((br.get("top_name") or "(no_match)")[:70])}</div></td>'
            f'<td><span class="pill {LABEL_CLASS.get(lab(ar), "unknown")}">{esc(lab(ar))}</span>'
            f'<div class="muted small">{esc((ar.get("top_name") or "(no_match)")[:70])}</div></td>'
            "</tr>"
        )

    html_doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Abbrev improvement report — {esc(args.before)} → {esc(args.after)}</title>
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
      max-width: 980px;
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
    .note {{ color: var(--muted); line-height: 1.65; font-size: 13px; }}
    .note li {{ margin: 0 0 6px; }}
    code {{
      background: #eef2f6;
      border-radius: 4px;
      padding: 1px 5px;
      font-size: 12px;
    }}
    .table-wrap {{
      max-height: 520px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 10px;
    }}
    .query-cell {{ font-weight: 600; }}
    @media (max-width: 900px) {{
      main {{ padding: 16px; }}
      .cards, .grid2 {{ grid-template-columns: 1fr 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Abbrev 精度向上レポート</h1>
    <p>
      論文コーパス上の略語慣用を優先しつつ HOMBA acronym は維持する方針で、
      RCS abbrev 経路を整備した結果です。比較:
      <code>{esc(args.before)}</code> → <code>{esc(args.after)}</code>
      （判定は DeepSeek flash × 3-pass、baseline と同条件）。
    </p>
  </header>
  <main>
    <section>
      <h2>サマリー</h2>
      <div class="cards">
        <div class="card">
          <div class="card-title">総クエリ</div>
          <div class="card-value">{total}</div>
          <div class="card-sub">abbrev {before_sum['query_kind_counts']['abbrev']} / fullname {before_sum['query_kind_counts']['fullname']}</div>
        </div>
        <div class="card">
          <div class="card-title">no_match</div>
          <div class="card-value">{a_all.get('no_match', 0)}</div>
          <div class="card-sub">baseline {b_all.get('no_match', 0)} → {delta(b_all.get('no_match', 0), a_all.get('no_match', 0))}</div>
        </div>
        <div class="card">
          <div class="card-title">aligned</div>
          <div class="card-value">{a_all.get('aligned', 0)}</div>
          <div class="card-sub">baseline {b_all.get('aligned', 0)} → {delta(b_all.get('aligned', 0), a_all.get('aligned', 0))}</div>
        </div>
        <div class="card">
          <div class="card-title">label 改善 / 悪化</div>
          <div class="card-value">{len(improved)} / {len(regressed)}</div>
          <div class="card-sub">abbrev のみ {len(imp_ab)} / {len(reg_ab)}</div>
        </div>
      </div>
      <h3>全体ラベル分布</h3>
      {count_bar(a_all, total)}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>label</th>
              <th class="num">before</th><th class="num">%</th>
              <th class="num">after</th><th class="num">%</th>
              <th class="num">Δ</th>
            </tr>
          </thead>
          <tbody>
            {metric_table(b_all, a_all, total)}
          </tbody>
        </table>
      </div>
      <h3>abbrev のみ</h3>
      {count_bar(a_ab, sum(a_ab.values()) or 1)}
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>label</th>
              <th class="num">before</th><th class="num">%</th>
              <th class="num">after</th><th class="num">%</th>
              <th class="num">Δ</th>
            </tr>
          </thead>
          <tbody>
            {metric_table(b_ab, a_ab, sum(a_ab.values()) or 1)}
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>システム変更（原理）</h2>
      <div class="note">
        <p><strong>方針:</strong> HOMBA の <code>unified_ontology_acronym</code> は消さない。
        コーパスが示す論文慣用と衝突する場合は、クエリ側の略語展開とスコアリングで文献側を優先する。
        オントロジーに存在しない区画へ無理に当てはめない（例: DMS → striatum 親への broader_parent）。</p>
        <ol>
          <li><strong>コーパス由来 abbrev ルール追加</strong>（<code>rcs/homba_abbrev_rules.csv</code>）
            — no_match / HOMBA acronym 衝突で、fullname 側が妥当なケースから文献展開を抽出。</li>
          <li><strong>文献略語優先の demotion</strong>（engine 0.8.x）
            — フルクエリが略語ルールに一致し、展開側が候補を取れたとき、生略語だけの HOMBA acronym ヒットを抑制。
            CA1 のように名前に略語が埋め込まれる語は保護。DMS のような非類似 acronym 衝突は soft demotion。</li>
          <li><strong>略語展開後の alias 再適用</strong>
            — LHb → lateral habenula → lateral habenular nuclei など。</li>
          <li><strong>展開パスのスコアクエリ</strong>
            — specificity / content 判定を展開語句に対して行い、短い略語の過大ペナルティを回避。</li>
          <li><strong>インライン展開の安全弁</strong>
            — ローマ数字の文中展開禁止; 残トークンが修飾語・側性のみのときだけ文中置換
            （<code>DCN interpositus</code> / <code>laminae III-IV</code> を壊さない）。</li>
          <li><strong>nucleus/nuclei を non-content 化</strong>
            — <code>lateral nuclei accumbens</code> が扁桃体 lateral nucleus に勝つ誤爆を抑制。</li>
        </ol>
      </div>
    </section>

    <section>
      <h2>代表例（abbrev）</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>query</th><th>before</th><th>after</th></tr>
          </thead>
          <tbody>
            {''.join(showcase_html)}
          </tbody>
        </table>
      </div>
    </section>

    <section class="grid2" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0;border:none;background:transparent">
      <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
        <h2>改善例（{len(improved)}）</h2>
        <p class="note small">ラベル順位が良くなったクエリ（先頭 25）</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>kind</th><th>query</th><th>before</th><th>after</th></tr></thead>
            <tbody>{example_rows(improved, 25)}</tbody>
          </table>
        </div>
      </div>
      <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
        <h2>悪化例（{len(regressed)}）</h2>
        <p class="note small">ラベル順位が悪くなったクエリ（先頭 25）。<code>contra-DMS</code>/<code>ipsi-DMS</code> は baseline が migratory stream への誤 aligned で、striatum 親への broader_parent は文献優先の意図的変化。</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>kind</th><th>query</th><th>before</th><th>after</th></tr></thead>
            <tbody>{example_rows(regressed, 25)}</tbody>
          </table>
        </div>
      </div>
    </section>

    <section>
      <h2>残課題（原理的限界）</h2>
      <ul class="note">
        <li>HOMBA に文献区画がない場合（多くの striatal compartment 略語）は親への <code>broader_parent</code> が上限。</li>
        <li>ドット接尾辞付きマーカー（<code>BLA.ac</code>）や細胞型付きクエリは略語展開対象外のまま。</li>
        <li>曖昧なフルクエリ（bare <code>arcuate nucleus</code>）は延髄 vs 視床下部が競合し得る — abbrev <code>ARC</code> は視床下部を明示展開。</li>
        <li>top1 変更数: {len(changed_top)} / {total}</li>
      </ul>
    </section>

    <section>
      <h2>成果物</h2>
      <ul class="note">
        <li>engine: <code>rcs/rosetta_candidate_generator.py</code> (0.8.3)</li>
        <li>rules: <code>rcs/homba_abbrev_rules.csv</code></li>
        <li>runs: <code>playgrounds/260802_playground/runs/{esc(args.before)}</code> /
            <code>.../runs/{esc(args.after)}</code></li>
        <li>after no_match={after_sum.get('no_match_n')} /
            before no_match={before_sum.get('no_match_n')}</li>
      </ul>
    </section>
  </main>
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    print(f"wrote {out} improved={len(improved)} regressed={len(regressed)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
