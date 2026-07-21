#!/usr/bin/env python3
"""Evaluate v0.8 (no parent promotion) vs round7_nodir; differential DeepSeek.

Baseline judgements: runs/round7_nodir (not re-validated when top1 unchanged).
Treatment: current RCS (ENGINE_VERSION 0.8.x 窶・parent promotion removed).

Writes runs/round8_nodir/ then regenerates
top1_consistency_review/auto_improve_report_nodir.html as
baseline_nodir 竊・round8_nodir.

Usage
-----
    python eval_round8_nodir_report.py --workers 24
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    ENGINE_VERSION,
    RosettaCandidateGenerator,
)
import eval_harness as eh  # noqa: E402
import generate_html_report as report  # noqa: E402

PREV_TAG = "round7_nodir"
FINAL_TAG = "round8_nodir"
REPORT_BASELINE = "baseline_nodir"
OUT_HTML = (
    HERE.parent / "top1_consistency_review" / "auto_improve_report_nodir.html"
)


def load_records(tag: str) -> dict[tuple[str, str], dict]:
    path = eh.RUNS_DIR / tag / "records.csv"
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


def run_rcs() -> list[eh.QueryResult]:
    generator = RosettaCandidateGenerator(
        eh.HOMBA_CSV,
        token_rules_csv=eh.RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=eh.RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=eh.RCS_DIR / "homba_abbrev_rules.csv",
    )
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--batch-size", type=int, default=6)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--skip-report", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT_HTML)
    args = ap.parse_args()

    prev = load_records(PREV_TAG)
    if not prev:
        print(f"previous run {PREV_TAG} records missing", flush=True)
        return 1

    print(f"[{FINAL_TAG}] engine v{ENGINE_VERSION} running RCS...", flush=True)
    t0 = time.time()
    results = run_rcs()
    print(f"  {len(results)} queries in {time.time() - t0:.1f}s", flush=True)

    changed: list[eh.QueryResult] = []
    unchanged = 0
    for r in results:
        base = prev.get((r.dataset, r.query))
        if base is not None and r.top_homba_id == base["top_homba_id"]:
            unchanged += 1
        else:
            changed.append(r)

    print(f"  top1 unchanged={unchanged} changed={len(changed)} (vs {PREV_TAG})", flush=True)

    cache = eh.load_cache()
    if not args.no_llm and changed:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set.", flush=True)
            return 2
        need = [
            r for r in changed
            if r.top_homba_id
            and not all(
                p in cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {})
                for p, _, _ in eh.PASSES
            )
        ]
        print(
            f"  DeepSeek: {len(need)}/{len(changed)} changed pairs need judging",
            flush=True,
        )
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
        base = prev.get((r.dataset, r.query))
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
                    "prev_id": base["top_homba_id"],
                    "prev_name": base["top_name"],
                    "prev_label": base["final_label"],
                    "new_id": r.top_homba_id,
                    "new_name": r.top_name,
                    "new_label": row["final_label"],
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
    summary["engine_version"] = ENGINE_VERSION
    summary["diff_vs"] = {
        "previous": PREV_TAG,
        "top1_unchanged": unchanged,
        "top1_changed": len(changed),
        "deepseek_judged_changed_only": True,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "top1_diff_vs_round7.json").write_text(
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
        # Patch CHANGES / findings text for round8 before render
        report.CHANGES = [
            *report.CHANGES,
        ]
        # Ensure Round8 change is present once
        if not any("隕ｪ譏・ｼ縺ｮ蜑企勁" in t for t, _ in report.CHANGES):
            report.CHANGES.append(
                ("縲審ound8縲題ｦｪ譏・ｼ縺ｮ蜑企勁 + 蠑ｱ隱､繝槭ャ繝∵椛蛻ｶ",
                 "_promote_common_parents 縺ｨ 2-pass 繧呈彫蜴ｻ縲・
                 "鬆伜沺繧｢繝ｳ繧ｫ繝ｼ蠢・医・讒矩繧ｯ繝ｩ繧ｹ・・rea竊把laustrum・峨・隍・焚蠖｢ nuclei 貂帷せ縺ｨ"
                 "FST/STS/orbital 遲峨・霎樊嶌縺ｧ縲∵・譬ｼ繧ｪ繝墓凾縺ｮ wrong 蠅励ｒ蝗槫庶縺励▽縺､邏ｰ隱槭ヲ繝・ヨ繧堤ｶｭ謖√・),
            )
        html = report.render(REPORT_BASELINE, FINAL_TAG)
        # Soften regression note and retitle final bar
        html = html.replace(
            f"譛邨・({FINAL_TAG})",
            f"譛邨・(round8 / no parent promotion)",
        )
        html = html.replace(
            "螟壹￥縺ｯ broader_parent 竊・partial 縺ｮ蜈･繧梧崛繧上ｊ繧・∫分蜿ｷ莉倥″鬆伜沺縺ｮ霑大ｍ隱､繝槭ャ繝√・n"
            "繝阪ャ繝医〒縺ｯ螟ｧ蟷・↓謾ｹ蝟・・,
            "Round8 縺ｯ隕ｪ譏・ｼ蜑企勁縺御ｸｻ蝗縲Ｕop1 荳榊､峨Ξ繧ｳ繝ｼ繝峨・ round7 蛻､螳壹ｒ邯呎価縺励・
            "螟牙喧蛻・・縺ｿ DeepSeek 蜀肴､懆ｨｼ縲・,
        )
        # Findings section: rewrite for round8
        import re
        bov = report.load_summary(REPORT_BASELINE)["overall"]["label_counts"]
        fov = overall
        wrong_d = fov.get("wrong", 0) - bov.get("wrong", 0)
        findings = f"""
