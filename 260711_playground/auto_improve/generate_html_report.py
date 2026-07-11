#!/usr/bin/env python3
"""Build a self-contained HTML report for the RCS auto-improvement run.

Reads the baseline and final evaluation summaries / records produced by
``eval_harness.py`` and renders a single static HTML file that documents:

* the headline label movement (baseline -> final),
* per-dataset breakdown,
* every case that improved or regressed between the two runs,
* the residual ``wrong`` cases grouped by root-cause family,
* the algorithm / scoring / dictionary changes that produced the gain.

Usage
-----
    python generate_html_report.py --baseline baseline --final round6 \\
        --out ../top1_consistency_review/auto_improve_report.html
"""
from __future__ import annotations

import argparse
import csv
import html
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"

try:
    from generate_wrong_report import ONTOLOGY_GAP_QUERIES
except ImportError:
    ONTOLOGY_GAP_QUERIES = {}

LABEL_ORDER = [
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "no_consensus",
    "ambiguous",
    "source_or_ontology_issue",
]
LABEL_JA = {
    "aligned": "aligned（一致）",
    "broader_parent": "broader_parent（上位で正）",
    "partial_or_narrower": "partial_or_narrower（部分一致）",
    "wrong": "wrong（誤り）",
    "no_consensus": "no_consensus（不一致）",
    "ambiguous": "ambiguous（曖昧）",
    "source_or_ontology_issue": "source/ontology issue",
}
LABEL_COLOR = {
    "aligned": "#1a7f37",
    "broader_parent": "#2f6f9f",
    "partial_or_narrower": "#8a6d00",
    "wrong": "#c0392b",
    "no_consensus": "#7d7d7d",
    "ambiguous": "#7d7d7d",
    "source_or_ontology_issue": "#7d7d7d",
}

# Root-cause families for the residual `wrong` cases (substring match on query).
WRONG_FAMILIES: list[tuple[str, list[str]]] = [
    ("線維/核・器官の構造クラス不一致 (残存)", [
        "Nucleus of the stria medullaris", "Cochlea", "Spiral ganglion",
        "Vestibular apparatus", "Pretectothalamic lamina",
        "Ventricular system, unspecified", "Mesencephalic Trigeminal Nerve",
        "Anterior commissure, posterior limb",
    ]),
    ("番号/コード付き領域・オントロジー欠損 (A1〜A13, OP, PH…)", [
        "A1 catecholaminergic", "A4 catecholaminergic", "A5 catecholaminergic",
        "A11 dopamine", "A13 dopamine", "Area PH", "Opercular area OP",
        "Posterior opercular area POS", "Frontal association area",
    ]),
    ("接頭辞由来の別構造・オントロジー欠損 (pre-/retro-/juxta-)", [
        "Retroreuniens", "Juxtaparaventricular", "Retro-mammillary",
        "Cuneal cortex", "Precuneal cortex", "Supracalcarine cortex",
        "Frontoinsular area", "Pre-supplementary motor area",
    ]),
    ("方向/部分修飾の解決不能 (subdivision mismatch)", [
        "Central opercular cortex", "Lateral occipital cortex",
        "Lenticular nucleus", "Inferior colliculus, dorsal cortex",
        "Secondary visual area", "Lateral parietal cortex",
        "Orbital cortex", "Ventroposterior", "Supratemporal plane",
    ]),
    ("領域取り違え・その他", []),
]


def load_summary(tag: str) -> dict:
    return json.loads((RUNS / tag / "summary.json").read_text(encoding="utf-8"))


def load_records(tag: str) -> dict[tuple[str, str], dict]:
    rows: dict[tuple[str, str], dict] = {}
    path = RUNS / tag / "records.csv"
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rows[(row["dataset"], row["query"])] = row
    return rows


def diff_runs(base: dict, final: dict) -> tuple[list, list]:
    """Return (improved, regressed) as lists of (dataset, query, old, new)."""
    rank = {
        "aligned": 5, "broader_parent": 4, "partial_or_narrower": 3,
        "no_consensus": 2, "ambiguous": 2, "source_or_ontology_issue": 2,
        "wrong": 1,
    }
    improved, regressed = [], []
    for key, brow in base.items():
        frow = final.get(key)
        if not frow:
            continue
        ol, nl = brow["final_label"], frow["final_label"]
        if ol == nl:
            continue
        entry = (key[0], key[1], brow, frow)
        if rank.get(nl, 0) > rank.get(ol, 0):
            improved.append(entry)
        else:
            regressed.append(entry)
    improved.sort(key=lambda e: (e[0], e[1]))
    regressed.sort(key=lambda e: (e[0], e[1]))
    return improved, regressed


