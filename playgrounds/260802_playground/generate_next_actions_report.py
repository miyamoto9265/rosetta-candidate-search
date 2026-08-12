#!/usr/bin/env python3
"""Generate next-actions HTML from round3_abbrev validation results."""

from __future__ import annotations

import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "runs" / "round3_abbrev"
OUT = RUN / "next_actions_report.html"


def esc(v: object) -> str:
    return html.escape(str(v or ""))


def lab(r: dict) -> str:
    if not r.get("top_homba_id"):
        return "no_match"
    return r.get("final_label") or "uncertain"


def score_of(r: dict) -> float:
    try:
        return float(r.get("score") or 0)
    except ValueError:
        return 0.0


def bucket_abbrev_problem(r: dict) -> str:
    q = r["query"]
    if lab(r) == "no_match":
        return "no_match"
    if re.search(
        r"[.+]|SPN|CRF|MC4R|Rspo|Ppp1|D1R|D2R|Glut|Vglut|GABAergic|Cre\b|interneurons",
        q,
        re.I,
    ):
        return "celltype_or_marker_compound"
    if re.search(r"\b(shell|core|pole|zone|lamina|laminae|layer)\b", q, re.I):
        return "subdivision_or_layer"
    if re.search(r"\b(ipsi|contra)", q, re.I):
        return "laterality_compound"
    if " " in q or "-" in q:
        return "multi_token_phrase"
    if len(q) <= 4:
        return "short_acronym"
    return "other"


