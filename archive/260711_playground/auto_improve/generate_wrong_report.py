#!/usr/bin/env python3
"""HTML report of round6 residual ``wrong`` cases, split by ontology gap vs fixable."""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RECORDS = HERE / "runs" / "round6" / "records.csv"
OUT = HERE.parent / "top1_consistency_review" / "round6_wrong_report.html"

# Queries whose intended structure is absent (or not representable) in HOMBA,
# so RCS cannot absorb them by scoring/dictionary alone.
ONTOLOGY_GAP_QUERIES: dict[str, str] = {
    "A1 catecholaminergic cell group": "HOMBA縺ｫ A1 cell group 縺檎┌縺・ｼ・2/A7/A8 縺ｮ縺ｿ・・,
    "A4 catecholaminergic cell group": "HOMBA縺ｫ A4 cell group 縺檎┌縺・,
    "A5 catecholaminergic cell group": "HOMBA縺ｫ A5 cell group 縺檎┌縺・ｼ育坩雉ｪ area 5 縺ｨ陦晉ｪ・ｼ・,
    "A11 dopamine cell group": "HOMBA縺ｫ A11 dopamine cell group 縺檎┌縺・,
    "A13 dopamine cell group": "HOMBA縺ｫ A13 dopamine cell group 縺檎┌縺・,
    "Area PH": "HOMBA縺ｫ Area PH 縺檎┌縺・ｼ・arahippocampal gyrus 遲峨・隕ｪ縺ｮ縺ｿ・・,
    "Opercular area OP1": "HOMBA縺ｫ OP1・磯ｭ鬆ょｼ∬搭S2・峨′辟｡縺・,
    "Opercular area OP2-3": "HOMBA縺ｫ OP2/OP3 縺檎┌縺・,
    "Opercular area OP4": "HOMBA縺ｫ OP4 縺檎┌縺・,
    "Posterior opercular area POS2": "HOMBA縺ｫ POS2 縺檎┌縺・,
    "Pre-supplementary motor area": "HOMBA縺ｫ pre-SMA 縺檎┌縺・ｼ・MA=medial area 6 縺ｮ縺ｿ・・,
    "Pre-supplementary motor area (inferior)": "HOMBA縺ｫ pre-SMA 縺檎┌縺・,
    "Pre-supplementary motor area (superior)": "HOMBA縺ｫ pre-SMA 縺檎┌縺・,
    "Juxtaparaventricular nucleus": "HOMBA縺ｫ juxtaparaventricular nucleus 縺檎┌縺・,
    "Retroreuniens thalamic nucleus": "HOMBA縺ｫ retroreuniens 縺檎┌縺・,
    "Accessory trigeminal nucleus": "HOMBA縺ｫ accessory trigeminal nucleus 縺檎┌縺・,
    "Cochlea": "陜ｸ迚帙・譛ｫ譴｢蝎ｨ螳倥〒閼ｳ繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ螟・,
    "Spiral ganglion": "繧峨○繧鍋･樒ｵ檎ｯ縺ｯ譛ｫ譴｢・亥・閠ｳ・峨〒閼ｳ繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ螟・,
    "Vestibular apparatus": "蜑榊ｺｭ蝎ｨ縺ｯ譛ｫ譴｢蝎ｨ螳倥〒閼ｳ繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ螟・,
    "Nucleus of the stria medullaris": "stria medullaris 縺ｮ譬ｸ繧ｨ繝ｳ繝医Μ縺檎┌縺・ｼ育ｷ夂ｶｭ縺ｮ縺ｿ・・,
    "Pretectothalamic lamina": "HOMBA縺ｫ pretectothalamic lamina 縺檎┌縺・,
    "Frontoinsular area": "HOMBA縺ｫ frontoinsular area 縺檎┌縺・,
    "Peduncular lateral hypothalamic nucleus": "HOMBA縺ｫ peduncular LHA nucleus 縺檎┌縺・ｼ郁ｿ大ｍ縺ｮ magnocellular LHA 縺ｮ縺ｿ・・,
}