def esc(text: str) -> str:
    return html.escape(str(text or ""))


def label_badge(label: str) -> str:
    color = LABEL_COLOR.get(label, "#7d7d7d")
    return (f'<span class="badge" style="background:{color}">'
            f'{esc(label)}</span>')


def bar(counts: dict, total: int) -> str:
    segs = []
    for label in LABEL_ORDER:
        n = counts.get(label, 0)
        if not n:
            continue
        pct = 100 * n / total
        segs.append(
            f'<div class="seg" style="width:{pct:.3f}%;background:{LABEL_COLOR[label]}" '
            f'title="{esc(LABEL_JA[label])}: {n} ({pct:.1f}%)"></div>')
    return f'<div class="bar">{"".join(segs)}</div>'


def counts_table(base_counts: dict, final_counts: dict, base_total: int,
                 final_total: int, final_label: str = "最終") -> str:
    rows = []
    for label in LABEL_ORDER:
        b = base_counts.get(label, 0)
        f = final_counts.get(label, 0)
        if b == 0 and f == 0:
            continue
        delta = f - b
        if delta > 0:
            dcls, dtxt = "up", f"+{delta}"
        elif delta < 0:
            dcls, dtxt = "down", str(delta)
        else:
            dcls, dtxt = "flat", "±0"
        bp = 100 * b / base_total
        fp = 100 * f / final_total
        rows.append(
            f"<tr><td>{label_badge(label)}</td>"
            f"<td class='num'>{b} <span class='pct'>({bp:.1f}%)</span></td>"
            f"<td class='num'>{f} <span class='pct'>({fp:.1f}%)</span></td>"
            f"<td class='num {dcls}'>{dtxt}</td></tr>")
    return (
        "<table class='counts'><thead><tr>"
        f"<th>ラベル</th><th class='num'>baseline</th>"
        f"<th class='num'>{esc(final_label)}</th><th class='num'>差分</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")


def case_row(dataset: str, query: str, brow: dict, frow: dict) -> str:
    return (
        f"<tr><td class='ds'>{esc(dataset)}</td>"
        f"<td class='q'>{esc(query)}</td>"
        f"<td>{label_badge(brow['final_label'])}<div class='name'>{esc(brow['top_name'])}</div></td>"
        f"<td class='arrow'>&rarr;</td>"
        f"<td>{label_badge(frow['final_label'])}<div class='name'>{esc(frow['top_name'])}</div></td></tr>")


def wrong_section(final_rows: dict) -> str:
    wrongs = {k: v for k, v in final_rows.items() if v["final_label"] == "wrong"}
    assigned: set[tuple[str, str]] = set()
    blocks = []
    for title, needles in WRONG_FAMILIES[:-1]:
        members = []
        for key, row in sorted(wrongs.items()):
            if key in assigned:
                continue
            if any(n.lower() in row["query"].lower() for n in needles):
                members.append((key, row))
                assigned.add(key)
        if members:
            blocks.append((title, members))
    other = [(k, v) for k, v in sorted(wrongs.items()) if k not in assigned]
    if other:
        blocks.append((WRONG_FAMILIES[-1][0], other))

    parts = [f"<p class='muted'>残存 wrong: <b>{len(wrongs)}</b> 件（原因パターン別）。"
             "各行は クエリ → RCS top1（DeepSeek判定理由の抜粋）。</p>"]
    for title, members in blocks:
        rows = []
        for (dataset, query), row in members:
            reason = (row.get("pass3_reason") or row.get("pass1_reason") or "")[:150]
            rows.append(
                f"<tr><td class='ds'>{esc(dataset)}</td>"
                f"<td class='q'>{esc(query)}</td>"
                f"<td><div class='name'>{esc(row['top_name'])}</div>"
                f"<div class='reason'>{esc(reason)}</div></td></tr>")
        parts.append(
            f"<details class='fam'><summary>{esc(title)} "
            f"<span class='cnt'>{len(members)}</span></summary>"
            "<table class='cases'><tbody>" + "".join(rows) + "</tbody></table></details>")
    return "".join(parts)


def is_ontology_gap(query: str) -> bool:
    if query in ONTOLOGY_GAP_QUERIES:
        return True
    return any(
        query.startswith(k + " ") or query.startswith(k + "(") or query.startswith(k + ",")
        for k in ONTOLOGY_GAP_QUERIES
    )


