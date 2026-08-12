#!/usr/bin/env python3
"""Generate HTML report proposing an agentic self-improvement loop for the
non-neocortex validation dataset, based on the baseline validation results."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "runs" / "baseline"
CSV_PATH = RUN / "validation_results.csv"
SUMMARY_PATH = RUN / "summary.json"
OUT_PATH = HERE / "policy_report.html"

LABEL_JA = {
    "aligned": "同一構造・同義語",
    "broader_parent": "正しい上位構造",
    "partial_or_narrower": "一部分・狭すぎる",
    "wrong": "異なる構造",
    "ambiguous": "判定困難",
    "source_or_ontology_issue": "入力/オントロジー問題",
    "no_consensus": "多数意見なし",
}
LABEL_CLASS = {
    "aligned": "ok",
    "broader_parent": "parent",
    "partial_or_narrower": "warn",
    "wrong": "bad",
    "ambiguous": "unknown",
    "source_or_ontology_issue": "issue",
    "no_consensus": "unknown",
}


def esc(v: object) -> str:
    return html.escape(str(v or ""))


def pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "0%"


def load() -> tuple[list[dict[str, str]], dict]:
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8-sig")))
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    return rows, summary


def main() -> int:
    rows, summary = load()
    total = len(rows)
    overall = summary["overall"]["label_counts"]

    by_struct: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for r in rows:
        by_struct[r["structure_name"]][r["query_kind"]] = r
    pairs = [v for v in by_struct.values() if "abbrev" in v and "fullname" in v]
    miss = [p for p in pairs if not p["abbrev"]["top_homba_id"] and p["fullname"]["top_homba_id"]]
    miss_full_aligned = sum(1 for p in miss if p["fullname"]["final_label"] == "aligned")
    aw_fa = [p for p in pairs if p["abbrev"]["final_label"] == "wrong" and p["fullname"]["final_label"] == "aligned"]

    abbrev = [r for r in rows if r["query_kind"] == "abbrev"]
    fullname = [r for r in rows if r["query_kind"] == "fullname"]
    abbrev_no_match = [r for r in abbrev if not r["top_homba_id"]]
    abbrev_wrong = [r for r in abbrev if r["final_label"] == "wrong"]
    fullname_wrong = [r for r in fullname if r["final_label"] == "wrong"]
    matched = [r for r in rows if r["top_homba_id"]]
    matched_aligned = sum(1 for r in matched if r["final_label"] == "aligned")

    def top_wrong(rs, n=12, min_score=0.0):
        out = sorted(
            [r for r in rs if float(r["score"] or 0) >= min_score],
            key=lambda r: (-int(r["n_mentions"] or 0), -float(r["score"] or 0)),
        )[:n]
        return out

    def table(rs, cols, n=100):
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = []
        for r in rs[:n]:
            tds = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
            body.append(f"<tr>{tds}</tr>")
        if not body:
            body.append("<tr><td colspan='99'>(none)</td></tr>")
        note = f"<p class='note'>{min(n, len(rs))} / {len(rs)} 件</p>" if len(rs) > n else ""
        return note + f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    abbrev_nm_samples = sorted(abbrev_no_match, key=lambda r: -int(r["n_mentions"] or 0))[:20]
    abbrev_wrong_samples = top_wrong(abbrev_wrong, 20, 0.75)
    fullname_wrong_samples = top_wrong(fullname_wrong, 20, 0.75)
    aw_fa_samples = sorted(
        aw_fa, key=lambda p: -int(p["abbrev"]["n_mentions"] or 0)
    )[:20]

    fams = Counter()
    for r in abbrev_wrong:
        q = (r["query"] + " " + r["fullname"]).lower()
        if any(k in q for k in ("ca1", "ca3", "hippocamp", "dg ")):
            fams["hippocampal"] += 1
        elif "thalam" in q:
            fams["thalamus"] += 1
        elif "striat" in q or "cp" in q or "putamen" in q:
            fams["striatum"] += 1
        elif "amygdal" in q or "bla" in q or "cea" in q:
            fams["amygdala"] += 1
        elif any(k in q for k in ("brainstem", "midbrain", "pons", "medulla")):
            fams["brainstem"] += 1
        elif "spinal" in q:
            fams["spinal"] += 1
        else:
            fams["other"] += 1

    html_out = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>non-neocortex 改善プロセス方針 — 260802</title>
  <style>
    :root {{
      --bg:#f4f6f9; --panel:#fff; --text:#1a2332; --muted:#667085; --line:#d8dee8;
      --ok:#0b7a4b; --parent:#2f6fed; --warn:#b7791f; --bad:#b42318; --issue:#7a3fb4; --unknown:#475467;
    }}
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
    .card-value {{ font-size:24px; font-weight:700; margin-top:2px; }}
    .card-sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
    table {{ width:100%; border-collapse:collapse; }}
    th,td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; font-size:13px; }}
    th {{ background:#f2f4f7; font-size:12px; }}
    .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
    .note {{ color:var(--muted); line-height:1.6; font-size:13px; }}
    code {{ background:#eef2f6; border-radius:4px; padding:1px 5px; font-size:12px; }}
    .pill {{ display:inline-block; padding:2px 8px; border-radius:999px; color:#fff; font-size:11px; font-weight:600; }}
    .pill.ok {{ background:var(--ok); }} .pill.parent {{ background:var(--parent); }} .pill.warn {{ background:var(--warn); }}
    .pill.bad {{ background:var(--bad); }} .pill.issue {{ background:var(--issue); }} .pill.unknown {{ background:var(--unknown); }}
    ol.tight li {{ margin:6px 0; line-height:1.6; }}
    .flow {{ background:#0f172a; color:#e2e8f0; border-radius:10px; padding:14px 16px; font-family:ui-monospace,Consolas,monospace; font-size:12.5px; line-height:1.7; overflow:auto; }}
    .kbd {{ background:#eef2f6; border-radius:4px; padding:0 4px; }}
  </style>
</head>
<body>
  <header>
    <h1>non-neocortex — Agent自律改善プロセス方針</h1>
    <p>
      精査済み non_neocortex suitable（abbrev 2,368 / fullname 1,090）の baseline 検証結果から、
      「テスト→問題分析→修正→再テスト」を回すための実データ観察と方針です。
    </p>
  </header>
  <main>
    <section>
      <h2>1. 実データで見えた構造</h2>
      <div class="cards">
        <div class="card"><div class="card-title">総クエリ</div><div class="card-value">{total}</div>
          <div class="card-sub">abbrev {len(abbrev)} / fullname {len(fullname)}</div></div>
        <div class="card"><div class="card-title">RCS マッチ</div><div class="card-value">{len(matched)}</div>
          <div class="card-sub">no_match {total-len(matched)}</div></div>
        <div class="card"><div class="card-title">マッチ中 aligned</div><div class="card-value">{matched_aligned}</div>
          <div class="card-sub">{pct(matched_aligned, len(matched))}</div></div>
        <div class="card"><div class="card-title">wrong（全体）</div><div class="card-value">{overall.get('wrong',0)}</div>
          <div class="card-sub">abbrev {len(abbrev_wrong)} / fullname {len(fullname_wrong)}</div></div>
      </div>
      <ol class="tight">
        <li><b>略語の no_match が主問題。</b> abbrev の RCS 無マッチ <b>{len(abbrev_no_match)}</b> 件。
            同一構造の fullname はヒットしているのに abbrev が落ちるケースが <b>{len(miss)}</b> 件
            （うち fullname が aligned なのは {miss_full_aligned}）。→ <b>略語テーブル／略語展開の未網羅</b> が最大の欠陥。</li>
        <li><b>略語の誤ヒットは高スコア混在。</b> abbrev wrong {len(abbrev_wrong)} 件の多くは fuzzy/bm25 由来で、
            <code>VP</code>→ventral posterior visual area（正: ventral pallidum）、<code>DMS</code>→dorsal migratory stream（正: dorsomedial striatum）
            など、<b>同字面の別構造に吸われる</b>。高スコア（≥0.75）でも wrong が目立つ。</li>
        <li><b>fullname は比較的健全だが「上位構造」判定が多い。</b> fullname aligned 419 / broader_parent 354。
            これは RCS の階層親昇格ではなく、<b>LLM 判定ラベル</b>（top1 が解剖学的に親／広い）である。
            親昇格（<code>_promote_common_parents</code>）は v0.8.0 で廃止済み。</li>
        <li><b>判定の安定性は高い。</b> vote 3-0 が 2,542 件、high certainty 3,050 件。
            3-pass（Flash 0731）の多数決は改善ループの「審判」として十分使える。</li>
      </ol>
    </section>

    <section>
      <h2>2. 失敗ファミリ（abbrev wrong）</h2>
      <table>
        <thead><tr><th>family</th><th class="num">件数</th></tr></thead>
        <tbody>
          {''.join(f"<tr><td>{esc(k)}</td><td class='num'>{v}</td></tr>" for k,v in fams.most_common())}
        </tbody>
      </table>
      <p class="note">other は文脈依存の短い略語（VP/DMS/DLS/CP/PP/PV 等）が中心。同字面の別構造に吸われる「略語衝突」が本質。</p>
    </section>

    <section>
      <h2>3. 改善プロセス方針（LLM-based Recursive Improvement）</h2>
      <p class="note">
        <code>eval_harness.py</code> は判定キャッシュ（query→top1）を持つので、
        <b>RCS が変わって top1 が変わった組だけ再判定</b>すればよい。3-pass は Flash 0731 のみで統一。
      </p>
      <div class="flow">
Round 0  baseline（本レポート）… abbrev 改善余地が最大
  │
Round 1  略語辞書拡充（最優先）
  │   ├─ abbrev no_match & fullname hit {len(miss)} 件 → abbrev テーブル追加
  │   └─ abbrev wrong 高スコア衝突 → abbrev→正式名の一意化ルール
  │   期待: abbrev no_match {len(abbrev_no_match)} → 大幅減 / abbrev aligned ↑
  │
Round 2  誤ヒット抑制
  │   ├─ 同字面衝突（VP/DMS/DLS/CP/PP/PV…）に種別・文脈制約
  │   └─ fullname 一致時は abbrev を fullname 展開で再スコア
  │   期待: wrong {overall.get('wrong',0)} ↓ / aligned 1,139 ↑
  │
Round 3  fullname 側の精度（親昇格は既に廃止済み）
      ├─ broader_parent 354 = LLM が「top1 が親／広い」と判定した件数
      │   （RCS が親を昇格させたわけではない）
      ├─ alias / specificity / region-anchor で具体名を top1 に押し上げる
      └─ partial_or_narrower 243 の化合物・部分構造の扱いを整理
  </div>
      <ol class="tight">
        <li><b>評価指標</b>: aligned_rate（matched 中 aligned 割合）、abbrev_no_match、wrong_high_conf（score≥0.75 で wrong）を主 KPI。
            broader_parent は「正しいが粗い」として aligned と別に追跡。</li>
        <li><b>判定は固定</b>（Flash 0731 ×3、pro なし）。審判を変えないことで改善量を素直に比較する。</li>
        <li><b>回帰ガード</b>: 既に aligned のペアが悪化しないよう、毎ラウンド差分レポート（improved/regressed）を必須化。</li>
        <li><b>コスト制御</b>: 変化した query→top1 のみ再判定。fullname 側は安定なので abbrev 優先。</li>
      </ol>
    </section>

    <section>
      <h2>4. Round 1 の対象例 — abbrev no_match &amp; fullname hit</h2>
      {table(abbrev_nm_samples, ['n_mentions','query','fullname'], 20)}
    </section>

    <section>
      <h2>5. Round 2 の対象例 — abbrev wrong（高スコア）</h2>
      {table(abbrev_wrong_samples, ['n_mentions','query','top_name','score','pass1_reason'], 20)}
    </section>

    <section>
      <h2>6. fullname 側の wrong（上位ヒット/別構造）</h2>
      {table(fullname_wrong_samples, ['n_mentions','query','top_name','score','pass1_reason'], 20)}
    </section>

    <section>
      <h2>7. abbrev wrong &amp; fullname aligned（略語だけが外れる）</h2>
      {table([p['abbrev'] for p in aw_fa_samples], ['n_mentions','query','top_name','score','pass1_reason'], 20)}
    </section>

    <section>
      <h2>8. まとめ</h2>
      <ol class="tight">
        <li>最大の改善対象は <b>abbrev の no_match {len(abbrev_no_match)} 件</b>（うち fullname はヒットする {len(miss)} 件）。略語テーブル拡充が効く。</li>
        <li>次点は <b>abbrev wrong の高スコア衝突</b>。同字面の別構造への誤マッチを、fullname 文脈と種別制約で絞る。</li>
        <li>判定は Flash 0731 ×3 で固定。キャッシュ再利用で安く再テストし、<code>generate_report.py</code> で各ラウンドを同じUIで比較する。</li>
      </ol>
    </section>
  </main>
</body>
</html>
"""
    OUT_PATH.write_text(html_out, encoding="utf-8")
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
