#!/usr/bin/env python3
"""Analyze round7_nodir broader_parent cases: ontology gap vs missed child.

Classification
--------------
* no_finer_ontology 窶・HOMBA has no child/near-child that better matches the query
  (parent hit is the best available absorption).
* finer_exists 窶・a more specific HOMBA term exists (usually a descendant of the
  returned parent, or a high-similarity more-specific sibling) but RCS ranked
  the parent first.

Outputs an HTML report under top1_consistency_review/.
"""
from __future__ import annotations

import csv
import html
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    RosettaCandidateGenerator,
    _structure_class_conflict,
    normalize_text,
    string_similarity,
    tokenize,
)

RECORDS = HERE / "runs" / "round7_nodir" / "records.csv"
OUT = HERE.parent / "top1_consistency_review" / "broader_parent_analysis.html"

# Minimum similarity for a descendant to count as a usable finer term.
CHILD_SIM_THRESH = 0.68
# Non-descendant "near" terms need a much stronger match.
NEAR_SIM_THRESH = 0.85
MARGIN = 0.03

# Query tokens that mean "exclude this part" 窶・matching that part is NOT finer.
EXCLUDE_MARKERS = ("excluding", "except", "without", "minus")


def esc(s: str) -> str:
    return html.escape(str(s or ""))


def build_children(gen: RosettaCandidateGenerator) -> dict[str, list[int]]:
    children: dict[str, list[int]] = defaultdict(list)
    for idx, term in enumerate(gen.terms):
        if term.parent_id:
            children[term.parent_id].append(idx)
    return children


def descendants(root_id: str, children: dict[str, list[int]], gen, limit: int = 400) -> list[int]:
    out: list[int] = []
    stack = list(children.get(root_id, []))
    seen = set(stack)
    while stack and len(out) < limit:
        idx = stack.pop()
        out.append(idx)
        for cidx in children.get(gen.terms[idx].homba_id, []):
            if cidx not in seen:
                seen.add(cidx)
                stack.append(cidx)
    return out


def best_alias_sim(query: str, term) -> tuple[float, str]:
    best = 0.0
    best_alias = term.name
    for alias in term.aliases:
        s = string_similarity(query, alias)
        if s > best:
            best = s
            best_alias = alias
    return best, best_alias


def query_content_tokens(query: str, gen: RosettaCandidateGenerator) -> set[str]:
    return set(tokenize(query, config=gen.config)) - gen._noncontent_tokens


def extra_content(query_toks: set[str], term, gen: RosettaCandidateGenerator) -> set[str]:
    """Query content tokens not covered by any alias of *term*."""
    covered: set[str] = set()
    for alias in term.aliases:
        covered |= set(tokenize(alias, config=gen.config))
    # stem-ish: if query token is prefix of an alias token or vice versa, count covered
    uncovered = set()
    for qt in query_toks:
        if qt in covered:
            continue
        if any(qt.startswith(ct) or ct.startswith(qt) for ct in covered if min(len(qt), len(ct)) >= 4):
            continue
        uncovered.add(qt)
    return uncovered


def excluded_tokens(query: str, gen: RosettaCandidateGenerator) -> set[str]:
    """Tokens named after 'excluding/except/...' should not be treated as the target."""
    qn = normalize_text(query)
    out: set[str] = set()
    for marker in EXCLUDE_MARKERS:
        if marker not in qn:
            continue
        after = qn.split(marker, 1)[1]
        out |= set(tokenize(after, config=gen.config)) - gen._noncontent_tokens
    return out


def shares_anatomical_core(query: str, term, gen: RosettaCandidateGenerator) -> bool:
    """Candidate must share a substantial content token with the query head."""
    q_toks = query_content_tokens(query, gen)
    if not q_toks:
        return False
    # Drop short positional / qualifier tokens for core check
    drop = {
        "area", "part", "division", "region", "layer", "zone", "portion",
        "anterior", "posterior", "dorsal", "ventral", "medial", "lateral",
        "rostral", "caudal", "superior", "inferior", "deep", "superficial",
        "internal", "external", "granular", "molecular", "principal",
        "magnocellular", "parvicellular", "oralis", "interpolar", "caudal",
    }
    core = {t for t in q_toks if t not in drop and len(t) >= 4}
    if not core:
        core = {t for t in q_toks if len(t) >= 4} or q_toks
    for alias in term.aliases:
        a_toks = set(tokenize(alias, config=gen.config))
        if core & a_toks:
            return True
        # soft prefix match for long stems (e.g. ansiform/ansiform)
        for ct in core:
            if any(len(ct) >= 5 and (ct in at or at in ct) for at in a_toks if len(at) >= 5):
                return True
    return False