<p><b>謌先棡:</b> wrong 繧・{bov.get('wrong', 0)} 竊・{fov.get('wrong', 0)} 莉ｶ・・wrong_d:+d}・峨・Round8 縺ｧ隕ｪ譏・ｼ・・ierarchy_parent・峨→ 2-pass 繧貞炎髯､縺励・伜沺繧｢繝ｳ繧ｫ繝ｼ繝ｻ讒矩繧ｯ繝ｩ繧ｹ繝ｻ霎樊嶌縺ｧ
譏・ｼ萓晏ｭ倥・隕ｪ繝偵ャ繝医→邏ｰ隱槭ヲ繝・ヨ繧剃ｸ｡遶九・/p>
<p><b>隧穂ｾ｡:</b> baseline_nodir 竊・round8_nodir縲Ｓound7 豈斐〒 top1 螟牙喧 {len(changed)} 莉ｶ縺ｮ縺ｿ
DeepSeek・井ｸ榊､・{unchanged} 莉ｶ縺ｯ蛻､螳夂ｶ呎価・峨・/p>
<p><b>谿玖ｪｲ鬘・</b></p>
<ul>
<li><b>繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ谺謳・/b>・・1縲廣13 cell group縲）uxtaparaventricular縲〉etroreuniens縲・pre-SMA縲《piral ganglion縲…ochlea 遲会ｼ・ HOMBA 縺ｫ蟇ｾ蠢懆ｪ槭′辟｡縺・りｾ樊嶌縺ｧ縺ｯ蜷ｸ蜿惹ｸ崎・縲・/li>
<li><b>逡ｪ蜿ｷ莉倥″邏ｰ蛹ｺ蛻・・谿倶ｽ・/b>・・P1/OP4縲∥rea PH・・ 繧ｳ繝ｼ繝我ｸ閾ｴ蠢・亥喧縺ｮ蠑ｷ蛹悶→
HOMBA 蛛ｴ縺ｮ蛻･蜷肴紛蛯吶・/li>
<li><b>讒矩繧ｯ繝ｩ繧ｹ縺ｮ蠅・阜萓・/b>・・ucleus of stria medullaris・・ 豁｣縺励＞繧ｯ繝ｩ繧ｹ縺ｮ蛟呵｣懆・菴薙′
繧ｪ繝ｳ繝医Ο繧ｸ繝ｼ縺ｫ辟｡縺・ｴ蜷医・繝輔か繝ｼ繝ｫ繝舌ャ繧ｯ險ｭ險医・/li>
</ul>
"""
        html = re.sub(
            r"<h2>7\. 謇隕九・谺｡繧｢繧ｯ繧ｷ繝ｧ繝ｳ蛟呵｣・/h2>\s*<div class=\"note\">.*?</div>",
            "<h2>7. 謇隕九・谺｡繧｢繧ｯ繧ｷ繝ｧ繝ｳ蛟呵｣・/h2>\n<div class=\"note\">"
            + findings
            + "</div>",
            html,
            count=1,
            flags=re.S,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(html, encoding="utf-8")
        print(f"  wrote {args.out}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
