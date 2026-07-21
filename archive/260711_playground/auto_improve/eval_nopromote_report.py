#!/usr/bin/env python3
"""Evaluate round7 with parent promotion disabled; reuse judgements when top1 unchanged.

Baseline: runs/round7_nodir (already judged; not re-validated).
Treatment: same RCS code with ``_promote_common_parents`` monkey-patched to no-op.

DeepSeek 3-pass is invoked only for (dataset, query) pairs whose top1 HOMBA id
differs from the round7_nodir baseline. Unchanged top1 rows copy the baseline
judgement fields verbatim.

Writes
------
    runs/round7_nopromote/records.csv
    runs/round7_nopromote/summary.json
    runs/round7_nopromote/top1_diff.json   # changed / unchanged counts

Then optionally builds the HTML report via generate_html_report.py.

Usage
-----
    python eval_nopromote_report.py --workers 24
    python eval_nopromote_report.py --no-llm   # RCS + copy-only (changed stay unjudged)
    python eval_nopromote_report.py --skip-report
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from types import MethodType
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    RosettaCandidateGenerator,
)
import eval_harness as eh  # noqa: E402
import generate_html_report as report  # noqa: E402

BASELINE_TAG = "round7_nodir"
FINAL_TAG = "round7_nopromote"
OUT_HTML = (
    HERE.parent / "top1_consistency_review" / "ablate_parent_promotion_report.html"
)

ABLATION_CHANGES = [
    ("隕ｪ譏・ｼ縺ｮ辟｡蜉ｹ蛹・(_promote_common_parents 竊・no-op)",
     "Round7 繧｢繝ｫ繧ｴ繝ｪ繧ｺ繝縺ｯ縺昴・縺ｾ縺ｾ縺ｫ縲∝・騾夊ｦｪ縺ｸ縺ｮ繧ｹ繧ｳ繧｢譏・ｼ縺縺代ｒ蛛懈ｭ｢縲・
     "繧ｽ繝ｼ繧ｹ縺ｯ螟画峩縺帙★繧､繝ｳ繧ｹ繧ｿ繝ｳ繧ｹ荳翫〒 monkey-patch縲・),
    ("蛻､螳壹・蟾ｮ蛻・・縺ｿ蜀肴､懆ｨｼ",
     "baseline・・ound7_nodir・峨→ top1 縺悟酔荳縺ｮ繝ｬ繧ｳ繝ｼ繝峨・ DeepSeek 繧貞他縺ｰ縺壹・
     "譌｢蟄倥・ 3-pass 蛻､螳壹ｒ縺昴・縺ｾ縺ｾ邯呎価縲Ｕop1 縺悟､峨ｏ縺｣縺溘・繧｢縺縺第眠隕丞愛螳・
     "・医く繝｣繝・す繝･繧ｭ繝ｼ dataset||query||top_id 繧貞・蛻ｩ逕ｨ・峨・),
]

def build_ablation_findings(
    bov: dict,
    fov: dict,
    n_improved: int,
    n_regressed: int,
    n_changed: int,
    n_unchanged: int,
) -> str:
    wrong_d = fov.get("wrong", 0) - bov.get("wrong", 0)
    good_b = bov.get("aligned", 0) + bov.get("broader_parent", 0)
    good_f = fov.get("aligned", 0) + fov.get("broader_parent", 0)
    return f"""