# Optional note for fixable cases (nearest HOMBA / likely fix type).
FIXABLE_HINTS: dict[str, str] = {
    "Cuneal cortex": "霑大ｍ: cuneus (gyrus) 窶・繧ｨ繧､繝ｪ繧｢繧ｹ縺ｧ蜷ｸ蜿主庄",
    "Precuneal cortex": "霑大ｍ: precuneaus (gyrus) 窶・繧ｨ繧､繝ｪ繧｢繧ｹ縺ｧ蜷ｸ蜿主庄",
    "Supracalcarine cortex": "霑大ｍ: calcarine sulcus / visual cortex 窶・隕ｪ繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ蠑ｷ蛹・,
    "Intracalcarine cortex (inferior)": "calcarine 髢｢騾｣縺ｸ隱伜ｰ趣ｼ・nferior colliculus 隱､隱伜ｼ輔・謚大宛・・,
    "Intracalcarine cortex, inferior": "蜷御ｸ・,
    "Intracalcarine cortex, superior": "蜷御ｸ・,
    "Retro-mammillary nucleus": "霑大ｍ: retromammillary area 窶・繧ｨ繧､繝ｪ繧｢繧ｹ縺ｧ蜷ｸ蜿主庄",
    "Mircrocellular Tegmentum": "隱､邯ｴ繧・ 豁｣隗｣: microcellular tegmental nucleus",
    "Ventroposterior Inferior Thalamus": "霑大ｍ: ventral posterior inferior nucleus",
    "Ventroposterior inferior thalamic nucleus": "霑大ｍ: ventral posterior inferior nucleus",
    "Ventroposterior Medial and Lateral Thalamus": "霑大ｍ: VPL+VPM / VP complex",
    "Ventroposterior medial and lateral thalamic nuclei": "霑大ｍ: VPL+VPM",
    "Ventral periolivary nuclei": "霑大ｍ: periolivary nuclei・・entral 邏ｰ蛹ｺ蛻・・蟇ｾ蠢懶ｼ・,
    "Inferior colliculus, dorsal cortex": "繧ｨ繧､繝ｪ繧｢繧ｹ陦晉ｪ・ dorsal cortex vs dorsal central nucleus",
    "Lenticular nucleus (pallidum)": "諡ｬ蠑ｧ縺ｮ pallidum 繧貞━蜈茨ｼ育樟迥ｶ putamen 繧ｨ繧､繝ｪ繧｢繧ｹ縺悟享縺､・・,
    "Anterior Thalamus": "anterior nuclear complex 縺・top2 窶・隕ｪ譏・ｼ縺ｮ謚ｼ縺嶺ｸ翫￡繧呈椛蛻ｶ",
    "Central Gray Nucleus": "騾壼ｸｸ縺ｯ PAG; 霎樊嶌 or 逡･隱槭〒隱伜ｰ・,
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
            r["_bucket_note"] = FIXABLE_HINTS.get(q, "繧ｹ繧ｳ繧｢繝ｪ繝ｳ繧ｰ・剰ｾ樊嶌・乗ｧ矩繧ｯ繝ｩ繧ｹ縺ｧ謾ｹ蝟・ｽ吝慍縺ゅｊ")
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
            f"<div class='meta'>score={esc(r.get('score',''))} ﾂｷ {esc(r.get('methods',''))}</div>"
            f"<div class='top3'>{top3}</div></td>"
            f"<td class='note'>{esc(r.get('_bucket_note',''))}</td>"
            f"<td class='reason'>{esc(reason)}</td>"
            "</tr>"
        )
    return (
        "<table class='cases'><thead><tr>"
        "<th>set</th><th>query</th><th>top1 / top3</th><th>蛻・｡槭Γ繝｢</th><th>蛻､螳夂炊逕ｱ</th>"
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
<title>Round6 谿句ｭ・wrong 繝ｬ繝昴・繝・/title>
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
<h1>Round6 谿句ｭ・wrong 繝ｬ繝昴・繝・/h1>
<p class="sub">繧ｽ繝ｼ繧ｹ: runs/round6/records.csv ﾂｷ 險・{len(rows)} 莉ｶ ﾂｷ 逕滓・: {now}</p>

<div class="cards">
  <div class="card"><div class="k">wrong 蜷郁ｨ・/div><div class="v">{len(rows)}</div></div>
  <div class="card gap"><div class="k">繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ谺謳搾ｼ亥精蜿惹ｸ榊庄・・/div><div class="v">{len(gaps)}</div></div>
  <div class="card fix"><div class="k">縺昴ｌ莉･螟厄ｼ域隼蝟・ｽ吝慍縺ゅｊ・・/div><div class="v">{len(other)}</div></div>
</div>

<div class="note">
<strong>繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ谺謳・/strong> = 諢丞峙縺吶ｋ讒矩縺ｮ蟇ｾ蠢懆ｪ槭′ HOMBA 縺ｫ辟｡縺上∬ｾ樊嶌霑ｽ蜉繧・せ繧ｳ繧｢隱ｿ謨ｴ縺縺代〒縺ｯ
aligned / 螯･蠖薙↑ broader_parent 縺ｫ隱伜ｰ弱〒縺阪↑縺・こ繝ｼ繧ｹ縲・<strong>縺昴ｌ莉･螟・/strong> = 霑大ｍ隱槭′ HOMBA 縺ｫ蟄伜惠縺吶ｋ縲√∪縺溘・隱､邯ｴ繧翫・菫ｮ鬟ｾ縺ｮ蜿悶ｊ驕輔∴縺ｪ縺ｩ縲・繧｢繝ｫ繧ｴ繝ｪ繧ｺ繝・剰ｾ樊嶌蛛ｴ縺ｧ縺ｾ縺謇九′謇薙※繧九こ繝ｼ繧ｹ縲・</div>

<h2><span class="badge gap">繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ谺謳・/span> {len(gaps)} 莉ｶ</h2>
{case_table(gaps)}

<h2><span class="badge fix">縺昴ｌ莉･螟厄ｼ域隼蝟・ｽ吝慍縺ゅｊ・・/span> {len(other)} 莉ｶ</h2>
<section class="fix">
{case_table(other)}
</section>

</div></body></html>"""
    OUT.write_text(html_doc, encoding="utf-8")
    print(f"wrong={len(rows)} ontology_gap={len(gaps)} other={len(other)}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
