#!/usr/bin/env python3
"""Generate standalone improvement_02 DeepSeek review report."""

from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path


HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
DS = OUT / "deepseek_review"

final_summary = json.loads((DS / "final_summary.json").read_text(encoding="utf-8"))
analysis = json.loads((DS / "analysis_summary.json").read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


changed_rows = read_csv(DS / "changed_top1_with_deepseek.csv")
final_rows = read_csv(DS / "final_review.csv")


LABEL_JA = {
    "improved_better": "改善後が良い",
    "improved_worse": "改善後が悪い",
    "no_material_change": "実質変化なし",
    "both_wrong": "両方とも不適切",
    "needs_human_review": "人手確認",
    "homba_gap_or_source_issue": "HOMBA/入力側の課題",
}


def pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.1f}%" if d else "0.0%"


def label_badge(label: str) -> str:
    cls = {
        "improved_better": "ok",
        "improved_worse": "danger",
        "no_material_change": "muted",
        "both_wrong": "warn",
        "needs_human_review": "mod",
        "homba_gap_or_source_issue": "info",
    }.get(label, "muted")
    return f"<span class='badge {cls}'>{escape(LABEL_JA.get(label, label))}</span>"


def table_counts(title: str, counts: dict[str, int], total: int) -> str:
    order = [
        "no_material_change",
        "improved_better",
        "improved_worse",
        "both_wrong",
        "needs_human_review",
        "homba_gap_or_source_issue",
    ]
    rows = []
    for k in order:
        v = counts.get(k, 0)
        if not v:
            continue
        rows.append(
            f"<tr><td>{label_badge(k)}</td><td class='num'>{v}</td>"
            f"<td class='num'>{pct(v, total)}</td></tr>"
        )
    return (
        f"<h3>{escape(title)}</h3>"
        "<table><thead><tr><th>判定</th><th class='num'>件数</th>"
        "<th class='num'>割合</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def rows_table(title: str, intro: str, rows: list[dict[str, str]], limit: int | None = None) -> str:
    shown = rows[:limit] if limit else rows
    body = []
    for r in shown:
        body.append(
            "<tr>"
            f"<td>{escape(r['query'])}<br><span class='ds'>{escape(r['dataset'])}</span> "
            f"<span class='role'>{escape(r['role'])}</span></td>"
            f"<td>{escape(r['baseline_top1_name'])}<br><span class='flag'>{escape(r['baseline_flag'])}</span></td>"
            f"<td><strong>{escape(r['improved_top1_name'])}</strong><br>"
            f"<span class='flag'>{escape(r['improved_flag'])}</span></td>"
            f"<td>{label_badge(r['deepseek_label'])}<br>"
            f"<span class='conf'>conf={escape(str(r['deepseek_confidence']))}</span></td>"
            f"<td>{escape(r['deepseek_reason'])}</td>"
            "</tr>"
        )
    more = ""
    if limit and len(rows) > limit:
        more = f"<p class='note'>他 {len(rows) - limit} 件はCSVを参照。</p>"
    return (
        f"<h3>{escape(title)}</h3><p>{intro}</p>"
        "<table><thead><tr><th>クエリ</th><th>改善前 top-1</th>"
        "<th>改善後 top-1</th><th>DeepSeek判定</th><th>理由</th></tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
        + more
    )


def changed_by(label: str) -> list[dict[str, str]]:
    return [r for r in changed_rows if r["deepseek_label"] == label]


better = changed_by("improved_better")
worse = changed_by("improved_worse")
both_wrong = changed_by("both_wrong")
needs_review = changed_by("needs_human_review")
gap_or_source = changed_by("homba_gap_or_source_issue")
high_risk = [r for r in changed_rows if r["review_risk_bucket"] == "high_risk_accept_degraded"]

role_counts = final_summary["final_label_counts_by_role"]


CSS = """
:root{--bg:#f8fafc;--card:#fff;--border:#e2e8f0;--muted:#64748b;--text:#0f172a;
--blue:#2563eb;--blue2:#1e3a8a;--ok:#16a34a;--danger:#dc2626;--warn:#d97706;
--info:#0284c7;--mod:#7c3aed}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans JP",sans-serif;line-height:1.65}
.page{display:flex;max-width:1240px;margin:0 auto;gap:1.4rem;padding:1.4rem}
.sidebar{position:sticky;top:1rem;align-self:flex-start;width:220px;flex:none;font-size:.9rem}
.sidebar h2{font-size:.78rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.sidebar nav{display:flex;flex-direction:column;gap:.28rem}.sidebar a{color:#334155;text-decoration:none;padding:.25rem .45rem;border-radius:6px}
.sidebar a:hover{background:#e2e8f0}.main{flex:1;min-width:0}
.hero{background:linear-gradient(135deg,var(--blue),var(--blue2));color:#fff;border-radius:16px;padding:1.8rem 2rem;margin-bottom:1.3rem}
.hero h1{margin:.25rem 0 .7rem;font-size:1.75rem;line-height:1.25}.hero p{margin:.4rem 0}.eyebrow{text-transform:uppercase;font-size:.72rem;letter-spacing:.08em;opacity:.85}
section{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:1.35rem 1.55rem;margin-bottom:1.2rem}
h2{margin:0 0 .8rem;font-size:1.25rem;border-bottom:2px solid var(--border);padding-bottom:.4rem}
h3{font-size:1.02rem;margin:1.1rem 0 .45rem}.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:.75rem}
.stat{background:#f1f5f9;border:1px solid var(--border);border-radius:12px;padding:.85rem}.stat .label{font-size:.74rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}.stat .value{font-size:1.6rem;font-weight:700}.stat .sub{font-size:.78rem;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin:.65rem 0;font-size:.86rem;table-layout:fixed}
th,td{padding:.42rem .5rem;border-bottom:1px solid var(--border);vertical-align:top;text-align:left;overflow-wrap:anywhere}
th{background:#f1f5f9;color:#475569;font-size:.77rem;text-transform:uppercase;letter-spacing:.03em}
td.num,th.num{text-align:right;white-space:nowrap}.badge{display:inline-block;border-radius:999px;padding:.08rem .48rem;font-size:.72rem;font-weight:700}
.badge.ok{background:#dcfce7;color:#166534}.badge.danger{background:#fee2e2;color:#991b1b}.badge.warn{background:#fef3c7;color:#92400e}.badge.muted{background:#e2e8f0;color:#475569}.badge.info{background:#e0f2fe;color:#075985}.badge.mod{background:#ede9fe;color:#5b21b6}
.callout{border-radius:10px;padding:.85rem 1rem;margin:.75rem 0;font-size:.92rem}.callout.ok{background:#f0fdf4;border:1px solid #bbf7d0}.callout.warn{background:#fffbeb;border:1px solid #fde68a}.callout.info{background:#eff6ff;border:1px solid #bfdbfe}
code{background:#f1f5f9;border-radius:4px;padding:.05rem .28rem}.ds,.role,.flag,.conf,.note{font-size:.74rem;color:var(--muted)}.role{background:#eef2ff;padding:.05rem .3rem;border-radius:4px}
footer{text-align:center;color:var(--muted);font-size:.78rem;padding:1rem 0 2rem}
"""


HTML = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RCS improvement_02 差分評価レポート</title>
<style>{CSS}</style></head><body>
<div class="page">
<aside class="sidebar">
  <h2>目次</h2>
  <nav>
    <a href="#summary">サマリー</a>
    <a href="#method">1. 判定方法</a>
    <a href="#overall">2. 全体結果</a>
    <a href="#changed">3. top-1変更55件</a>
    <a href="#risk">4. 回帰候補5件</a>
    <a href="#files">5. 出力ファイル</a>
  </nav>
</aside>
<main class="main">
<header class="hero">
  <p class="eyebrow">ROSETTA Candidate Search · improvement_02 · DeepSeek Review</p>
  <h1>improvement_02 差分評価レポート</h1>
  <p>
    このレポートは <code>report.html</code> を前提にしない完結版。
    improvement_02 の改善前後で RCS top-1 がどう変わったかを、
    DeepSeek <code>flash</code> + 必要時 <code>pro</code> で全921件再判定した。
  </p>
  <p>
    重要: このプロジェクトには確立済みの正解データセットはない。
    ここでの判定は、改善前候補と改善後候補のどちらが入力クエリに近いかをLLMで再レビューしたもの。
  </p>
</header>

<section id="summary">
  <h2>サマリー</h2>
  <div class="summary-grid">
    <div class="stat"><div class="label">評価対象</div><div class="value">{analysis['total']}</div><div class="sub">全レビュー対象レコード</div></div>
    <div class="stat"><div class="label">top-1 ID変更</div><div class="value">{analysis['changed_id']}</div><div class="sub">{pct(analysis['changed_id'], analysis['total'])}</div></div>
    <div class="stat"><div class="label">改善と判定</div><div class="value" style="color:var(--ok)">{analysis['changed_labels'].get('improved_better',0)}</div><div class="sub">top-1変更55件中</div></div>
    <div class="stat"><div class="label">悪化と判定</div><div class="value" style="color:var(--danger)">{analysis['changed_labels'].get('improved_worse',0)}</div><div class="sub">top-1変更55件中</div></div>
    <div class="stat"><div class="label">両方不適切</div><div class="value" style="color:var(--warn)">{analysis['changed_labels'].get('both_wrong',0)}</div><div class="sub">top-1変更55件中</div></div>
    <div class="stat"><div class="label">pro使用</div><div class="value">{final_summary['used_pro']}</div><div class="sub">不確実ケースを再判定</div></div>
  </div>
  <div class="callout ok">
    <strong>結論:</strong> top-1 が変わった55件のうち、29件は改善後の方が良い。
    明確な悪化は4件。さらに、以前LLMがacceptしていた集合から出た高リスクな変化は5件あり、
    これは個別に扱うべき。
  </div>
  <div class="callout warn">
    <strong>注意:</strong> 18件は「両方とも不適切」と判定された。
    これは improvement_02 が解決したというより、誤った高めの候補を別候補または低信頼側へ動かしたケースを含む。
    そのため、単純に「改善/悪化」だけでなく「まだ未解決」として扱う必要がある。
  </div>
</section>

<section id="method">
  <h2>1. 判定方法</h2>
  <p>
    入力は <code>output/improved_full_results.csv</code>。改善前 top-1 と改善後 top-1 を全921件で比較した。
    1 API call あたり5件に抑え、まず <code>deepseek-v4-flash</code> で全件判定し、
    confidence が低いもの・人手確認相当・accept済み候補が悪化した疑いのあるものを
    <code>deepseek-v4-pro</code> で再判定した。
  </p>
  <ul>
    <li>校正: 14件のサンプルでプロンプトA/Bを比較し、Bを採用。</li>
    <li>flash: 921/921件を判定。</li>
    <li>pro: 20件を昇格。うち初回失敗した5件は再試行して最終結果に反映。</li>
    <li>最終ラベル: <code>improved_better</code>, <code>improved_worse</code>, <code>no_material_change</code>, <code>both_wrong</code>, <code>needs_human_review</code>, <code>homba_gap_or_source_issue</code>。</li>
  </ul>
</section>

<section id="overall">
  <h2>2. 全体結果</h2>
  {table_counts("全921件のDeepSeek最終判定", final_summary['final_label_counts'], final_summary['total_records'])}
  <h3>レビュー区分別</h3>
  <table><thead><tr><th>レビュー区分</th><th>判定内訳</th></tr></thead><tbody>
    <tr><td><code>llm_accept_top1</code></td><td>{escape(json.dumps(role_counts['llm_accept_top1'], ensure_ascii=False))}</td></tr>
    <tr><td><code>llm_reject_top1</code></td><td>{escape(json.dumps(role_counts['llm_reject_top1'], ensure_ascii=False))}</td></tr>
    <tr><td><code>llm_out_of_scope_for_rcs</code></td><td>{escape(json.dumps(role_counts['llm_out_of_scope_for_rcs'], ensure_ascii=False))}</td></tr>
  </tbody></table>
  <p class="note">
    <code>no_material_change</code> が多いのは、921件の大半で top-1 ID が変わっていないため。
    差分評価では次の「top-1変更55件」を主に見る。
  </p>
</section>

<section id="changed">
  <h2>3. top-1 が変わった55件</h2>
  {table_counts("top-1変更55件の判定", analysis['changed_labels'], analysis['changed_id'])}
  {rows_table("3-1. 改善後が良いと判定された例", "視床核の表記ゆれ、親から具体候補への移動、明らかな誤候補から近い候補への移動が含まれる。", better, limit=12)}
  {rows_table("3-2. 改善後が悪いと判定された例", "改善後候補が片側だけを拾った、または粗い候補へ戻ったケース。", worse)}
  {rows_table("3-3. 両方とも不適切な例", "改善前も改善後も入力クエリに十分対応していない。改善後が低信頼へ落ちたものも含まれる。", both_wrong, limit=10)}
  {rows_table("3-4. HOMBA/入力側の課題", "RCS側だけで1候補へ決めるのが難しい、または入力ラベル側の問題が疑われるもの。", gap_or_source)}
</section>

<section id="risk">
  <h2>4. 回帰候補5件</h2>
  <p>
    以前のLLMレビューで <code>llm_accept_top1</code> に入っていたもののうち、
    DeepSeekが <code>improved_worse</code> または <code>both_wrong</code> と判定した5件。
    improvement_02を本体へ入れる場合、少なくともこの5件は個別対策またはガードが必要。
  </p>
  {rows_table("4-1. 高リスクな変化", "この5件は改善結果として数えない。明確な悪化または未解決として扱う。", high_risk)}
</section>

<section id="files">
  <h2>5. 出力ファイル</h2>
  <ul>
    <li><code>output/deepseek_review/final_review.csv</code>: 全921件のflash/pro/final判定。</li>
    <li><code>output/deepseek_review/changed_top1_with_deepseek.csv</code>: top-1 IDが変わった55件だけを抽出。</li>
    <li><code>output/deepseek_review/analysis_summary.json</code>: 変更有無別の集計。</li>
    <li><code>output/deepseek_review/final_summary.json</code>: 全体集計。</li>
    <li><code>output/deepseek_review/accept_worse_or_both_wrong.json</code>: 高リスク5件。</li>
    <li><code>deepseek_review_runner.py</code>: DeepSeek判定パイプライン。APIキーは環境変数から読む。</li>
  </ul>
</section>

<footer>
  ROSETTA Candidate Search · improvement_02 · report_02.html · DeepSeek review over 921 records
</footer>
</main></div></body></html>
"""


out = HERE / "report_02.html"
out.write_text(HTML, encoding="utf-8")
print(f"Wrote {out}")