def main() -> int:
    rows = list(
        csv.DictReader(
            (RUN / "validation_results.csv").open(encoding="utf-8-sig")
        )
    )
    summary = json.loads((RUN / "summary.json").read_text(encoding="utf-8"))
    baseline = json.loads(
        (HERE / "runs" / "baseline" / "summary.json").read_text(encoding="utf-8")
    )

    b = baseline["overall"]["label_counts"]
    a = summary["overall"]["label_counts"]
    b_nm = baseline.get("no_match_n", 0)
    a_nm = summary.get("no_match_n", 0)

    by_kind = {
        k: Counter(lab(r) for r in rows if r["query_kind"] == k)
        for k in ("abbrev", "fullname")
    }

    problems = [
        r
        for r in rows
        if r["query_kind"] == "abbrev"
        and lab(r) in ("wrong", "no_match", "source_or_ontology_issue")
    ]
    buckets = Counter(bucket_abbrev_problem(r) for r in problems)
    bucket_examples: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for r in problems:
        bkt = bucket_abbrev_problem(r)
        if len(bucket_examples[bkt]) < 4:
            bucket_examples[bkt].append(
                (r["query"], lab(r), (r.get("top_name") or "(no_match)")[:55])
            )

    high_wrong = sorted(
        [
            r
            for r in rows
            if r["query_kind"] == "abbrev"
            and lab(r) == "wrong"
            and score_of(r) >= 0.75
        ],
        key=score_of,
        reverse=True,
    )

    by_struct: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_struct[r["structure_name"]][r["query_kind"]] = r
    nm_good_fn = []
    for sn, d in by_struct.items():
        ab, fn = d.get("abbrev"), d.get("fullname")
        if not ab or lab(ab) != "no_match":
            continue
        if fn and lab(fn) in ("aligned", "broader_parent"):
            nm_good_fn.append(
                (ab["query"], fn["query"][:50], lab(fn), (fn.get("top_name") or "")[:45])
            )

    fw = [r for r in rows if r["query_kind"] == "fullname" and lab(r) == "wrong"]
    bp_tops = Counter(
        (r.get("top_name") or "")[:48]
        for r in rows
        if r["query_kind"] == "abbrev" and lab(r) == "broader_parent"
    )

    def delta(x: int, y: int) -> str:
        d = y - x
        return f"+{d}" if d > 0 else str(d)

    bucket_rows = "".join(
        f"<tr><td><code>{esc(k)}</code></td>"
        f'<td class="num">{buckets[k]}</td>'
        f"<td class=\"small muted\">"
        + "; ".join(
            f"{esc(q)}→{esc(top)}" for q, _, top in bucket_examples.get(k, [])
        )
        + "</td></tr>"
        for k, _ in buckets.most_common()
    )

    high_rows = "".join(
        f"<tr><td class=\"query-cell\">{esc(r['query'])}</td>"
        f'<td class="num">{score_of(r):.2f}</td>'
        f"<td>{esc((r.get('top_name') or '')[:55])}</td>"
        f"<td class=\"muted small\">{esc((r.get('fullname') or '')[:45])}</td></tr>"
        for r in high_wrong[:18]
    )

    nm_rows = "".join(
        f"<tr><td class=\"query-cell\">{esc(q)}</td>"
        f"<td>{esc(fn)}</td>"
        f"<td><span class=\"pill parent\">{esc(lbl)}</span></td>"
        f"<td class=\"muted small\">{esc(top)}</td></tr>"
        for q, fn, lbl, top in nm_good_fn[:15]
    )

    bp_rows = "".join(
        f"<tr><td>{esc(name)}</td><td class=\"num\">{n}</td></tr>"
        for name, n in bp_tops.most_common(10)
    )

    fw_rows = "".join(
        f"<tr><td class=\"query-cell\">{esc(r['query'][:55])}</td>"
        f"<td>{esc((r.get('top_name') or '')[:50])}</td>"
        f'<td class="num">{score_of(r):.2f}</td></tr>'
        for r in sorted(fw, key=score_of, reverse=True)[:12]
    )

    doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Next actions after round3 abbrev — 260802</title>
  <style>
    :root {{
      --bg: #f4f6f9; --panel: #fff; --text: #1a2332; --muted: #667085; --line: #d8dee8;
      --ok: #0b7a4b; --parent: #2f6fed; --warn: #b7791f; --bad: #b42318; --issue: #7a3fb4; --unknown: #475467;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
      background: var(--bg); color: var(--text);
    }}
    header {{
      padding: 28px 32px 20px;
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
      color: #fff;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 24px; font-weight: 700; }}
    header p {{ margin: 0; color: #cbd5e1; max-width: 1000px; line-height: 1.65; font-size: 14px; }}
    main {{ padding: 22px 32px 56px; max-width: 1400px; margin: 0 auto; }}
    section {{
      background: var(--panel); border: 1px solid var(--line);
      border-radius: 12px; padding: 18px 20px; margin: 0 0 16px;
    }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 16px 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; }}
    .cards {{
      display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr));
      gap: 10px; margin: 12px 0 4px;
    }}
    .card {{
      border: 1px solid var(--line); border-radius: 10px;
      padding: 12px 14px; background: #fafbfd;
    }}
    .card-title {{ color: var(--muted); font-size: 12px; }}
    .card-value {{ font-size: 24px; font-weight: 700; margin-top: 2px; font-variant-numeric: tabular-nums; }}
    .card-sub {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{
      border-bottom: 1px solid var(--line); padding: 8px 10px;
      text-align: left; vertical-align: top; font-size: 13px;
    }}
    th {{ background: #f2f4f7; font-size: 12px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 12px; }}
    .note {{ color: var(--muted); line-height: 1.65; font-size: 13px; }}
    .pill {{
      display: inline-block; padding: 2px 8px; border-radius: 999px;
      color: #fff; font-size: 11px; font-weight: 600;
    }}
    .pill.ok {{ background: var(--ok); }}
    .pill.parent {{ background: var(--parent); }}
    .pill.warn {{ background: var(--warn); }}
    .pill.bad {{ background: var(--bad); }}
    .pill.issue {{ background: var(--issue); }}
    .pill.unknown {{ background: var(--unknown); }}
    code {{ background: #eef2f6; border-radius: 4px; padding: 1px 5px; font-size: 12px; }}
    .prio {{
      display: inline-block; min-width: 28px; text-align: center;
      border-radius: 6px; font-size: 11px; font-weight: 700; padding: 2px 6px; color: #fff;
    }}
    .prio.p0 {{ background: #7f1d1d; }}
    .prio.p1 {{ background: #9a3412; }}
    .prio.p2 {{ background: #2f6fed; }}
    .prio.p3 {{ background: #475467; }}
    ol.actions > li {{ margin: 0 0 14px; line-height: 1.6; }}
    .flow {{
      background: #0f172a; color: #e2e8f0; border-radius: 10px;
      padding: 14px 16px; font-family: ui-monospace, Consolas, monospace;
      font-size: 12.5px; line-height: 1.75; overflow: auto; white-space: pre;
    }}
    .query-cell {{ font-weight: 600; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    @media (max-width: 900px) {{
      .cards, .grid2 {{ grid-template-columns: 1fr; }}
      main {{ padding: 16px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Round3 以降の次アクション分析</h1>
    <p>
      abbrev 整備（baseline → round3_abbrev）を踏まえ、残課題の内訳と
      「やるべき順」を整理したアクションレポートです。過学習を避け、RCS の一般価値を上げる方針を優先します。
    </p>
  </header>
  <main>
    <section>
      <h2>1. いまどこまで来たか</h2>
      <div class="cards">
        <div class="card">
          <div class="card-title">no_match</div>
          <div class="card-value">{a_nm}</div>
          <div class="card-sub">baseline {b_nm} → {delta(b_nm, a_nm)}</div>
        </div>
        <div class="card">
          <div class="card-title">aligned</div>
          <div class="card-value">{a.get('aligned', 0)}</div>
          <div class="card-sub">baseline {b.get('aligned', 0)} → {delta(b.get('aligned', 0), a.get('aligned', 0))}</div>
        </div>
        <div class="card">
          <div class="card-title">wrong</div>
          <div class="card-value">{a.get('wrong', 0)}</div>
          <div class="card-sub">baseline {b.get('wrong', 0)} → {delta(b.get('wrong', 0), a.get('wrong', 0))}</div>
        </div>
        <div class="card">
          <div class="card-title">broader_parent</div>
          <div class="card-value">{a.get('broader_parent', 0)}</div>
          <div class="card-sub">「正しいが粗い」上限が残る</div>
        </div>
      </div>
      <p class="note">
        Round1–3 で効いたのは <b>文献略語ルール + 衝突 demotion + 安全なインライン展開</b>。
        HOMBA acronym は維持したまま、コーパス慣用をクエリ側で優先する設計は妥当だった。
        残差の大半は「まだ辞書で拾える略語」より、<b>複合句・細胞型接尾辞・オントロジー粒度ギャップ・fullname 曖昧性</b>に移っている。
      </p>
      <h3>round3 内訳</h3>
      <table>
        <thead><tr><th>kind</th><th class="num">n</th><th class="num">aligned</th><th class="num">broader</th><th class="num">wrong</th><th class="num">no_match</th></tr></thead>
        <tbody>
          <tr>
            <td>abbrev</td><td class="num">2368</td>
            <td class="num">{by_kind['abbrev'].get('aligned', 0)}</td>
            <td class="num">{by_kind['abbrev'].get('broader_parent', 0)}</td>
            <td class="num">{by_kind['abbrev'].get('wrong', 0)}</td>
            <td class="num">{by_kind['abbrev'].get('no_match', 0)}</td>
          </tr>
          <tr>
            <td>fullname</td><td class="num">1090</td>
            <td class="num">{by_kind['fullname'].get('aligned', 0)}</td>
            <td class="num">{by_kind['fullname'].get('broader_parent', 0)}</td>
            <td class="num">{by_kind['fullname'].get('wrong', 0)}</td>
            <td class="num">{by_kind['fullname'].get('no_match', 0)}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section>
      <h2>2. 残課題のファミリ（abbrev problem = {len(problems)}）</h2>
      <table>
        <thead><tr><th>bucket</th><th class="num">n</th><th>examples</th></tr></thead>
        <tbody>{bucket_rows}</tbody>
      </table>
      <p class="note">
        <code>no_match</code> の多くは fullname も弱い／細胞型付きで、単純な略語追加では解けない。
        一方で fullname が aligned/broader なのに abbrev だけ落ちるケースはまだ <b>{len(nm_good_fn)}</b> 件あり、ここは低リスクで拾える。
      </p>
    </section>

    <section>
      <h2>3. 推奨アクション（優先順）</h2>
      <ol class="actions">
        <li>
          <span class="prio p0">P0</span>
          <b>エンジン v0.8.3 を本番デプロイ</b><br>
          <span class="note">
            WebUI Reports は 0802 だが、検索 API / Lambda が旧 engine のままだと利用者に改善が届かない。
            <code>rosetta_candidate_generator.py</code> + <code>homba_abbrev_rules.csv</code> をパッケージし、
            S3 辞書同期 → Lambda 更新 → スモーク（VP / DMS / PPN / CA1 / III / dorsolateral PAG）を必須にする。
          </span>
        </li>
        <li>
          <span class="prio p1">P1</span>
          <b>高信頼 wrong の選択的衝突解消（過学習禁止）</b>
          — 現在 score≥0.75 の abbrev wrong が <b>{len(high_wrong)}</b> 件。<br>
          <span class="note">
            方針: コーパス fullname と整合し、かつ HOMBA に対応ノードがあるものだけルール化。
            例: <code>TH</code>（thalamus vs area TH）、<code>dSC</code>（deep SC vs tract）、
            <code>pTh</code>（prethalamus）。対応ノードが無い／曖昧なものは broader_parent で止め、無理に exact へ押さない。
          </span>
        </li>
        <li>
          <span class="prio p1">P1</span>
          <b>複合クエリ前処理（cell-type / marker strip）</b><br>
          <span class="note">
            <code>BLA Ppp1r1b</code>、<code>CeA-CRF</code>、<code>NAc-S D1-SPNs</code>、<code>*Glut2</code> は
            解剖 ROI + 分子タグの合成。RCS の仕事は ROI 側。
            クエリ正規化で分子・Cre・SPN 接尾辞を剥がし、残った ROI を検索 → 親/本体へ
            <code>broader_parent</code> を意図的に返す経路を作る（no_match や無関係 exact を減らす）。
          </span>
        </li>
        <li>
          <span class="prio p2">P2</span>
          <b>multi-token phrase の構造化マッチ</b>
          （abbrev wrong 最大バケット ≈ multi_token）。<br>
          <span class="note">
            <code>caudal CP</code>、<code>lateral VTA</code>、<code>spinal interneurons</code> など。
            位置修飾 + 核略語は既に一部対応済み。次は
            （1）残トークンが content のときの部分マッチ強化、
            （2）「interneurons / cells / neurons」を弱語化、
            （3）fullname 展開との二段検索、を評価する。
          </span>
        </li>
        <li>
          <span class="prio p2">P2</span>
          <b>fullname 曖昧性（同名異所）</b> — fullname wrong {len(fw)}、うち高スコア≥0.75 も残存。<br>
          <span class="note">
            典型: <code>paraventricular nucleus</code>（視床 vs 視床下部）、
            <code>arcuate nucleus</code>（延髄 vs 視床下部）。
            abbrev 側は <code>ARC</code> で視床下部を明示できた。fullname 側は
            コーパス種・周辺語・頻度プライア、または「曖昧なら曖昧ラベル」を UI に出す方が、
            誤った exact より価値が高い。
          </span>
        </li>
        <li>
          <span class="prio p2">P2</span>
          <b>broader_parent 上限の扱いをプロダクト方針として固定</b><br>
          <span class="note">
            abbrev broader_parent {by_kind['abbrev'].get('broader_parent', 0)} 件。頻出親は thalamus / striatum / spinal cord / BNST / NAc。
            これは失敗ではなく「HOMBA に文献区画が無い」ことの正しい帰結（DMS 型）。
            KPI では aligned+broader を有用率として並記し、親を無理に細分化しない。
          </span>
        </li>
        <li>
          <span class="prio p3">P3</span>
          <b>評価ハーネス拡張</b><br>
          <span class="note">
            （1）回帰セット固定（今回の showcase + high-conf wrong 上位）、
            （2）neocortex suitable トラックを別タグで回す、
            （3）デプロイ後の本番 API とローカル engine の一致テスト。
          </span>
        </li>
        <li>
          <span class="prio p3">P3</span>
          <b>UI での説明可能性</b><br>
          <span class="note">
            <code>matched_query</code>（文献展開句）と「HOMBA acronym 衝突を抑制した」フラグを WebUI に出し、
            VP→ventral pallidum のような判断をユーザーが検証できるようにする。
          </span>
        </li>
      </ol>
    </section>

    <section>
      <h2>4. やらないこと（過学習ガード）</h2>
      <ul class="note">
        <li>HOMBA acronym の削除・書換えで衝突を消す（今回の方針と矛盾）。</li>
        <li>単発コーパス固有の変則表記だけを exact に押し込むルール乱造。</li>
        <li>オントロジーに無い区画（多くの striatal compartment）への偽ノード捏造。</li>
        <li>判定モデルを毎回変えて「改善したように見せる」こと。審判は Flash×3 固定を継続。</li>
      </ul>
    </section>

    <section>
      <h2>5. 推奨ロードマップ</h2>
      <div class="flow">P0  Deploy engine 0.8.3 (+ abbrev CSV) → smoke on production API
 │
P1  High-conf collision pack (TH/dSC/pTh/…) + cell-type strip normalizer
 │     re-validate tag=round4_* ; require improve>>regress
 │
P2  Multi-token phrase + fullname disambiguation (PVN/ARC family)
 │     track useful_rate = (aligned + broader_parent) / matched
 │
P3  Regression suite + neocortex track + UI matched_query explainability</div>
    </section>

    <section class="grid2">
      <div>
        <h2>高信頼 wrong 例（abbrev, score≥0.75）</h2>
        <p class="note small">P1 の候補プール。対応ノードが明確なものだけ手を付ける。</p>
        <table>
          <thead><tr><th>query</th><th class="num">score</th><th>top1</th><th>corpus fullname</th></tr></thead>
          <tbody>{high_rows}</tbody>
        </table>
      </div>
      <div>
        <h2>abbrev no_match だが fullname は妥当</h2>
        <p class="note small">低リスクの辞書追加候補（{len(nm_good_fn)} 件中の先頭）。</p>
        <table>
          <thead><tr><th>abbrev</th><th>fullname</th><th>fn label</th><th>fn top1</th></tr></thead>
          <tbody>{nm_rows if nm_rows else '<tr><td colspan="4" class="muted">該当少</td></tr>'}</tbody>
        </table>
        <h3>broader_parent 頻出親（abbrev）</h3>
        <table>
          <thead><tr><th>top1</th><th class="num">n</th></tr></thead>
          <tbody>{bp_rows}</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>fullname wrong 例（高スコア順）</h2>
      <table>
        <thead><tr><th>query</th><th>top1</th><th class="num">score</th></tr></thead>
        <tbody>{fw_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>成果物・参照</h2>
      <ul class="note">
        <li>本分析の入力: <code>runs/round3_abbrev/validation_results.csv</code></li>
        <li>差分レポート: <code>runs/round3_abbrev/abbrev_improve_report.html</code></li>
        <li>engine: <code>rcs/rosetta_candidate_generator.py</code> (0.8.3)</li>
        <li>辞書: <code>rcs/homba_abbrev_rules.csv</code></li>
      </ul>
    </section>
  </main>
</body>
</html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