def classify_case(row: dict, gen: RosettaCandidateGenerator, children: dict) -> dict:
    query = row["query"]
    parent_id = row["top_homba_id"]
    parent_idx = gen.term_index_by_id.get(parent_id)
    if parent_idx is None:
        return {
            "bucket": "no_finer_ontology",
            "reason": "top1 id not in HOMBA index",
            "candidate": "",
            "candidate_id": "",
            "parent_sim": 0.0,
            "child_sim": 0.0,
        }

    parent = gen.terms[parent_idx]
    parent_sim, _ = best_alias_sim(query, parent)
    q_toks = query_content_tokens(query, gen)
    parent_uncovered = extra_content(q_toks, parent, gen)
    excluded = excluded_tokens(query, gen)
    q_tok_list = tokenize(query, config=gen.config)

    # Prefer descendants of the returned parent.
    desc_indexes = set(descendants(parent_id, children, gen))

    # Also allow non-descendants only if they are near-exact and structure-compatible
    # (covers cases where hierarchy parent 竕 semantic parent, e.g. GPi under GP).
    near_indexes: set[int] = set()
    for idx, term in enumerate(gen.terms):
        if idx == parent_idx or idx in desc_indexes:
            continue
        if not shares_anatomical_core(query, term, gen):
            continue
        if _structure_class_conflict(q_tok_list, tokenize(term.name, config=gen.config)):
            continue
        sim, _ = best_alias_sim(query, term)
        if sim < NEAR_SIM_THRESH:
            continue
        if term.depth > parent.depth or len(term.name) >= len(parent.name):
            near_indexes.add(idx)

    best = None
    for idx in desc_indexes | near_indexes:
        term = gen.terms[idx]
        if term.homba_id == parent_id:
            continue
        if not shares_anatomical_core(query, term, gen):
            continue
        if _structure_class_conflict(q_tok_list, tokenize(term.name, config=gen.config)):
            continue
        # Don't pick the excluded structure as the "finer" target
        t_toks = set(tokenize(term.name, config=gen.config))
        if excluded and (excluded & t_toks) and not (excluded & set(tokenize(parent.name, config=gen.config))):
            # candidate is the excluded part itself
            if len(excluded & t_toks) >= max(1, len(excluded) // 2):
                continue

        sim, alias = best_alias_sim(query, term)
        uncovered = extra_content(q_toks, term, gen)
        covers_extra = len(uncovered) < len(parent_uncovered)
        under_parent = idx in desc_indexes

        if under_parent:
            if sim < CHILD_SIM_THRESH and not (covers_extra and sim >= 0.60):
                continue
            # Must improve on parent somehow
            if not (covers_extra or sim >= parent_sim + MARGIN or sim >= 0.88):
                continue
        else:
            # Non-descendant: must cover query tokens the parent misses,
            # and be a near-exact match (avoids sibling / wrong-branch traps).
            if sim < NEAR_SIM_THRESH or not covers_extra:
                continue
            # Reject same-depth or shallower "siblings" that look similar
            if term.depth <= parent.depth:
                continue

        score = (1 if under_parent else 0, sim, -len(uncovered), term.depth)
        rec = {
            "sim": sim,
            "alias": alias,
            "name": term.name,
            "id": term.homba_id,
            "depth": term.depth,
            "covers_extra": covers_extra,
            "uncovered": sorted(uncovered),
            "under_parent": under_parent,
        }
        if best is None or score > (
            1 if best["under_parent"] else 0,
            best["sim"],
            -len(best["uncovered"]),
            best["depth"],
        ):
            best = rec

    if best is None:
        return {
            "bucket": "no_finer_ontology",
            "reason": (
                f"隕ｪ驟堺ｸ九↓繧ｯ繧ｨ繝ｪ繧偵ｈ繧願憶縺剰ｪｬ譏弱☆繧句ｭ舌′辟｡縺・
                f"・・arent_sim={parent_sim:.2f}"
                + (f", 隕ｪ縺梧悴繧ｫ繝舌・: {', '.join(sorted(parent_uncovered))}" if parent_uncovered else "")
                + "・・
            ),
            "candidate": "",
            "candidate_id": "",
            "parent_sim": round(parent_sim, 3),
            "child_sim": 0.0,
        }

    where = "隕ｪ縺ｮ蟄仙ｭｫ" if best["under_parent"] else "髫主ｱ､螟悶・鬮倬｡樔ｼｼ隱・
    return {
        "bucket": "finer_exists",
        "reason": (
            f"繧医ｊ邏ｰ縺九＞蛟呵｣懊≠繧奇ｼ・where}・・ {best['name']} "
            f"(sim={best['sim']:.2f} vs parent {parent_sim:.2f}"
            + ("; 霑ｽ蜉繧ｫ繝舌・縺ゅｊ" if best["covers_extra"] else "")
            + ")"
        ),
        "candidate": best["name"],
        "candidate_id": best["id"],
        "parent_sim": round(parent_sim, 3),
        "child_sim": round(best["sim"], 3),
    }


def render(cases: list[dict]) -> str:
    no_finer = [c for c in cases if c["bucket"] == "no_finer_ontology"]
    finer = [c for c in cases if c["bucket"] == "finer_exists"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    def ds_count(rows: list[dict]) -> str:
        from collections import Counter
        c = Counter(r["dataset"] for r in rows)
        return " ﾂｷ ".join(f"{k} {v}" for k, v in sorted(c.items()))

    def table(rows: list[dict], show_cand: bool) -> str:
        body = []
        for c in rows:
            reason = (c.get("pass3_reason") or c.get("pass1_reason") or "")[:160]
            cand_cell = (
                f"<div class='name'>{esc(c['candidate'])}</div>"
                f"<div class='meta'>{esc(c['candidate_id'])} ﾂｷ child_sim={c['child_sim']}</div>"
                if show_cand else
                f"<div class='meta'>parent_sim={c['parent_sim']}</div>"
            )
            body.append(
                "<tr>"
                f"<td class='ds'>{esc(c['dataset'])}</td>"
                f"<td class='q'>{esc(c['query'])}</td>"
                f"<td><div class='name'>{esc(c['top_name'])}</div>"
                f"<div class='meta'>{esc(c['top_homba_id'])}</div></td>"
                f"<td>{cand_cell}</td>"
                f"<td class='note'>{esc(c['reason'])}</td>"
                f"<td class='judge'>{esc(reason)}</td>"
                "</tr>"
            )
        head = (
            "<table class='cases'><thead><tr>"
            "<th>set</th><th>query</th><th>top1 (parent)</th>"
            + ("<th>繧医ｊ邏ｰ縺九＞蛟呵｣・/th>" if show_cand else "<th>隕ｪ繧ｹ繧ｳ繧｢</th>")
            + "<th>蛻・｡樒炊逕ｱ</th><th>DeepSeek逅・罰</th>"
            "</tr></thead><tbody>"
        )
        return head + "".join(body) + "</tbody></table>"

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>broader_parent 蛻・梵・育ｴｰ隱槭・譛臥┌・・/title>
<style>
:root {{ --fg:#1c1c1e; --muted:#6b6b70; --line:#e3e3e8; --bg:#fbfbfd; --ok:#1a7f37; --warn:#8a4b08; }}
* {{ box-sizing:border-box; }}
body {{ font-family:-apple-system,"Segoe UI",Roboto,"Helvetica Neue","Noto Sans JP",sans-serif;
  color:var(--fg); background:var(--bg); margin:0; line-height:1.55; }}
.wrap {{ max-width:1120px; margin:0 auto; padding:28px 22px 72px; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
h2 {{ font-size:18px; margin:36px 0 10px; padding-bottom:6px; border-bottom:2px solid var(--line); }}
.sub {{ color:var(--muted); font-size:14px; margin:0 0 18px; }}
.cards {{ display:flex; gap:12px; flex-wrap:wrap; margin:14px 0; }}
.card {{ flex:1 1 160px; background:#fff; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.card .k {{ font-size:12px; color:var(--muted); }}
.card .v {{ font-size:28px; font-weight:700; margin-top:2px; }}
.card .s {{ font-size:12px; color:var(--muted); margin-top:4px; }}
.card.ok {{ border-left:4px solid var(--ok); }}
.card.warn {{ border-left:4px solid var(--warn); }}
.note {{ background:#fff; border:1px solid var(--line); border-radius:10px; padding:12px 14px; font-size:14px; margin:10px 0 16px; }}
table.cases {{ width:100%; border-collapse:collapse; background:#fff; border:1px solid var(--line);
  border-radius:8px; overflow:hidden; font-size:13px; }}
.cases th, .cases td {{ padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; text-align:left; }}
.cases th {{ background:#f3f3f6; font-size:12px; color:var(--muted); }}
.ds {{ color:var(--muted); width:64px; font-size:12px; }}
.q {{ font-weight:600; width:200px; }}
.name {{ font-weight:600; }}
.meta {{ color:var(--muted); font-size:11.5px; margin-top:3px; }}
td.note {{ color:#555; font-size:12.5px; width:220px; }}
section.ok td.note {{ color:var(--ok); }}
section.warn td.note {{ color:var(--warn); }}
.judge {{ color:#6a5a00; font-size:12px; width:220px; }}
.badge {{ display:inline-block; color:#fff; font-size:12px; font-weight:600; padding:2px 8px; border-radius:20px; }}
.badge.ok {{ background:var(--ok); }}
.badge.warn {{ background:var(--warn); }}
details {{ background:#fff; border:1px solid var(--line); border-radius:8px; margin:8px 0; padding:4px 12px; }}
details > summary {{ cursor:pointer; font-weight:600; padding:8px 2px; }}
ul.compact {{ margin:6px 0 0 18px; padding:0; font-size:13.5px; }}
</style></head><body><div class="wrap">
<h1>broader_parent 蛻・梵繝ｬ繝昴・繝・/h1>
<p class="sub">繧ｽ繝ｼ繧ｹ: round7_nodir・・cs_corpus_no_direction + rcs_species・可ｷ
broader_parent {len(cases)} 莉ｶ ﾂｷ 逕滓・: {now}</p>

<div class="cards">
  <div class="card"><div class="k">broader_parent 蜷郁ｨ・/div><div class="v">{len(cases)}</div>
    <div class="s">{ds_count(cases)}</div></div>
  <div class="card ok"><div class="k">邏ｰ隱槭′蟄伜惠縺励↑縺・ｼ郁ｦｪ繝偵ャ繝亥ｦ･蠖難ｼ・/div><div class="v">{len(no_finer)}</div>
    <div class="s">{ds_count(no_finer)} ﾂｷ {100*len(no_finer)/len(cases):.0f}%</div></div>
  <div class="card warn"><div class="k">邏ｰ隱槭′縺ゅｋ縺ｮ縺ｫ隕ｪ縺ｫ繝偵ャ繝・/div><div class="v">{len(finer)}</div>
    <div class="s">{ds_count(finer)} ﾂｷ {100*len(finer)/len(cases):.0f}%</div></div>
</div>

<div class="note">
<strong>蛻・｡樊婿驥・/strong>
<ul class="compact">
<li><strong>邏ｰ隱槭′蟄伜惠縺励↑縺・/strong> 窶・霑斐＠縺溯ｦｪ縺ｮ蟄仙ｭｫ・医∪縺溘・蜊∝・縺ｫ豺ｱ縺・ｫ倬｡樔ｼｼ隱橸ｼ峨↓縲・繧ｯ繧ｨ繝ｪ縺ｮ蛹ｺ蛻･隱槭ｒ隕ｪ繧医ｊ濶ｯ縺剰ｪｬ譏弱☆繧・HOMBA 隱槭′隕九▽縺九ｉ縺ｪ縺・りｦｪ縺ｸ縺ｮ蜷ｸ蜿弱・繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ荳雁ｦ･蠖薙・/li>
<li><strong>邏ｰ隱槭′縺ゅｋ縺ｮ縺ｫ隕ｪ縺ｫ繝偵ャ繝・/strong> 窶・隕ｪ縺ｮ蟄仙ｭｫ縲√∪縺溘・讒矩繧ｯ繝ｩ繧ｹ荳閾ｴ縺ｮ豺ｱ縺・ｫ倬｡樔ｼｼ隱槭→縺励※
繧医ｊ蜈ｷ菴鍋噪縺ｪ蛟呵｣懊′縺ゅｋ縺ｮ縺ｫ縲ヽCS 縺瑚ｦｪ繧・top1 縺ｫ縺励◆縲ゅせ繧ｳ繧｢繝ｪ繝ｳ繧ｰ・剰ｾ樊嶌・剰ｦｪ譏・ｼ縺ｮ謾ｹ蝟・ｽ吝慍縲・/li>
<li>蛻､螳壹・鬘樔ｼｼ蠎ｦ繝ｻ繝医・繧ｯ繝ｳ繧ｫ繝舌・繝ｻ讒矩繧ｯ繝ｩ繧ｹ陦晉ｪ√・excluding 蜿･縺ｮ髯､螟悶ｒ邨・∩蜷医ｏ縺帙◆繝偵Η繝ｼ繝ｪ繧ｹ繝・ぅ繝・け縲・蠅・阜萓九・ DeepSeek 逅・罰谺・→辣ｧ蜷医☆繧九％縺ｨ縲・/li>
</ul>
</div>

<h2><span class="badge ok">邏ｰ隱槭′蟄伜惠縺励↑縺・/span> {len(no_finer)} 莉ｶ
<span style="font-weight:400;color:var(--muted);font-size:13px">・・ds_count(no_finer)}・・/span></h2>
<section class="ok">
<details><summary>荳隕ｧ繧定｡ｨ遉ｺ・・len(no_finer)}・・/summary>
{table(no_finer, show_cand=False)}
</details>
</section>

<h2><span class="badge warn">邏ｰ隱槭′縺ゅｋ縺ｮ縺ｫ隕ｪ縺ｫ繝偵ャ繝・/span> {len(finer)} 莉ｶ
<span style="font-weight:400;color:var(--muted);font-size:13px">・・ds_count(finer)}・・/span></h2>
<section class="warn">
<details open><summary>荳隕ｧ繧定｡ｨ遉ｺ・・len(finer)}・俄・謾ｹ蝟・━蜈・/summary>
{table(finer, show_cand=True)}
</details>
</section>

</div></body></html>"""


def main() -> None:
    rows = [
        r for r in csv.DictReader(RECORDS.open(encoding="utf-8-sig"))
        if r["final_label"] == "broader_parent"
    ]
    print(f"broader_parent={len(rows)} loading HOMBA...", flush=True)
    gen = RosettaCandidateGenerator(REPO / "rcs" / "HOMBA_v1_fixed.csv")
    children = build_children(gen)

    cases = []
    for i, r in enumerate(rows, 1):
        cls = classify_case(r, gen, children)
        cases.append({
            "dataset": r["dataset"],
            "query": r["query"],
            "top_name": r["top_name"],
            "top_homba_id": r["top_homba_id"],
            "pass1_reason": r.get("pass1_reason", ""),
            "pass3_reason": r.get("pass3_reason", ""),
            **cls,
        })
        if i % 50 == 0:
            print(f"  {i}/{len(rows)}...", flush=True)

    no_finer = sum(1 for c in cases if c["bucket"] == "no_finer_ontology")
    finer = len(cases) - no_finer
    print(f"no_finer={no_finer} finer_exists={finer}", flush=True)

    OUT.write_text(render(cases), encoding="utf-8")
    summary = {
        "n": len(cases),
        "no_finer_ontology": no_finer,
        "finer_exists": finer,
        "cases": [
            {k: c[k] for k in (
                "dataset", "query", "top_name", "top_homba_id", "bucket",
                "candidate", "candidate_id", "parent_sim", "child_sim", "reason",
            )}
            for c in cases
        ],
    }
    (HERE / "runs" / "round7_nodir" / "broader_parent_analysis.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
