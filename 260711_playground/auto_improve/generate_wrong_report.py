#!/usr/bin/env python3
"""HTML report of round6 residual ``wrong`` cases, split by ontology gap vs fixable."""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RECORDS = HERE / "runs" / "round6" / "records.csv"
OUT = HERE.parent / "top1_consistency_review" / "round6_wrong_report.html"

# Queries whose intended structure is absent (or not representable) in HOMBA,
# so RCS cannot absorb them by scoring/dictionary alone.
ONTOLOGY_GAP_QUERIES: dict[str, str] = {
    "A1 catecholaminergic cell group": "HOMBAに A1 cell group が無い（A2/A7/A8 のみ）",
    "A4 catecholaminergic cell group": "HOMBAに A4 cell group が無い",
    "A5 catecholaminergic cell group": "HOMBAに A5 cell group が無い（皮質 area 5 と衝突）",
    "A11 dopamine cell group": "HOMBAに A11 dopamine cell group が無い",
    "A13 dopamine cell group": "HOMBAに A13 dopamine cell group が無い",
    "Area PH": "HOMBAに Area PH が無い（parahippocampal gyrus 等の親のみ）",
    "Opercular area OP1": "HOMBAに OP1（頭頂弁蓋S2）が無い",
    "Opercular area OP2-3": "HOMBAに OP2/OP3 が無い",
    "Opercular area OP4": "HOMBAに OP4 が無い",
    "Posterior opercular area POS2": "HOMBAに POS2 が無い",
    "Pre-supplementary motor area": "HOMBAに pre-SMA が無い（SMA=medial area 6 のみ）",
    "Pre-supplementary motor area (inferior)": "HOMBAに pre-SMA が無い",
    "Pre-supplementary motor area (superior)": "HOMBAに pre-SMA が無い",
    "Juxtaparaventricular nucleus": "HOMBAに juxtaparaventricular nucleus が無い",
    "Retroreuniens thalamic nucleus": "HOMBAに retroreuniens が無い",
    "Accessory trigeminal nucleus": "HOMBAに accessory trigeminal nucleus が無い",
    "Cochlea": "蝸牛は末梢器官で脳オントロジー外",
    "Spiral ganglion": "らせん神経節は末梢（内耳）で脳オントロジー外",
    "Vestibular apparatus": "前庭器は末梢器官で脳オントロジー外",
    "Nucleus of the stria medullaris": "stria medullaris の核エントリが無い（線維のみ）",
    "Pretectothalamic lamina": "HOMBAに pretectothalamic lamina が無い",
    "Frontoinsular area": "HOMBAに frontoinsular area が無い",
    "Peduncular lateral hypothalamic nucleus": "HOMBAに peduncular LHA nucleus が無い（近傍の magnocellular LHA のみ）",
}

# Optional note for fixable cases (nearest HOMBA / likely fix type).
FIXABLE_HINTS: dict[str, str] = {
    "Cuneal cortex": "近傍: cuneus (gyrus) — エイリアスで吸収可",
    "Precuneal cortex": "近傍: precuneaus (gyrus) — エイリアスで吸収可",
    "Supracalcarine cortex": "近傍: calcarine sulcus / visual cortex — 親フォールバック強化",
    "Intracalcarine cortex (inferior)": "calcarine 関連へ誘導（inferior colliculus 誤誘引の抑制）",
    "Intracalcarine cortex, inferior": "同上",
    "Intracalcarine cortex, superior": "同上",
    "Retro-mammillary nucleus": "近傍: retromammillary area — エイリアスで吸収可",
    "Mircrocellular Tegmentum": "誤綴り; 正解: microcellular tegmental nucleus",
    "Ventroposterior Inferior Thalamus": "近傍: ventral posterior inferior nucleus",
    "Ventroposterior inferior thalamic nucleus": "近傍: ventral posterior inferior nucleus",
    "Ventroposterior Medial and Lateral Thalamus": "近傍: VPL+VPM / VP complex",
    "Ventroposterior medial and lateral thalamic nuclei": "近傍: VPL+VPM",
    "Ventral periolivary nuclei": "近傍: periolivary nuclei（ventral 細区分の対応）",
    "Inferior colliculus, dorsal cortex": "エイリアス衝突: dorsal cortex vs dorsal central nucleus",
    "Lenticular nucleus (pallidum)": "括弧の pallidum を優先（現状 putamen エイリアスが勝つ）",
    "Anterior Thalamus": "anterior nuclear complex が top2 — 親昇格の押し上げを抑制",
    "Central Gray Nucleus": "通常は PAG; 辞書 or 略語で誘導",
}


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def load_wrong() -> list[dict]:
    rows = []
    with RECORDS.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("final_label") != "wrong":
                continue
            top3 = []
            try:
                top3 = json.loads(r.get("top3") or "[]")
            except json.JSONDecodeError:
                pass
            rows.append({**r, "_top3": top3})
    rows.sort(key=lambda x: (x["dataset"], x["query"]))
    return rows