<p><b>螳滄ｨ・</b> Round7 邨ゆｺ・凾轤ｹ・・ound7_nodir・峨ｒ baseline 縺ｨ縺励∬ｦｪ譏・ｼ縺縺代ｒ繧ｪ繝輔・baseline 縺ｮ蜀肴､懆ｨｼ縺ｯ陦後ｏ縺壹》op1 荳榊､・{n_unchanged} 莉ｶ縺ｯ蛻､螳壹ｒ邯呎価縲・螟牙喧 {n_changed} 莉ｶ縺縺・DeepSeek・医く繝｣繝・す繝･蜷ｫ繧・峨・/p>
<p><b>邨先棡:</b> wrong {bov.get('wrong', 0)} 竊・{fov.get('wrong', 0)}・・wrong_d:+d}・峨・aligned+broader {good_b} 竊・{good_f}・・good_f - good_b:+d}・峨・繝ｩ繝吶Ν謾ｹ蝟・{n_improved} / 蝗槫ｸｰ {n_regressed}縲・隕ｪ譏・ｼ繧ｪ繝輔・邏ｰ隱槭ヲ繝・ヨ・・Pi縲＾FC縲！C central 遲会ｼ峨〒荳驛ｨ謾ｹ蝟・☆繧九′縲・STS/orbital 遲峨〒隕ｪ繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ縺悟､悶ｌ wrong 縺悟｢励∴縲√ロ繝・ヨ縺ｧ縺ｯ謔ｪ蛹悶・/p>
<p><b>谺｡繧｢繧ｯ繧ｷ繝ｧ繝ｳ:</b> 蜈ｨ髱｢繧ｪ繝輔・髱樊耳螂ｨ縲らｴｰ隱槭′螳溷惠縺吶ｋ繧ｱ繝ｼ繧ｹ縺縺第・譬ｼ繧呈椛縺医ｋ
譚｡莉ｶ莉倥″險ｭ險茨ｼ井ｿｮ鬟ｾ縺ゅｊ繝ｻ蟄仙呵｣懊′鬮倥せ繧ｳ繧｢遲会ｼ峨ｒ讀懆ｨ弱・/p>
"""


def noop_promote(self, *args, **kwargs) -> None:  # noqa: ANN001
    return None


def run_rcs_nopromote() -> list[eh.QueryResult]:
    generator = RosettaCandidateGenerator(
        eh.HOMBA_CSV,
        token_rules_csv=eh.RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=eh.RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=eh.RCS_DIR / "homba_abbrev_rules.csv",
    )
    generator._promote_common_parents = MethodType(noop_promote, generator)

    results: list[eh.QueryResult] = []
    for dataset, query in eh.load_queries():
        cands = generator.generate(query, top_k=3)
        if not cands:
            results.append(eh.QueryResult(dataset, query, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(
            eh.QueryResult(
                dataset=dataset,
                query=query,
                top_homba_id=str(top.get("homba_id", "")),
                top_name=str(top.get("name", "")),
                score=str(top.get("score", "")),
                methods=str(top.get("methods", "")),
                matched_query=str(top.get("matched_query", "")),
                matched_alias=str(top.get("matched_alias", "")),
                modifier_terms=str(top.get("modifier_terms", "")),
                top3=[
                    {
                        "homba_id": c.get("homba_id"),
                        "name": c.get("name"),
                        "score": c.get("score"),
                        "methods": c.get("methods"),
                    }
                    for c in cands[:3]
                ],
            )
        )
    return results


def load_baseline_records() -> dict[tuple[str, str], dict]:
    path = eh.RUNS_DIR / BASELINE_TAG / "records.csv"
    rows: dict[tuple[str, str], dict] = {}
    with path.open(encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rows[(row["dataset"], row["query"])] = row
    return rows


def copy_judgement_fields(base: dict) -> dict[str, Any]:
    keys = [
        "pass1_label", "pass1_reason",
        "pass2_label", "pass2_reason",
        "pass3_label", "pass3_reason",
        "final_label", "final_certainty", "final_confidence",
        "vote_agreement", "vote_split_pattern", "uncertainty_tag",
    ]
    return {k: base.get(k, "") for k in keys}


def build_row_from_votes(
    i: int,
    r: eh.QueryResult,
    votes: dict[str, Any],
) -> dict[str, Any]:
    p1 = votes.get("pass1", {})
    p2 = votes.get("pass2", {})
    p3 = votes.get("pass3", {})
    final = eh.final_decision(p1, p2, p3)
    return {
        "validation_id": i,
        "dataset": r.dataset,
        "query": r.query,
        "top_homba_id": r.top_homba_id,
        "top_name": r.top_name,
        "score": r.score,
        "methods": r.methods,
        "matched_query": r.matched_query,
        "matched_alias": r.matched_alias,
        "modifier_terms": r.modifier_terms,
        "top3": json.dumps(r.top3, ensure_ascii=False),
        "pass1_label": p1.get("label", ""),
        "pass1_reason": p1.get("reason", ""),
        "pass2_label": p2.get("label", ""),
        "pass2_reason": p2.get("reason", ""),
        "pass3_label": p3.get("label", ""),
        "pass3_reason": p3.get("reason", ""),
        "final_label": final["label"],
        "final_certainty": final["certainty"],
        "final_confidence": final["confidence"],
        "vote_agreement": final["agreement"],
        "vote_split_pattern": final["vote_split_pattern"],
        "uncertainty_tag": final["uncertainty_tag"],
    }


def render_ablation_report(baseline_tag: str, final_tag: str) -> str:
    """Same shape as generate_html_report.render, with ablation-specific copy."""
    import re

    html = report.render(baseline_tag, final_tag)
    bsum = report.load_summary(baseline_tag)
    fsum = report.load_summary(final_tag)
    brows = report.load_records(baseline_tag)
    frows = report.load_records(final_tag)
    improved, regressed = report.diff_runs(brows, frows)
    bov = bsum["overall"]["label_counts"]
    fov = fsum["overall"]["label_counts"]
    abl = fsum.get("ablation", {})
    n_changed = int(abl.get("top1_changed", 0))
    n_unchanged = int(abl.get("top1_unchanged", 0))

    html = html.replace(
        "RCS 繧｢繝ｫ繧ｴ繝ｪ繧ｺ繝 閾ｪ蠕区隼蝟・Ξ繝昴・繝・,
        "RCS 隕ｪ譏・ｼ繧｢繝悶Ξ繝ｼ繧ｷ繝ｧ繝ｳ繝ｬ繝昴・繝・,
        1,
    )
    html = html.replace(
        f"(baseline 竊・{final_tag})",
        f"({baseline_tag} 竊・{final_tag})",
        1,
    )

    changes_html = "".join(
        f"<li><b>{report.esc(t)}</b><br><span class='muted'>{report.esc(d)}</span></li>"
        for t, d in ABLATION_CHANGES
    )
    html = re.sub(
        r"<h2>5\. 螳滓命縺励◆繧｢繝ｫ繧ｴ繝ｪ繧ｺ繝謾ｹ蝟・/h2>\s*<ul class=\"changes\">.*?</ul>",
        "<h2>5. 譛ｬ螳滄ｨ薙・譚｡莉ｶ</h2>\n<ul class=\"changes\">"
        + changes_html
        + "</ul>",
        html,
        count=1,
        flags=re.S,
    )
    findings = build_ablation_findings(
        bov, fov, len(improved), len(regressed), n_changed, n_unchanged,
    )
    html = re.sub(
        r"<h2>7\. 謇隕九・谺｡繧｢繧ｯ繧ｷ繝ｧ繝ｳ蛟呵｣・/h2>\s*<div class=\"note\">.*?</div>",
        "<h2>7. 謇隕九・谺｡繧｢繧ｯ繧ｷ繝ｧ繝ｳ蛟呵｣・/h2>\n<div class=\"note\">"
        + findings
        + "</div>",
        html,
        count=1,
        flags=re.S,
    )
    html = html.replace(
        "螟壹￥縺ｯ broader_parent 竊・partial 縺ｮ蜈･繧梧崛繧上ｊ繧・∫分蜿ｷ莉倥″鬆伜沺縺ｮ霑大ｍ隱､繝槭ャ繝√・n"
        "繝阪ャ繝医〒縺ｯ螟ｧ蟷・↓謾ｹ蝟・・,
        "隕ｪ譏・ｼ繧ｪ繝輔↓繧医ｊ top1 縺悟､峨ｏ縺｣縺溘こ繝ｼ繧ｹ縺ｮ繝ｩ繝吶Ν荳贋ｸ九ｒ蛻玲嫌縲・
        "top1 荳榊､峨・繝ｬ繧ｳ繝ｼ繝峨・蛻､螳壹ｒ蜀榊茜逕ｨ縺励※縺・ｋ縲・,
    )
    html = html.replace(
        f"譛邨・({final_tag})",
        f"隕ｪ譏・ｼ繧ｪ繝・({final_tag})",
    )
    html = html.replace(
        'style="font-size:12px;margin-top:10px">baseline</div>',
        f'style="font-size:12px;margin-top:10px">baseline ({baseline_tag})</div>',
    )

    wrong_d = fov.get("wrong", 0) - bov.get("wrong", 0)
    aligned_d = fov.get("aligned", 0) - bov.get("aligned", 0)
    good_d = (
        fov.get("aligned", 0) + fov.get("broader_parent", 0)
        - bov.get("aligned", 0) - bov.get("broader_parent", 0)
    )

    def delta_cls(delta: int, *, higher_is_better: bool) -> str:
        if delta == 0:
            return "flat"
        better = delta > 0 if higher_is_better else delta < 0
        return "up" if better else "down"

    html = re.sub(
        r'(<div class="card"><div class="k">wrong・郁ｪ､繧奇ｼ・/div>\s*'
        r'<div class="v">\d+ 竊・\d+</div>\s*)'
        r'<div class="d [^"]*">([^<]*)</div>',
        rf'\1<div class="d {delta_cls(wrong_d, higher_is_better=False)}">\2</div>',
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="card"><div class="k">aligned</div>\s*'
        r'<div class="v">\d+ 竊・\d+</div>\s*)'
        r'<div class="d [^"]*">([^<]*)</div>',
        rf'\1<div class="d {delta_cls(aligned_d, higher_is_better=True)}">\2</div>',
        html,
        count=1,
    )
    html = re.sub(
        r'(<div class="card"><div class="k">aligned \+ broader_parent・郁ｨｱ螳ｹ蜿ｯ・・/div>\s*'
        r'<div class="v">\d+ 竊・\d+</div>\s*)'
        r'<div class="d [^"]*">([^<]*)</div>',
        rf'\1<div class="d {delta_cls(good_d, higher_is_better=True)}">\2</div>',
        html,
        count=1,
    )
    return html


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--batch-size", type=int, default=6)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--skip-report", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT_HTML)
    args = ap.parse_args()

    baseline = load_baseline_records()
    if not baseline:
        print(f"baseline {BASELINE_TAG} records missing", flush=True)
        return 1

    print(f"[{FINAL_TAG}] running RCS with parent promotion OFF...", flush=True)
    t0 = time.time()
    results = run_rcs_nopromote()
    print(f"  {len(results)} queries in {time.time()-t0:.1f}s", flush=True)

    changed: list[eh.QueryResult] = []
    unchanged = 0
    missing_base = 0
    for r in results:
        base = baseline.get((r.dataset, r.query))
        if base is None:
            missing_base += 1
            changed.append(r)
            continue
        if r.top_homba_id == base["top_homba_id"]:
            unchanged += 1
        else:
            changed.append(r)

    print(
        f"  top1 unchanged={unchanged} changed={len(changed)} "
        f"missing_baseline={missing_base}",
        flush=True,
    )

    cache = eh.load_cache()
    if not args.no_llm and changed:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set.", flush=True)
            return 2
        # Only judge pairs missing from cache
        need = [
            r for r in changed
            if r.top_homba_id
            and not all(
                p in cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {})
                for p, _, _ in eh.PASSES
            )
        ]
        print(f"  DeepSeek: {len(need)}/{len(changed)} changed pairs need judging", flush=True)
        for pass_name, model, prompt in eh.PASSES:
            workers = args.workers if model == eh.FLASH_MODEL else max(6, args.workers // 2)
            eh.judge_pass(
                need, pass_name, model, prompt, api_key, cache,
                args.batch_size, workers,
            )
            eh.save_cache(cache)
    elif args.no_llm:
        print("  --no-llm: skipping DeepSeek for changed pairs", flush=True)

    rows: list[dict[str, Any]] = []
    diff_detail = []
    for i, r in enumerate(results):
        base = baseline.get((r.dataset, r.query))
        same = base is not None and r.top_homba_id == base["top_homba_id"]
        if same:
            row = {
                "validation_id": i,
                "dataset": r.dataset,
                "query": r.query,
                "top_homba_id": r.top_homba_id,
                "top_name": r.top_name,
                "score": r.score,
                "methods": r.methods,
                "matched_query": r.matched_query,
                "matched_alias": r.matched_alias,
                "modifier_terms": r.modifier_terms,
                "top3": json.dumps(r.top3, ensure_ascii=False),
                **copy_judgement_fields(base),
            }
        else:
            key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
            votes = cache.get(key, {})
            row = build_row_from_votes(i, r, votes)
            if base is not None:
                diff_detail.append({
                    "dataset": r.dataset,
                    "query": r.query,
                    "baseline_id": base["top_homba_id"],
                    "baseline_name": base["top_name"],
                    "baseline_label": base["final_label"],
                    "nopromote_id": r.top_homba_id,
                    "nopromote_name": r.top_name,
                    "nopromote_label": row["final_label"],
                    "methods": r.methods,
                })
        rows.append(row)

    out_dir = eh.RUNS_DIR / FINAL_TAG
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "records.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = eh.build_summary(rows)
    summary["ablation"] = {
        "baseline": BASELINE_TAG,
        "treatment": "parent_promotion_off",
        "top1_unchanged": unchanged,
        "top1_changed": len(changed),
        "deepseek_judged_changed_only": True,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "top1_diff.json").write_text(
        json.dumps({
            "unchanged": unchanged,
            "changed": len(changed),
            "details": diff_detail,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    overall = summary["overall"]["label_counts"]
    print(f"\n[{FINAL_TAG}] label counts: {overall}", flush=True)
    print(
        f"  wrong={overall.get('wrong', 0)} "
        f"aligned={overall.get('aligned', 0)} "
        f"broader_parent={overall.get('broader_parent', 0)} "
        f"partial={overall.get('partial_or_narrower', 0)}",
        flush=True,
    )
    print(f"  wrote {csv_path}", flush=True)

    if not args.skip_report:
        html = render_ablation_report(BASELINE_TAG, FINAL_TAG)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
        print(f"  wrote {args.out}", flush=True)

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--report-only":
        sys.argv.pop(1)
        out = OUT_HTML
        if "--out" in sys.argv:
            i = sys.argv.index("--out")
            out = Path(sys.argv[i + 1])
        html = render_ablation_report(BASELINE_TAG, FINAL_TAG)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        print(f"wrote {out}")
        raise SystemExit(0)
    raise SystemExit(main())
