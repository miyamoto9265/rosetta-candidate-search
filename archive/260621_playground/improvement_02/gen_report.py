#!/usr/bin/env python3
"""Generate the improvement_02 final HTML report from the measured results."""
from __future__ import annotations

import csv
import json
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "output"

metrics = json.loads((OUT / "metrics.json").read_text(encoding="utf-8"))
B, I = metrics["baseline"], metrics["improved"]

results: dict[tuple[str, str], dict] = {}
with (OUT / "improved_full_results.csv").open(encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        results[(r["dataset"], r["query"])] = r


def row(ds: str, q: str):
    return results.get((ds, q))


def flag_badge(flag: str) -> str:
    cls = {
        "high_confidence": "ok", "needs_review": "warn",
        "low_confidence": "muted", "modifier_conflict": "mod",
    }.get(flag, "muted")
    return f"<span class='badge {cls}'>{escape(flag)}</span>"


def example_table(title: str, intro: str, queries: list[tuple[str, str]]) -> str:
    body = []
    for ds, q in queries:
        r = row(ds, q)
        if not r:
            body.append(f"<tr><td colspan='5'>{escape(q)} (no data)</td></tr>")
            continue
        body.append(
            "<tr>"
            f"<td>{escape(q)} <span class='ds'>{ds[:3]}</span></td>"
            f"<td class='mono'>{escape(r['base_name'])}</td>"
            f"<td class='num'>{r['base_score']}</td>"
            f"<td class='mono'><strong>{escape(r['impr_name'])}</strong></td>"
            f"<td class='num'>{r['impr_score']}<br>{flag_badge(r['impr_flag'])}</td>"
            "</tr>"
        )
    return (
        f"<h3>{escape(title)}</h3><p>{intro}</p>"
        "<table><thead><tr><th>クエリ (入力)</th><th>改善前 top-1</th>"
        "<th class='num'>前</th><th>改善後 top-1</th><th class='num'>後</th>"
        "</tr></thead><tbody>" + "".join(body) + "</tbody></table>"
    )


# ---- curated example sets (verified from measured runs) --------------------
highconf_fixes = [
    ("species", "Ventrolateral thalamic nucleus"),
    ("species", "Ventromedial thalamic nucleus"),
    ("species", "Laterodorsal thalamic nucleus"),
    ("corpus", "Medial dorsal thalamic nucleus"),
    ("species", "Dorsal Lateral Leminscus Nucleus"),
]

dict_other = [
    ("species", "Saginum Nucleus"),
    ("species", "Septimbrial nucleus"),
    ("species", "Kolliker-Fuse Nucleus"),
    ("species", "Intergeniculate leaflet"),
    ("species", "Stria medullaris thalami"),
    ("species", "Optic tract/chiasma"),
]

trap_demotions = [
    ("corpus", "Anterior ventral insular area"),
    ("species", "Ventral orbital area"),
    ("corpus", "Ventral intraparietal area"),
    ("species", "Medial Raphe"),
    ("species", "Ventral striatal region, unspecified"),
    ("corpus", "Central opercular cortex (anterior)"),
]

hierarchy_fixes = [
    ("species", "Abducens Motor Nucleus"),
    ("species", "Spinal Trigeminal Nucleus Intermediate"),
    ("species", "Interanteromedial Thalamus"),
    ("species", "Intermediodorsal Thalamus"),
    ("species", "Paraventricular hypothalamic nucleus"),
    ("species", "Basomedial amygdaloid nucleus"),
    ("species", "Centrolateral and paracentral thalamic nuclei"),
]

review_accept_id_changes = [
    ("corpus", "Superior parietal gyrus"),
    ("species", "Anterior pituitary"),
    ("species", "Frontal orbital cortex, anterior"),
    ("species", "Ventromedial occipital cortex"),
    ("species", "Ventromedial thalamic nucleus (posterior and basal)"),
]

regressions = [
    ("species", "Cuneate Gracile Nuclei"),
    ("species", "Lateral Dorsal Thalamus"),
    ("species", "Lateral Dorsal Amygdaloid Nucleus"),
    ("species", "Ventroposterior Medial and Lateral Thalamus"),
]


def flags_table() -> str:
    order = ["high_confidence", "needs_review", "modifier_conflict",
             "low_confidence"]
    rows = []
    for f in order:
        b = B["flags"].get(f, 0)
        i = I["flags"].get(f, 0)
        d = i - b
        sign = "+" if d > 0 else ""
        col = ("var(--ok,#16a34a)" if (f == "high_confidence" and d >= 0)
               else "var(--muted)")
        rows.append(
            f"<tr><td>{f}</td><td class='num'>{b}</td><td class='num'>{i}</td>"
            f"<td class='num' style='color:{col}'>{sign}{d}</td></tr>"
        )
    return ("<table><thead><tr><th>review_flag</th><th class='num'>改善前</th>"
            "<th class='num'>改善後</th><th class='num'>Δ</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table>")


CSS = """
:root{--accent:#2563eb;--accent-dark:#1e3a8a;--muted:#64748b;--ok:#16a34a;
--warn:#d97706;--danger:#dc2626;--bg:#f8fafc;--card:#fff;--border:#e2e8f0;}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,
"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans JP",sans-serif;color:#0f172a;
background:var(--bg);line-height:1.65}
.page{display:flex;max-width:1180px;margin:0 auto;gap:1.5rem;padding:1.5rem}
.sidebar{position:sticky;top:1rem;align-self:flex-start;width:210px;flex:none;
font-size:.9rem}.sidebar h2{font-size:.8rem;text-transform:uppercase;color:var(--muted);
letter-spacing:.04em}.sidebar nav{display:flex;flex-direction:column;gap:.3rem}
.sidebar a{color:#334155;text-decoration:none;padding:.2rem .4rem;border-radius:6px}
.sidebar a:hover{background:#eef2f7}
.main{flex:1;min-width:0}
.hero{background:linear-gradient(135deg,var(--accent),var(--accent-dark));color:#fff;
border-radius:16px;padding:1.8rem 2rem;margin-bottom:1.5rem}
.hero h1{margin:.2rem 0 .6rem;font-size:1.7rem;line-height:1.25}
.eyebrow{text-transform:uppercase;letter-spacing:.08em;font-size:.72rem;opacity:.85;margin:0}
.hero .meta{font-size:.9rem;opacity:.95}
section{background:var(--card);border:1px solid var(--border);border-radius:14px;
padding:1.4rem 1.6rem;margin-bottom:1.3rem}
h2{margin-top:0;font-size:1.3rem;border-bottom:2px solid var(--border);padding-bottom:.4rem}
h3{font-size:1.05rem;margin:1.2rem 0 .4rem}
table{width:100%;border-collapse:collapse;margin:.6rem 0;font-size:.86rem;table-layout:fixed}
th,td{text-align:left;padding:.4rem .5rem;border-bottom:1px solid var(--border);
overflow-wrap:anywhere;vertical-align:top}
th{background:#f1f5f9;font-size:.78rem;text-transform:uppercase;letter-spacing:.03em;color:#475569}
td.num,th.num{text-align:right;white-space:nowrap}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.82rem}
.summary-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.8rem;margin:1rem 0}
.stat-card{background:var(--bg);border:1px solid var(--border);border-radius:12px;padding:.9rem 1rem}
.stat-card .label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.stat-card .value{font-size:1.7rem;font-weight:700}
.stat-card .delta{font-size:.8rem;color:var(--muted)}
.badge{display:inline-block;padding:.05rem .45rem;border-radius:999px;font-size:.72rem;font-weight:600}
.badge.ok{background:#dcfce7;color:#166534}.badge.warn{background:#fef3c7;color:#92400e}
.badge.mod{background:#ede9fe;color:#5b21b6}.badge.muted{background:#e2e8f0;color:#475569}
.ds{font-size:.66rem;color:var(--muted);background:#eef2f7;padding:.04rem .3rem;border-radius:4px}
.callout{border-radius:10px;padding:.8rem 1rem;margin:.8rem 0;font-size:.9rem}
.callout.ok{background:#f0fdf4;border:1px solid #bbf7d0}
.callout.info{background:#eff6ff;border:1px solid #bfdbfe}
.callout.warn{background:#fffbeb;border:1px solid #fde68a}
code{background:#f1f5f9;padding:.05rem .3rem;border-radius:4px;font-size:.85em}
footer{color:var(--muted);font-size:.8rem;padding:1rem 0 2rem;text-align:center}
ul{margin:.4rem 0;padding-left:1.2rem}li{margin:.25rem 0}
"""

HTML = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>RCS improvement_02 — 改善結果レポート</title>
<style>{CSS}</style></head><body>
<div class="page">
<aside class="sidebar">
  <h2>目次</h2>
  <nav>
    <a href="#summary">サマリー</a>
    <a href="#method">1. 評価方法</a>
    <a href="#algo">2. 変更内容</a>
    <a href="#dict">3. 追加辞書</a>
    <a href="#results">4. 結果と例</a>
    <a href="#regress">5. 注意点</a>
    <a href="#merge">6. マージ方針</a>
  </nav>
</aside>
<main class="main">
<header class="hero">
  <p class="eyebrow">ROSETTA Candidate Search · Playground · improvement_02</p>
  <h1>RCS 改善結果レポート<br/>アルゴリズム変更 + playground 辞書</h1>
  <p class="meta">
    <code>improvement_01</code> で整理した改善案を <code>improvement_02</code> で実装した。
    目視確認済みの4 CSVを評価基準にし、改善前(round3相当)と改善後を比較した。
  </p>
</header>

<section id="summary">
  <h2>サマリー</h2>
  <p>
    今回の変更は、主に「明らかな誤候補を落とす」「視床核などの表記ゆれを正しい候補へ寄せる」
    「親候補が具体候補を押しのけるケースを減らす」ためのもの。最も重要な確認点は、
    <strong>LLMレビューで accept していた high_confidence の top-1 を1件も落としていない</strong>こと。
  </p>
  <div class="summary-grid">
    <div class="stat-card"><div class="label">LLM accept ID を維持</div>
      <div class="value">{I['llm_accept_top1_same_id']}/{I['llm_accept_top1_total']}</div>
      <div class="delta">改善前 {B['llm_accept_top1_same_id']}</div></div>
    <div class="stat-card"><div class="label">high 降格</div>
      <div class="value" style="color:var(--ok)">0</div>
      <div class="delta">LLM accept high は {B['llm_accept_top1_highconf']}→{I['llm_accept_top1_highconf']}</div></div>
    <div class="stat-card"><div class="label">明確に正解化</div>
      <div class="value" style="color:var(--ok)">{I['curated_target_matched']}/17</div>
      <div class="delta">確認対象17件中。改善前は {B['curated_target_matched']}/17</div></div>
    <div class="stat-card"><div class="label">既知の誤りに介入</div>
      <div class="value">{I['llm_reject_top1_changed']}</div>
      <div class="delta">111件中。改善前は {B['llm_reject_top1_changed']} 件</div></div>
    <div class="stat-card"><div class="label">high_confidence 総数</div>
      <div class="value">{I['flags']['high_confidence']}</div>
      <div class="delta">前 {B['flags']['high_confidence']} ({I['flags']['high_confidence']-B['flags']['high_confidence']:+d})</div></div>
  </div>
  <div class="callout ok">
    <strong>結論:</strong> 視床核の表記ゆれや外側毛帯核のスペルミスは high_confidence で正解化できた。
    方向語だけに引っ張られる誤候補は low_confidence に落ち、親候補が強すぎるケースも一部改善した。
    一方で、全ての誤りが解消したわけではないため、本体へ入れる前に残件は確認対象として扱う。
  </div>
  <div class="callout info">
    <strong>「既知の誤りに介入 35」は悪化ではない。</strong>
    これは「もともと top-1 が誤りだった111件」の中で、改善後に top-1 が変わった件数。
    つまり、誤った候補をそのまま放置せず、別候補へ動かせた件数を表す。
    35件すべてが正解になったという意味ではないが、悪化指標ではない。
  </div>
  <h3>review_flag 分布の変化</h3>
  {flags_table()}
  <p style="font-size:.85rem;color:var(--muted)">
    high_confidence は全体で10件増えた。needs_review が減り、low_confidence が増えたのは、
    自信を持てない誤候補を review 帯から低信頼へ落としたため。</p>
</section>

<section id="method">
  <h2>1. 評価方法</h2>
  <p>評価には <code>improvement_01</code> で目視確認した4つのCSVを使った。</p>
  <ul>
    <li><code>1_highconf_correct</code> + <code>3_unresolved_correct</code> +
        <code>2_highconf_incorrect</code> の <code>correct_parent</code> を
        「このレビュー時点では top-1 を accept」として扱った。合計689件。
        これは確立済みの正解IDではない。</li>
    <li><code>2</code> の wrong/questionable + <code>4</code> の B_algo/C_dict =
        <strong>既知の誤り 111件</strong>。ここでは top-1 が変わること自体は悪化ではなく、
        改善が介入できたことを示す。</li>
    <li><code>4</code> の D_homba_gap / E_source_typo は、HOMBA側の粒度不足または入力データの誤記なので、
        RCSの改善対象から外した。</li>
  </ul>
  <p>
    改善前は round3 相当のエンジンと辞書、改善後は <code>improvement_02/rcs_engine.py</code>
    と playground 辞書で比較した。比較対象は全921クエリ。
  </p>
</section>

<section id="algo">
  <h2>2. 変更内容</h2>
  <h3>2-1. 方向語だけで当たった候補を下げる</h3>
  <p>
    <code>ventral</code>、<code>posterior</code>、<code>cortex</code> など、単独では場所を特定しにくい語だけで
    fuzzy/bm25 が当たるケースを抑制した。識別語を共有しない候補はスコアを0.50以下にして、
    review対象ではなく low_confidence に落とす。
  </p>
  <p>
    ただし、単純に落とすと正しい候補も巻き込むため、語形差
    (<code>striatal</code> と <code>striatum</code> など)は同じ語として扱い、
    parietal/temporal のような lobe 語は保護した。
  </p>
  <h3>2-2. 親候補が強すぎるケースを抑える</h3>
  <p>
    複数の子候補が見つかると共通の親を上げる仕組みがあるが、これが具体的な正解候補を追い抜くことがあった。
    そこで、具体候補が十分に見えている場合は、親候補のスコアをその具体候補より少し低く抑えた。
  </p>
  <h3>2-3. 辞書ルールに一方向指定を追加</h3>
  <p>
    <code>ventrolateral → ventral lateral</code> のような正規化は有効だが、双方向にすると
    別領域の名前まで変換されることがある。そこで alias 辞書に <code>bidirectional</code> 列を追加し、
    必要なルールは「クエリ側だけを変換する」形にした。
  </p>
</section>

<section id="dict">
  <h2>3. 追加した辞書</h2>
  <ul>
    <li><strong>視床核の表記ゆれ:</strong>
      <code>ventrolateral→ventral lateral</code>, <code>ventromedial→ventral medial</code>,
      <code>laterodorsal→lateral dorsal</code>, <code>medial dorsal→mediodorsal</code>,
      <code>ventroanterior</code>, <code>ventroposterior</code>, <code>centrolateral</code>。</li>
    <li><strong>スペル・語順の補正:</strong> <code>leminscus→lemniscus</code>,
      <code>kolliker→koelliker</code>, <code>saginum→sagulum</code>,
      <code>septimbrial→septofimbrial</code>, <code>chiasma→chiasm</code>,
      <code>leaflet→leaf</code>, <code>stria medullaris thalami→…of thalamus</code>,
      <code>X lemniscus nucleus→nucleus of X lemniscus</code>。</li>
  </ul>
  <div class="callout warn">
    明らかな入力ミス(<code>Antherior</code> など)は辞書に入れていない。辞書に誤記を取り込むと、
    本番運用で不要な誤マッチを増やすため、データ側で直す方針のまま。
  </div>
</section>

<section id="results">
  <h2>4. 結果と例</h2>
  {example_table("4-1. high_confidence で正解化した例",
                 "視床核の表記ゆれと外側毛帯核のスペルミスは、正しい候補を高信頼で返せるようになった。", highconf_fixes)}
  {example_table("4-2. 辞書追加で改善した例",
                 "綴り、語順、ラテン語表記のゆれを辞書で吸収した。", dict_other)}
  {example_table("4-3. 誤候補を low_confidence に落とした例",
                 "方向語だけで拾っていた候補は、正解にできなくても、自信のある候補として扱わないようにした。", trap_demotions)}
  {example_table("4-4. 親候補より具体候補を優先できた例",
                 "共通親が top-1 を取っていたケースで、より具体的な候補を上に出せるようになった。", hierarchy_fixes)}
</section>

<section id="regress">
  <h2>5. 注意点</h2>
  <p>
    LLMが前回 accept した top-1 ID の維持は 682/689 から 671/689 に下がっている。
    この数字だけ見ると悪くなったように見えるが、内訳を見ると、粗い親候補からより細かい候補に
    変わったものが多い。ここで使っているCSVは確立済みの正解データではなく、レビュー時点の判断なので、
    IDだけで評価すると「前回 accept したIDとは不一致」になる。
  </p>
  {example_table("5-1. 粗い親から具体候補に変わった例",
                 "これは機械的には前回acceptしたIDと不一致だが、解剖学的には改善と見なせるものが多い。",
                 review_accept_id_changes)}
  {example_table("5-2. 本当に注意が必要な例",
                 "一部では改善前より扱いが悪くなった可能性がある。いずれも high_confidence ではないため、運用上はレビュー対象に残る。",
                 regressions)}
  <div class="callout info">
    注意すべき例はあるが、いずれも <code>needs_review</code> / <code>low_confidence</code> /
    <code>modifier_conflict</code> に残っている。今回の変更で、LLMが accept していた high_confidence を落としたケースはない。
  </div>
</section>

<section id="merge">
  <h2>6. マージ方針</h2>
  <ul>
    <li><strong>本体に入れてよい候補:</strong> 方向語だけの誤マッチを落とす処理、親候補の過剰昇格を抑える処理、
      alias辞書の <code>bidirectional</code> 列対応。</li>
    <li><strong>辞書として入れてよい候補:</strong> 視床核の表記ゆれ、外側毛帯核、Koelliker/Kolliker、
      sagulum/Saginum などの一般的な表記ゆれ。</li>
    <li><strong>まだ入れない方がよいもの:</strong> 明らかな入力ミス、HOMBAに粒度がない概念、複合クエリを無理に1候補へ潰すルール。</li>
  </ul>
  <p style="font-size:.85rem;color:var(--muted)">再現コマンド: <code>python eval.py compare</code>
    / <code>python eval.py export</code>。
    成果物: <code>output/metrics.json</code>, <code>output/diff_baseline_vs_improved.csv</code>,
    <code>output/improved_full_results.csv</code>。</p>
</section>

<footer>ROSETTA Candidate Search · 260621_playground/improvement_02 ·
  measured over rcs_corpus + rcs_species (921 unique queries)</footer>
</main></div></body></html>
"""

out = HERE / "report.html"
out.write_text(HTML, encoding="utf-8")
print(f"Wrote {out}")