def classify(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    gaps, other = [], []
    for r in rows:
        q = r["query"]
        # strip directional variants of pre-SMA already in map; also match prefix
        gap_reason = ONTOLOGY_GAP_QUERIES.get(q)
        if gap_reason is None:
            for key, reason in ONTOLOGY_GAP_QUERIES.items():
                if q == key or q.startswith(key + " ") or q.startswith(key + "(") or q.startswith(key + ","):
                    gap_reason = reason
                    break
        if gap_reason:
            r["_bucket_note"] = gap_reason
            gaps.append(r)
        else:
            r["_bucket_note"] = FIXABLE_HINTS.get(q, "スコアリング／辞書／構造クラスで改善余地あり")
            other.append(r)
    return gaps, other


def case_table(rows: list[dict]) -> str:
    body = []
    for r in rows:
        top3 = " | ".join(
            f"{esc(c.get('name', ''))} ({float(c.get('score') or 0):.2f})"
            for c in r.get("_top3") or []
        )
        reason = (r.get("pass3_reason") or r.get("pass1_reason") or "")[:180]
        body.append(
            "<tr>"
            f"<td class='ds'>{esc(r['dataset'])}</td>"
            f"<td class='q'>{esc(r['query'])}</td>"
            f"<td><div class='name'>{esc(r['top_name'])}</div>"
            f"<div class='meta'>score={esc(r.get('score',''))} · {esc(r.get('methods',''))}</div>"
            f"<div class='top3'>{top3}</div></td>"
            f"<td class='note'>{esc(r.get('_bucket_note',''))}</td>"
            f"<td class='reason'>{esc(reason)}</td>"
            "</tr>"
        )
    return (
        "<table class='cases'><thead><tr>"
        "<th>set</th><th>query</th><th>top1 / top3</th><th>分類メモ</th><th>判定理由</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def main() -> None:
    rows = load_wrong()
    gaps, other = classify(rows)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html_doc = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Round6 残存 wrong レポート</title>
<style>
:root {{ --fg:#1c1c1e; --muted:#6b6b70; --line:#e3e3e8; --bg:#fbfbfd; --gap:#8a4b08; --fix:#1a5f8a; }}
* {{ box-sizing:border-box; }}
body {{ font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue","Noto Sans JP",sans-serif;
  color:var(--fg); background:var(--bg); margin:0; line-height:1.55; }}
.wrap {{ max-width:1100px; margin:0 auto; padding:28px 22px 72px; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
h2 {{ font-size:18px; margin:36px 0 10px; padding-bottom:6px; border-bottom:2px solid var(--line); }}
.sub {{ color:var(--muted); font-size:14px; margin:0 0 20px; }}
.cards {{ display:flex; gap:12px; flex-wrap:wrap; margin:16px 0 8px; }}
.card {{ flex:1 1 160px; background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.card .k {{ font-size:12px; color:var(--muted); }}
.card .v {{ font-size:28px; font-weight:700; margin-top:2px; }}
.card.gap {{ border-left:4px solid var(--gap); }}
.card.fix {{ border-left:4px solid var(--fix); }}
.note {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px; font-size:14px; margin:12px 0; }}
table.cases {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line);
  border-radius:8px; overflow:hidden; font-size:13px; }}
.cases th, .cases td {{ padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
.cases th {{ background:#f3f3f6; font-size:12px; color:var(--muted); }}
.ds {{ color:var(--muted); width:64px; font-size:12px; }}
.q {{ font-weight:600; width:200px; }}
.name {{ font-weight:600; }}
.meta, .top3 {{ color:var(--muted); font-size:11.5px; margin-top:3px; }}
td.note {{ color:var(--gap); width:200px; font-size:12.5px; }}
section.fix td.note {{ color:var(--fix); }}
.reason {{ color:#6a5a00; font-size:12px; width:240px; }}
.badge {{ display:inline-block; color:#fff; font-size:12px; font-weight:600; padding:2px 8px; border-radius:20px; }}
.badge.gap {{ background:var(--gap); }}
.badge.fix {{ background:var(--fix); }}
</style></head><body><div class="wrap">
<h1>Round6 残存 wrong レポート</h1>
<p class="sub">ソース: runs/round6/records.csv · 計 {len(rows)} 件 · 生成: {now}</p>

<div class="cards">
  <div class="card"><div class="k">wrong 合計</div><div class="v">{len(rows)}</div></div>
  <div class="card gap"><div class="k">オントロジー欠損（吸収不可）</div><div class="v">{len(gaps)}</div></div>
  <div class="card fix"><div class="k">それ以外（改善余地あり）</div><div class="v">{len(other)}</div></div>
</div>

<div class="note">
<strong>オントロジー欠損</strong> = 意図する構造の対応語が HOMBA に無く、辞書追加やスコア調整だけでは
aligned / 妥当な broader_parent に誘導できないケース。
<strong>それ以外</strong> = 近傍語が HOMBA に存在する、または誤綴り・修飾の取り違えなど、
アルゴリズム／辞書側でまだ手が打てるケース。
</div>

<h2><span class="badge gap">オントロジー欠損</span> {len(gaps)} 件</h2>
{case_table(gaps)}

<h2><span class="badge fix">それ以外（改善余地あり）</span> {len(other)} 件</h2>
<section class="fix">
{case_table(other)}
</section>

</div></body></html>"""
    OUT.write_text(html_doc, encoding="utf-8")
    print(f"wrong={len(rows)} ontology_gap={len(gaps)} other={len(other)}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