def fixable_wrong_section(final_rows: dict) -> str:
    """List all residual wrongs that are *not* ontology gaps."""
    wrongs = sorted(
        ((k, v) for k, v in final_rows.items() if v["final_label"] == "wrong"),
        key=lambda item: (item[0][0], item[0][1]),
    )
    gaps = [(k, v) for k, v in wrongs if is_ontology_gap(k[1])]
    fixable = [(k, v) for k, v in wrongs if not is_ontology_gap(k[1])]
    rows = []
    for (dataset, query), row in fixable:
        reason = (row.get("pass3_reason") or row.get("pass1_reason") or "")[:180]
        note = ""
        # optional hint from gap map's sibling file is not needed; keep score/methods
        rows.append(
            f"<tr><td class='ds'>{esc(dataset)}</td>"
            f"<td class='q'>{esc(query)}</td>"
            f"<td><div class='name'>{esc(row['top_name'])}</div>"
            f"<div class='reason'>{esc(reason)}</div></td>"
            f"<td class='meta'>{esc(row.get('score', ''))}<br>{esc(row.get('methods', ''))}</td></tr>"
        )
    return (
        f"<p class='muted'>残存 wrong {len(wrongs)} 件のうち、オントロジー欠損 "
        f"<b>{len(gaps)}</b> 件を除いた <b>{len(fixable)}</b> 件を列挙。"
        "スコアリング・辞書・構造クラス等でまだ改善余地があるケース。</p>"
        "<table class='cases'><thead><tr>"
        "<th>set</th><th>query</th><th>top1 / 判定理由</th><th>score / methods</th>"
        "</tr></thead><tbody>"
        + ("".join(rows) if rows else
           "<tr><td colspan='4' class='muted'>該当なし</td></tr>")
        + "</tbody></table>"
    )


CHANGES = [
    ("語境界を尊重した包含スコア (_boundary_contains)",
     "部分文字列の包含ボーナスを語境界でのみ許可。「precuneiform / retroreuniens」等の"
     "接頭辞違いが「cuneiform / reuniens」を満点近くで誤マッチする過加点を抑制。"),
    ("エリアID整合ペナルティ＋コード付きブースト (_area_ids_compatible)",
     "番号の食い違いを減点（×0.40）。アルファ付きコード（v3a, a8…）の一致時のみ"
     "加点し、素の数字（layers 2-3）への誤ブーストを回避。"),
    ("方向修飾の条件付き有効化 (_effective_modifiers)",
     "方向語は候補プールで解決可能な場合のみスコアに反映。"),
    ("親昇格ガード (_promote_common_parents)",
     "※ Round8 で削除。領域アンカー／構造クラス／辞書に置換。"),
    ("弱一致キャップ (weak_only_match ≤0.38)",
     "一般語のみの一致の上限を引き下げ。"),
    ("汎用語のみエイリアスの除去 (_drop_generic_only_aliases)",
     "括弧展開の「(area)→area」等を索引から除外。"),
    ("【Round6】構造クラス・ヘッド判定 (_structure_class_conflict)",
     "クエリと候補の構造クラス（gray/white/nerve/ventricle/sulcus/organ）を比較。"
     "「CLASS of …」をヘッド優先、それ以外は末尾クラス語を採用。"
     "「lateral olfactory tract → nucleus of LOT」を抑制し olfactory tract を上位へ。"),
    ("【Round6】接頭辞不一致ペナルティ (_distinguishing_affix_mismatch)",
     "pre-/retro-/juxta-/supra- 等がクエリにあり候補が裸の語幹だけのとき減点。"
     "「Precuneiform → cuneiform」を「precuneiform area」へ改善。"),
    ("【Round6】辞書・略語の追加 (alias / abbrev rules)",
     "4th ventricle、PPN、CM-Pf、PVN hypothalamic、V3A、dentate/interpositus、"
     "temporal horn、trochlear nerve、suprageniculate、laterodorsal tegmentum 等を追加。"),
    ("【Round6】括弧内容の保持バリアント",
     "「Anterior nucleus (thalamus)」→「anterior nucleus thalamus」も検索し、"
     "anterior nuclear complex へ誘導。"),
    ("【Round8】親昇格の削除 + 弱誤マッチ抑制",
     "_promote_common_parents を撤去。代わりに領域アンカー必須（orbital/occipital 等）、"
     "area↔claustrum の構造クラス、複数形 nuclei 減点、FST/STS/orbital 等の辞書で、"
     "昇格オフ時に増えた wrong を回収しつつ細語ヒット（GPi/OFC 等）を維持。"),
]


