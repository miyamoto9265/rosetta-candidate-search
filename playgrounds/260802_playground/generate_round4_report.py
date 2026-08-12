#!/usr/bin/env python3
"""Round4 improvement HTML report (vs round3 and baseline)."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

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


def esc(v: object) -> str:
    return html.escape(str(v or ""))


def lab(r: dict) -> str:
    if not r.get("top_homba_id"):
        return "no_match"
    return r.get("final_label") or "uncertain"


def load(tag: str):
    rows = list(
        csv.DictReader(
            (HERE / "runs" / tag / "validation_results.csv").open(encoding="utf-8-sig")
        )
    )
    summary = json.loads(
        (HERE / "runs" / tag / "summary.json").read_text(encoding="utf-8")
    )
    return rows, summary


def counts(rows, kind=None):
    c: Counter[str] = Counter()
    for r in rows:
        if kind and r.get("query_kind") != kind:
            continue
        c[lab(r)] += 1
    return dict(c)


def compare(before, after):
    bm = {(r["query_kind"], r["query"]): r for r in before}
    am = {(r["query_kind"], r["query"]): r for r in after}
    imp, reg = [], []
    for k, ar in am.items():
        br = bm.get(k)
        if not br:
            continue
        bl, al = lab(br), lab(ar)
        if bl == al:
            continue
        row = (k[0], k[1], bl, al, br, ar)
        if RANK.get(al, 9) < RANK.get(bl, 9):
            imp.append(row)
        elif RANK.get(al, 9) > RANK.get(bl, 9):
            reg.append(row)
    return imp, reg


def delta(a, b):
    d = b - a
    return f"+{d}" if d > 0 else str(d)


def metric_rows(b, a, total):
    out = []
    for key in LABEL_ORDER:
        if not b.get(key) and not a.get(key):
            continue
        bv, av = b.get(key, 0), a.get(key, 0)
        d = av - bv
        good = (key in {"aligned", "broader_parent"} and d > 0) or (
            key in {"wrong", "no_match", "source_or_ontology_issue"} and d < 0
        )
        bad = (key in {"aligned", "broader_parent"} and d < 0) or (
            key in {"wrong", "no_match", "source_or_ontology_issue"} and d > 0
        )
        dcls = "ok" if good else ("bad" if bad else "unknown")
        out.append(
            f"<tr><td><span class='pill {LABEL_CLASS.get(key,'unknown')}'>{esc(key)}</span></td>"
            f"<td class='num'>{bv}</td><td class='num'>{av}</td>"
            f"<td class='num'><span class='pill {dcls}'>{delta(bv, av)}</span></td></tr>"
        )
    return "".join(out)


def ex_rows(items, n=20):
    out = []
    for kind, q, bl, al, br, ar in items[:n]:
        out.append(
            "<tr>"
            f"<td>{esc(kind)}</td><td class='query-cell'>{esc(q)}</td>"
            f"<td><span class='pill {LABEL_CLASS.get(bl,'unknown')}'>{esc(bl)}</span>"
            f"<div class='muted small'>{esc((br.get('top_name') or '(no_match)')[:55])}</div></td>"
            f"<td><span class='pill {LABEL_CLASS.get(al,'unknown')}'>{esc(al)}</span>"
            f"<div class='muted small'>{esc((ar.get('top_name') or '(no_match)')[:55])}</div></td>"
            "</tr>"
        )
    return "".join(out) if out else "<tr><td colspan=4 class=muted>なし</td></tr>"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--before", default="round3_abbrev")
    p.add_argument("--after", default="round4_abbrev")
    p.add_argument("--baseline", default="baseline")
    args = p.parse_args()

    before_rows, before_sum = load(args.before)
    after_rows, after_sum = load(args.after)
    base_rows, base_sum = load(args.baseline)

    b_all, a_all = counts(before_rows), counts(after_rows)
    base_all = counts(base_rows)
    b_ab, a_ab = counts(before_rows, "abbrev"), counts(after_rows, "abbrev")
    imp, reg = compare(before_rows, after_rows)
    imp_b, reg_b = compare(base_rows, after_rows)

    showcase = [
        "TH", "DLS", "CN", "CP", "Acb", "dSC", "pTh", "CeM", "BN", "CUN",
        "contralateral MEC", "BLA Ppp1r1b", "CeA-CRF", "MDTGlut",
        "paraventricular nucleus", "arcuate nucleus", "caudal CP", "basal nucleus",
        "VP", "CA1",
    ]
    bm = {(r["query_kind"], r["query"]): r for r in before_rows}
    am = {(r["query_kind"], r["query"]): r for r in after_rows}
    show_html = []
    for q in showcase:
        # try abbrev then any
        br = bm.get(("abbrev", q)) or bm.get(("fullname", q))
        ar = am.get(("abbrev", q)) or am.get(("fullname", q))
        if not br or not ar:
            continue
        show_html.append(
            f"<tr><td class='query-cell'><code>{esc(q)}</code></td>"
            f"<td><span class='pill {LABEL_CLASS.get(lab(br),'unknown')}'>{esc(lab(br))}</span>"
            f"<div class='muted small'>{esc((br.get('top_name') or '(no_match)')[:50])}</div></td>"
            f"<td><span class='pill {LABEL_CLASS.get(lab(ar),'unknown')}'>{esc(lab(ar))}</span>"
            f"<div class='muted small'>{esc((ar.get('top_name') or '(no_match)')[:50])}</div></td></tr>"
        )

    total = len(after_rows)
    out = HERE / "runs" / args.after / "round4_improve_report.html"
    doc = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Round4 improve report — {esc(args.before)} → {esc(args.after)}</title>
<style>
:root {{ --bg:#f4f6f9; --panel:#fff; --text:#1a2332; --muted:#667085; --line:#d8dee8;
  --ok:#0b7a4b; --parent:#2f6fed; --warn:#b7791f; --bad:#b42318; --issue:#7a3fb4; --unknown:#475467; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:28px 32px 20px; background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%); color:#fff; }}
header h1 {{ margin:0 0 8px; font-size:24px; }}
header p {{ margin:0; color:#cbd5e1; max-width:1000px; line-height:1.65; font-size:14px; }}
main {{ padding:22px 32px 56px; max-width:1400px; margin:0 auto; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin:0 0 16px; }}
h2 {{ margin:0 0 12px; font-size:18px; }}
h3 {{ margin:16px 0 8px; font-size:14px; color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(4,minmax(140px,1fr)); gap:10px; margin:12px 0 4px; }}
.card {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:#fafbfd; }}
.card-title {{ color:var(--muted); font-size:12px; }}
.card-value {{ font-size:24px; font-weight:700; margin-top:2px; font-variant-numeric:tabular-nums; }}
.card-sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; font-size:13px; }}
th {{ background:#f2f4f7; font-size:12px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.muted {{ color:var(--muted); }} .small {{ font-size:12px; }}
.note {{ color:var(--muted); line-height:1.65; font-size:13px; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; color:#fff; font-size:11px; font-weight:600; }}
.pill.ok {{ background:var(--ok); }} .pill.parent {{ background:var(--parent); }}
.pill.warn {{ background:var(--warn); }} .pill.bad {{ background:var(--bad); }}
.pill.issue {{ background:var(--issue); }} .pill.unknown {{ background:var(--unknown); }}
code {{ background:#eef2f6; border-radius:4px; padding:1px 5px; font-size:12px; }}
.query-cell {{ font-weight:600; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.table-wrap {{ max-height:480px; overflow:auto; border:1px solid var(--line); border-radius:10px; }}
ol.tight li {{ margin:6px 0; line-height:1.6; }}
</style>
</head>
<body>
<header>
  <h1>Round4 精度改善レポート</h1>
  <p>
    ロードマップ P1–P2（高信頼衝突解消・cell-type strip・fullname 曖昧性・複合句）を
    engine 0.8.4 で実装した結果です。比較: <code>{esc(args.before)}</code> → <code>{esc(args.after)}</code>
    （デプロイなし。判定は Flash×3 固定）。
  </p>
</header>
<main>
<section>
  <h2>サマリー</h2>
  <div class="cards">
    <div class="card"><div class="card-title">no_match</div>
      <div class="card-value">{a_all.get('no_match',0)}</div>
      <div class="card-sub">r3 {b_all.get('no_match',0)} → {delta(b_all.get('no_match',0), a_all.get('no_match',0))}
        / baseline {base_all.get('no_match',0)}</div></div>
    <div class="card"><div class="card-title">aligned</div>
      <div class="card-value">{a_all.get('aligned',0)}</div>
      <div class="card-sub">r3 {b_all.get('aligned',0)} → {delta(b_all.get('aligned',0), a_all.get('aligned',0))}
        / baseline {base_all.get('aligned',0)}</div></div>
    <div class="card"><div class="card-title">wrong</div>
      <div class="card-value">{a_all.get('wrong',0)}</div>
      <div class="card-sub">r3 {b_all.get('wrong',0)} → {delta(b_all.get('wrong',0), a_all.get('wrong',0))}
        / baseline {base_all.get('wrong',0)}</div></div>
    <div class="card"><div class="card-title">r3→r4 改善/悪化</div>
      <div class="card-value">{len(imp)} / {len(reg)}</div>
      <div class="card-sub">baseline→r4: {len(imp_b)} / {len(reg_b)}</div></div>
  </div>
  <h3>全体ラベル（round3 → round4）</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>label</th><th class="num">round3</th><th class="num">round4</th><th class="num">Δ</th></tr></thead>
    <tbody>{metric_rows(b_all, a_all, total)}</tbody>
  </table></div>
  <h3>abbrev のみ</h3>
  <div class="table-wrap"><table>
    <thead><tr><th>label</th><th class="num">round3</th><th class="num">round4</th><th class="num">Δ</th></tr></thead>
    <tbody>{metric_rows(b_ab, a_ab, sum(a_ab.values()) or 1)}</tbody>
  </table></div>
</section>

<section>
  <h2>Round4 で入れた変更（engine 0.8.4）</h2>
  <ol class="tight note">
    <li><b>P1 衝突 demotion 強化</b> — <code>area TH</code> を primary embed から除外。soft demotion を acronym 衝突＋複合句内の裸略語残りに拡大。展開パスは content overlap 必須。</li>
    <li><b>P1 cell-type / marker strip</b> — <code>BLA Ppp1r1b</code>、<code>CeA-CRF</code>、<code>MDTGlut</code>、<code>NAc-S D1-SPNs</code> などから分子タグを剥がして ROI 検索。</li>
    <li><b>P1 高信頼衝突ルール追加</b> — CP/Acb/dSC/pTh/CUN/PCx/OP/ANT/… などコーパス fullname と整合する文献展開を追加。</li>
    <li><b>P2 fullname 曖昧性</b> — bare <code>paraventricular nucleus</code> / <code>arcuate nucleus</code> を視床下部へ（alias）。</li>
    <li><b>P2 複合句</b> — 2文字略語の安全なインライン展開（caudal CP）、exact 同点時は name–query Jaccard でタイブレーク（basal nucleus → Meynert）。</li>
    <li><b>やらないこと</b> — HOMBA acronym 削除なし。オントロジーに無い区画への偽 exact なし。デプロイは未実施。</li>
  </ol>
</section>

<section>
  <h2>代表例（round3 → round4）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>query</th><th>round3</th><th>round4</th></tr></thead>
    <tbody>{''.join(show_html)}</tbody>
  </table></div>
</section>

<section class="grid2" style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0;border:none;background:transparent">
  <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
    <h2>改善例（{len(imp)}）</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>kind</th><th>query</th><th>before</th><th>after</th></tr></thead>
      <tbody>{ex_rows(imp)}</tbody>
    </table></div>
  </div>
  <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
    <h2>悪化例（{len(reg)}）</h2>
    <div class="table-wrap"><table>
      <thead><tr><th>kind</th><th>query</th><th>before</th><th>after</th></tr></thead>
      <tbody>{ex_rows(reg)}</tbody>
    </table></div>
  </div>
</section>

<section>
  <h2>baseline からの通算</h2>
  <p class="note">
    no_match {base_sum.get('no_match_n')} → {after_sum.get('no_match_n')}
    （{delta(base_sum.get('no_match_n',0), after_sum.get('no_match_n',0))}）、
    aligned {base_all.get('aligned',0)} → {a_all.get('aligned',0)}、
    wrong {base_all.get('wrong',0)} → {a_all.get('wrong',0)}。
    useful ≈ aligned+broader:
    {base_all.get('aligned',0)+base_all.get('broader_parent',0)} →
    {a_all.get('aligned',0)+a_all.get('broader_parent',0)}。
  </p>
</section>
</main>
</body>
</html>
"""
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out} imp={len(imp)} reg={len(reg)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