def render(baseline_tag: str, final_tag: str) -> str:
    bsum = load_summary(baseline_tag)
    fsum = load_summary(final_tag)
    brows = load_records(baseline_tag)
    frows = load_records(final_tag)
    improved, regressed = diff_runs(brows, frows)

    bov = bsum["overall"]["label_counts"]
    fov = fsum["overall"]["label_counts"]
    btot = bsum["total_records"]
    ftot = fsum["total_records"]

    wrong_delta = fov.get("wrong", 0) - bov.get("wrong", 0)
    good_base = bov.get("aligned", 0) + bov.get("broader_parent", 0)
    good_final = fov.get("aligned", 0) + fov.get("broader_parent", 0)
    final_label = f"最終 ({final_tag})"

    changes_html = "".join(
        f"<li><b>{esc(t)}</b><br><span class='muted'>{esc(d)}</span></li>"
        for t, d in CHANGES)

    improved_rows = "".join(case_row(d, q, b, f) for d, q, b, f in improved)
    regressed_rows = "".join(case_row(d, q, b, f) for d, q, b, f in regressed)
    fixable_wrong_html = fixable_wrong_section(frows)

    def ds_block(name: str) -> str:
        bd = bsum["datasets"][name]["label_counts"]
        fd = fsum["datasets"][name]["label_counts"]
        bt = bsum["datasets"][name]["records"]
        ft = fsum["datasets"][name]["records"]
        return (f"<h3>{esc(name)} <span class='muted'>({ft} queries)</span></h3>"
                + counts_table(bd, fd, bt, ft, final_label))

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RCS 自律改善レポート (baseline → {esc(final_tag)})</title>
<style>
:root {{ --fg:#1c1c1e; --muted:#6b6b70; --line:#e3e3e8; --bg:#fbfbfd; }}
* {{ box-sizing:border-box; }}
body {{ font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue","Noto Sans JP",sans-serif;
  color:var(--fg); background:var(--bg); margin:0; line-height:1.6; }}
.wrap {{ max-width:980px; margin:0 auto; padding:32px 24px 80px; }}
h1 {{ font-size:26px; margin:0 0 4px; }}
h2 {{ font-size:20px; margin:40px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--line); }}
h3 {{ font-size:16px; margin:22px 0 8px; }}
.muted {{ color:var(--muted); }}
.sub {{ color:var(--muted); margin:0 0 24px; font-size:14px; }}
.cards {{ display:flex; gap:14px; flex-wrap:wrap; margin:20px 0; }}
.card {{ flex:1 1 150px; background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:16px 18px; }}
.card .k {{ font-size:13px; color:var(--muted); }}
.card .v {{ font-size:28px; font-weight:700; margin-top:4px; }}
.card .d {{ font-size:14px; font-weight:600; margin-top:2px; }}
.up {{ color:#1a7f37; }} .down {{ color:#c0392b; }} .flat {{ color:var(--muted); }}
.bar {{ display:flex; height:24px; border-radius:6px; overflow:hidden; border:1px solid var(--line); margin:6px 0 4px; }}
.seg {{ height:100%; }}
.legend {{ display:flex; flex-wrap:wrap; gap:10px 18px; font-size:12px; margin:8px 0 4px; }}
.legend span::before {{ content:""; display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:5px; vertical-align:-1px; background:var(--c); }}
table {{ width:100%; border-collapse:collapse; font-size:14px; background:#fff; }}
.counts td, .counts th {{ padding:7px 10px; border-bottom:1px solid var(--line); text-align:left; }}
.counts .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.pct {{ color:var(--muted); font-size:12px; }}
.badge {{ display:inline-block; color:#fff; font-size:12px; font-weight:600;
  padding:2px 8px; border-radius:20px; white-space:nowrap; }}
.cases td, .counts td {{ vertical-align:top; }}
.cases {{ border:1px solid var(--line); border-radius:8px; margin:8px 0 4px; }}
.cases td {{ padding:8px 10px; border-bottom:1px solid var(--line); }}
.cases tr:last-child td {{ border-bottom:none; }}
.ds {{ color:var(--muted); font-size:12px; width:66px; }}
.q {{ font-weight:600; width:230px; }}
.name {{ color:var(--muted); font-size:12.5px; margin-top:3px; }}
.reason {{ color:#8a5a00; font-size:12px; margin-top:4px; }}
.arrow {{ color:var(--muted); text-align:center; width:28px; }}
details.fam {{ background:#fff; border:1px solid var(--line); border-radius:8px;
  margin:8px 0; padding:4px 12px; }}
details.fam > summary {{ cursor:pointer; font-weight:600; padding:8px 2px; }}
.cnt {{ background:#c0392b; color:#fff; border-radius:20px; font-size:12px; padding:1px 8px; margin-left:6px; }}
ul.changes {{ list-style:none; padding:0; }}
ul.changes li {{ background:#fff; border:1px solid var(--line); border-left:4px solid #2f6f9f;
  border-radius:8px; padding:12px 14px; margin:8px 0; }}
.meta {{ color:var(--muted); font-size:12px; width:120px; }}
.note {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:14px 16px; font-size:14px; }}
</style></head>
<body><div class="wrap">
<h1>RCS アルゴリズム 自律改善レポート</h1>
<p class="sub">テストデータ: rcs_corpus_no_direction.csv + rcs_species.csv（計 {ftot} クエリ）・
評価: DeepSeek 3-pass 整合性判定・生成: {now}</p>

<div class="cards">
  <div class="card"><div class="k">wrong（誤り）</div>
    <div class="v">{bov.get('wrong',0)} → {fov.get('wrong',0)}</div>
    <div class="d down">{wrong_delta:+d} 件</div></div>
  <div class="card"><div class="k">aligned</div>
    <div class="v">{bov.get('aligned',0)} → {fov.get('aligned',0)}</div>
    <div class="d up">{fov.get('aligned',0)-bov.get('aligned',0):+d} 件</div></div>
  <div class="card"><div class="k">aligned + broader_parent（許容可）</div>
    <div class="v">{good_base} → {good_final}</div>
    <div class="d up">{good_final-good_base:+d} 件</div></div>
  <div class="card"><div class="k">改善 / 回帰</div>
    <div class="v">{len(improved)} / {len(regressed)}</div>
    <div class="d">baseline比</div></div>
</div>

<h2>1. ラベル分布の変化</h2>
<div class="legend">
{"".join(f'<span style="--c:{LABEL_COLOR[l]}">{esc(LABEL_JA[l])}</span>' for l in LABEL_ORDER if bov.get(l) or fov.get(l))}
</div>
<div class="muted" style="font-size:12px;margin-top:10px">baseline</div>
{bar(bov, btot)}
<div class="muted" style="font-size:12px;margin-top:6px">{esc(final_label)}</div>
{bar(fov, ftot)}
{counts_table(bov, fov, btot, ftot, final_label)}

<h2>2. データセット別内訳</h2>
{ds_block('corpus')}
{ds_block('species')}

<h2>3. 改善したケース <span class="muted">({len(improved)} 件)</span></h2>
<table class="cases"><tbody>{improved_rows}</tbody></table>

<h2>4. 回帰したケース <span class="muted">({len(regressed)} 件)</span></h2>
<p class="note">改善 {len(improved)} 件に対し回帰 {len(regressed)} 件。
多くは broader_parent ↔ partial の入れ替わりや、番号付き領域の近傍誤マッチ。
ネットでは大幅に改善。</p>
<table class="cases"><tbody>{regressed_rows}</tbody></table>

<h2>5. 実施したアルゴリズム改善</h2>
<ul class="changes">{changes_html}</ul>

<h2>6. 残存 wrong の原因分析</h2>
{wrong_section(frows)}

<h2>7. 所見・次アクション候補</h2>
<div class="note">
<p><b>成果:</b> wrong を {bov.get('wrong',0)} → {fov.get('wrong',0)} 件（{wrong_delta:+d}）に削減。
Round6 では構造クラス・接頭辞ペナルティと辞書追加で、
tract↔nucleus / nerve↔ventricle / PPN / V3A / PVN 等を大きく改善。</p>
<p><b>残課題:</b></p>
<ul>
<li><b>オントロジー欠損</b>（A1〜A13 cell group、juxtaparaventricular、retroreuniens、
pre-SMA、spiral ganglion、cochlea 等）: HOMBA に対応語が無い。辞書では吸収不能。</li>
<li><b>番号付き細区分の残余</b>（OP1/OP4、area PH）: コード一致必須化の強化と
HOMBA 側の別名整備。</li>
<li><b>構造クラスの境界例</b>（nucleus of stria medullaris）: 正しいクラスの候補自体が
オントロジーに無い場合のフォールバック設計。</li>
</ul>
</div>

<h2>8. 残存 wrong（オントロジー欠損以外）</h2>
{fixable_wrong_html}

</div></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default="baseline_nodir")
    ap.add_argument("--final", default="round7_nodir")
    ap.add_argument(
        "--out",
        default=str(HERE.parent / "top1_consistency_review" / "auto_improve_report_nodir.html"))
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(args.baseline, args.final), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
