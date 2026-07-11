#!/usr/bin/env python3
"""Generate the two analysis HTML reports from unresolved_classified.csv.

Outputs
-------
improvement_proposals.html : algorithm + dictionary improvement proposals.
homba_expansion.html       : HOMBA ontology expansion proposals (separate, as
                             these inputs have no matching granularity in HOMBA).
"""
from __future__ import annotations

import csv
import html
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "unresolved_classified.csv"


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def load() -> list[dict]:
    return list(csv.DictReader(SRC.open(encoding="utf-8")))


def rows_for(rows, mech=None, cat=None):
    out = rows
    if cat:
        out = [r for r in out if r["_category"] == cat]
    if mech:
        out = [r for r in out if r["_mechanism"] == mech]
    return out


def fnum(x: str) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# table renderers
# ---------------------------------------------------------------------------

def tbl_wrong(rows) -> str:
    head = ("<table><thead><tr><th>クエリ (入力)</th><th>RCS 現在の top-1（誤）</th>"
            "<th>マッチ根拠</th><th class='num'>score</th>"
            "<th>rank2（しばしば正解寄り）</th></tr></thead><tbody>")
    body = []
    for r in sorted(rows, key=lambda r: (r["dataset"], fnum(r["score"]))):
        basis = r["matched_alias"] or r["matched_query"]
        if r["modifier_terms"]:
            basis += f" <span class='mono' style='color:#7c3aed'>[mod: {esc(r['modifier_terms'])}]</span>"
        body.append(
            f"<tr><td><strong>{esc(r['query'])}</strong> <span class='ds'>{esc(r['dataset'][:3])}</span></td>"
            f"<td>{esc(r['top_name'])}</td>"
            f"<td class='mono'>{basis}</td>"
            f"<td class='num'>{fnum(r['score']):.2f}</td>"
            f"<td>{esc(r['rank2_name'])}</td></tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def tbl_hier(rows) -> str:
    head = ("<table><thead><tr><th>クエリ (入力)</th><th>top-1（過剰昇格された親）</th>"
            "<th class='num'>score</th><th>rank2（正しい sibling）</th>"
            "<th class='num'>rank2</th></tr></thead><tbody>")
    body = []
    for r in sorted(rows, key=lambda r: (r["dataset"], fnum(r["score"]))):
        body.append(
            f"<tr><td><strong>{esc(r['query'])}</strong> <span class='ds'>{esc(r['dataset'][:3])}</span></td>"
            f"<td>{esc(r['top_name'])}</td>"
            f"<td class='num'>{fnum(r['score']):.2f}</td>"
            f"<td>{esc(r['rank2_name'])}</td>"
            f"<td class='num'>{fnum(r['rank2_score']):.2f}</td></tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def tbl_dict(rows) -> str:
    head = ("<table><thead><tr><th>クエリ (入力)</th><th>RCS 現在の top-1</th>"
            "<th>辞書追加の方針（HOMBA 実在確認済み）</th></tr></thead><tbody>")
    body = []
    for r in sorted(rows, key=lambda r: r["query"].lower()):
        body.append(
            f"<tr><td><strong>{esc(r['query'])}</strong> <span class='ds'>{esc(r['dataset'][:3])}</span></td>"
            f"<td>{esc(r['top_name'])}</td>"
            f"<td>{esc(r['_mechanism'])}</td></tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def tbl_eff(rows, n=14) -> str:
    head = ("<table><thead><tr><th>クエリ (入力)</th><th>RCS top-1（実質正解）</th>"
            "<th class='num'>score</th><th>flag</th></tr></thead><tbody>")
    body = []
    sample = sorted(rows, key=lambda r: -fnum(r["score"]))[:n]
    for r in sample:
        body.append(
            f"<tr><td>{esc(r['query'])} <span class='ds'>{esc(r['dataset'][:3])}</span></td>"
            f"<td>{esc(r['top_name'])}</td>"
            f"<td class='num'>{fnum(r['score']):.2f}</td>"
            f"<td><span class='badge {flag_cls(r['review_flag'])}'>{esc(r['review_flag'])}</span></td></tr>"
        )
    return head + "".join(body) + "</tbody></table>"


def flag_cls(flag: str) -> str:
    return {"high_confidence": "high", "needs_review": "review",
            "low_confidence": "low", "modifier_conflict": "mod"}.get(flag, "review")


def tbl_simple(rows) -> str:
    head = ("<table><thead><tr><th>クエリ (入力)</th><th class='ds'>set</th>"
            "<th>RCS top-1 (親フォールバック)</th></tr></thead><tbody>")
    body = []
    for r in sorted(rows, key=lambda r: r["query"].lower()):
        body.append(
            f"<tr><td><strong>{esc(r['query'])}</strong></td>"
            f"<td class='ds'>{esc(r['dataset'][:3])}</td>"
            f"<td>{esc(r['top_name'])}</td></tr>"
        )
    return head + "".join(body) + "</tbody></table>"


CSS = "report.css"

HEAD = """<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="description" content="{desc}" />
  <title>{title}</title>
  <link rel="stylesheet" href="report.css" />
  <style>
    .ds {{ font-size:.7rem; color:var(--muted); background:#eef2f7; padding:.05rem .3rem;
           border-radius:4px; vertical-align:middle; }}
    .toplinks {{ display:flex; gap:.6rem; flex-wrap:wrap; margin-top:1rem; }}
    .toplinks a {{ background:rgba(255,255,255,.16); color:#fff; text-decoration:none;
                   padding:.35rem .7rem; border-radius:8px; font-size:.85rem; }}
    .toplinks a.active {{ background:#fff; color:var(--accent-dark); font-weight:700; }}
    table {{ table-layout:fixed; }} td, th {{ overflow-wrap:anywhere; }}
  </style>
</head>
<body>
  <div class="page">
"""

FOOT = """      <footer>
        ROSETTA Candidate Search · build_testdata/260621_playground/improvement_01 ·
        生成元: <code>gen_reports.py</code>（<code>unresolved_classified.csv</code> 由来）
      </footer>
    </main>
  </div>
</body>
</html>
"""


def build_improvement(rows) -> str:
    A = rows_for(rows, cat="A_effectively_correct")
    B = rows_for(rows, cat="B_algo")
    C = rows_for(rows, cat="C_dict")
    D = rows_for(rows, cat="D_homba_gap")
    E = rows_for(rows, cat="E_source_typo")
    weak = rows_for(rows, mech="weak/lone-token fuzzy trap")
    hier = rows_for(rows, mech="hierarchy_parent over-promotion")
    wrong = rows_for(rows, mech="wrong top-1 (better candidate exists)")
    total = len(rows)

    sidebar = """    <aside class="sidebar">
      <h2>目次</h2>
      <nav>
        <a href="#summary">サマリー</a>
        <a href="#method">1. 分類方法</a>
        <a href="#effective">2. 実質正解（除外）</a>
        <a href="#algo">3. アルゴリズム改善案</a>
        <a href="#dict">4. 辞書改善案</a>
        <a href="#priority">5. 優先度・次アクション</a>
      </nav>
      <h2 style="margin-top:1rem">関連</h2>
      <nav>
        <a href="homba_expansion.html">HOMBA 拡張案 →</a>
        <a href="index.html">辞書改善ループ報告</a>
      </nav>
    </aside>
"""

    hero = f"""    <main class="main">
      <header class="hero">
        <p class="eyebrow">ROSETTA Candidate Search · Playground · Analysis</p>
        <h1>未解決レコード分析<br />アルゴリズム改善案 / 辞書改善案</h1>
        <p class="meta">
          対象: <code>unresolved_round3.csv</code>（{total} 件 = corpus 204 + species 294）·
          round3 で <code>high_confidence</code> に届かなかった全入力を目視確認。
        </p>
        <div class="toplinks">
          <a class="active" href="improvement_proposals.html">① アルゴリズム / 辞書改善案</a>
          <a href="homba_expansion.html">② HOMBA オントロジー拡張案</a>
        </div>
      </header>
"""

    summary = f"""      <section id="summary">
        <h2>サマリー</h2>
        <p>
          未解決 {total} 件を目視で 5 区分に分類。<strong>約 6 割（{len(A)} 件）は実質的に正解</strong>
          （rank1 が正しいエントリまたは妥当な親）で、低スコアは <code>review_flag</code> の閾値由来の
          見かけ上のもの。RCS 側で実際に手を入れる価値があるのは
          <strong>アルゴリズム {len(B)} 件 + 辞書 {len(C)} 件 = {len(B)+len(C)} 件（全体の {100*(len(B)+len(C))/total:.0f}%）</strong>。
          残り {len(D)} 件は HOMBA に粒度が無く、<a href="homba_expansion.html">別レポート</a>で扱う。
        </p>
        <div class="summary-grid">
          <div class="stat-card"><div class="label">実質正解（除外）</div>
            <div class="value">{len(A)}</div><div class="delta">{100*len(A)/total:.1f}%</div></div>
          <div class="stat-card"><div class="label">アルゴリズム改善</div>
            <div class="value" style="color:var(--danger)">{len(B)}</div><div class="delta" style="color:var(--danger)">要ロジック修正</div></div>
          <div class="stat-card"><div class="label">辞書追加で解決</div>
            <div class="value" style="color:var(--warning)">{len(C)}</div><div class="delta" style="color:var(--warning)">同義語・綴り・語順</div></div>
          <div class="stat-card"><div class="label">HOMBA 拡張（別報告）</div>
            <div class="value" style="color:var(--muted)">{len(D)}</div><div class="delta" style="color:var(--muted)">{100*len(D)/total:.1f}%</div></div>
          <div class="stat-card"><div class="label">ソース転記ミス</div>
            <div class="value" style="color:var(--muted)">{len(E)}</div><div class="delta" style="color:var(--muted)">データ側修正</div></div>
        </div>
        <div class="callout info">
          <strong>読み方:</strong> <code>review_flag</code> はスコア閾値（high≥0.90 / needs 0.60–0.90 / low&lt;0.60 /
          modifier_conflict）であり、正誤判定ではない。本分析は確立済みの参照ラベルが無いため、
          各 top-1 の解剖学的妥当性を目視で判断した。区分ごとの全件は <code>output/cat_*.csv</code> に出力済み。
        </div>
      </section>
"""

    method = """      <section id="method">
        <h2>1. 分類方法</h2>
        <ul>
          <li><strong>A 実質正解</strong> — top-1 が正しいエントリ、または HOMBA に亜区が無いための妥当な親フォールバック。問題リストから除外。</li>
          <li><strong>B アルゴリズム改善</strong> — HOMBA により良い候補が実在するのに、スコア/マッチ規則の都合で誤った top-1 を返す。</li>
          <li><strong>C 辞書追加</strong> — 正解エントリが実在し、綴り・語順・同義語ギャップのみが原因（<code>verify.py</code> で実在確認済み）。</li>
          <li><strong>D HOMBA 粒度ギャップ</strong> — 該当概念が HOMBA に無い → 拡張レポートへ。</li>
          <li><strong>E ソース転記ミス</strong> — 入力文字列自体がデータセット側の誤記。</li>
        </ul>
        <div class="callout warn">
          分類は <code>classify.py</code>（ルール + 目視オーバーライド集合）で再現可能。判断が割れうる
          「妥当な親」境界例は A に寄せ、確実に改善余地があるものだけ B/C に計上した（保守的）。
        </div>
      </section>
"""

    effective = f"""      <section id="effective">
        <h2>2. 実質正解（{len(A)} 件 / 除外推奨）</h2>
        <p>内訳: exact 完全一致で亜区のみ欠落 63 ／ modifier を外して正しい親 33 ／ 同義語・親マッチ 175 ／ 低スコアだが rank1 正解 31。</p>
        <div class="callout ok">
          これらは <strong>誤りではない</strong>。<code>needs_review</code>/<code>modifier_conflict</code> のまま運用レビューに回すのが妥当で、
          辞書やロジックで無理に <code>high</code> に上げる必要はない（旧ハックの轍を踏まない）。
        </div>
        <h3>例（スコア上位の実質正解）</h3>
        {tbl_eff(A)}
      </section>
"""

    algo = f"""      <section id="algo">
        <h2>3. アルゴリズム改善案（{len(B)} 件）</h2>

        <div class="issue-card">
          <h4>3-1. 弱トークン単独マッチの fuzzy トラップ（{len(weak)} 件）</h4>
          <p>
            <code>ventral</code> / <code>posterior</code> / <code>medial</code> など laterality・weak 語が
            <em>唯一のマッチ根拠</em>になり、無関係なエントリ（例: <code>anterior (ventral) spinal artery</code>）へ高スコアで誤着弾。
          </p>
          {tbl_wrong(weak)}
          <p><strong>提案:</strong>
            matched_alias/matched_query が laterality・weak・modifier 語<em>のみ</em>で構成される場合は
            その候補のスコアを強く減点（または候補から除外）。実装は <code>homba_token_rules.csv</code> の
            <code>laterality</code>/<code>weak</code> 種別を「単独では content token として無効」とするガードを
            スコアリングに追加。
          </p>
        </div>

        <div class="issue-card">
          <h4>3-2. hierarchy_parent の過剰昇格（{len(hier)} 件）</h4>
          <p>
            親昇格ボーナス（+0.08）が、<strong>直接マッチした正しい sibling</strong> を僅差で逆転してしまう。
            下表は rank2 に正解相当が来ているのに親が top-1 を取った例。
          </p>
          {tbl_hier(hier)}
          <p><strong>提案:</strong>
            ① 親昇格スコアは「同点候補内の最良 sibling の直接マッチスコアを超えない」上限を設ける。
            ② <code>ventrolateral / ventromedial / mediodorsal / laterodorsal</code> など融合形の語は
            分離形（<code>ventral lateral</code> 等）へ正規化（→ 辞書側 4-1 と連動）し、sibling 直接マッチを成立させる。
          </p>
        </div>

        <div class="issue-card">
          <h4>3-3. その他の誤 top-1（{len(wrong)} 件）</h4>
          <p>より良い候補が HOMBA に実在するが、現行スコアで取りこぼしているもの。個別性が高く、3-1/3-2 の修正＋スコア下限で大半が改善見込み。</p>
          {tbl_wrong(wrong)}
        </div>

        <div class="issue-card">
          <h4>3-4. 完全一致なのにスコアが沈む（スコア下限の検討）</h4>
          <p>
            <code>Uncus → uncus of (para)hippocampal gyrus</code> は alias 完全一致なのに
            <code>bm25</code> 単独で <strong>0.22</strong>。長い HOMBA 名に対し短いクエリの BM25 正規化が過剰に効くため。
            <strong>提案:</strong> alias/exact 完全包含が成立した候補にはスコア下限（例 0.70）を保証し、
            BM25 はランキング内の微調整に留める。
          </p>
        </div>
      </section>
"""

    dictsec = f"""      <section id="dict">
        <h2>4. 辞書改善案（{len(C)} 件）</h2>
        <p>いずれも正解エントリが HOMBA に実在。<code>playground_alias_rules.csv</code> への追記候補。</p>
        {tbl_dict(C)}
        <h3>4-1. 一般化価値の高いルール（最優先）</h3>
        <div class="callout info">
          <strong>融合形 ↔ 分離形（視床核で頻出）:</strong>
          <code>mediodorsal ↔ medial dorsal</code>, <code>laterodorsal ↔ lateral dorsal</code>,
          <code>ventrolateral ↔ ventral lateral</code>, <code>ventromedial ↔ ventral medial</code>。
          HOMBA は視床核を分離形で命名しており、1 ルールで複数入力を救済できる（3-2 とも連動）。
        </div>
        <h3>4-2. スペル・語順の個別同義語</h3>
        <p class="mono">
          Kolliker → Koelliker ／ sagulum (Saginum) ／ septofimbrial (Septimbrial) ／
          lemniscus (Leminscus) ／ chiasma → chiasm ／ intergeniculate leaflet → leaf ／
          stria medullaris thalami → stria medullaris of thalamus ／ locus coeruleus region → nucleus coeruleus
        </p>
        <div class="callout warn">
          <strong>E. ソース転記ミス（{len(E)} 件・辞書化しない）:</strong>
          <code>Antherior</code> / <code>Mircrocellular</code> / <code>Vestibulochoclear</code> /
          <code>Emminence</code> / <code>Occulomotor</code> はデータセット側で修正すべき。
          本体辞書に誤記を取り込むと汚染源になるため除外。
        </div>
      </section>
"""

    priority = f"""      <section id="priority">
        <h2>5. 優先度・次アクション</h2>
        <table>
          <thead><tr><th>優先</th><th>施策</th><th class="num">影響</th><th>種別</th></tr></thead>
          <tbody>
            <tr><td><strong>高</strong></td><td>弱トークン単独マッチのガード（3-1）</td><td class="num">~{len(weak)}+</td><td>アルゴリズム</td></tr>
            <tr><td><strong>高</strong></td><td>親昇格の上限化（3-2）＋融合形正規化（4-1）</td><td class="num">~{len(hier)}+</td><td>アルゴ＋辞書</td></tr>
            <tr><td>中</td><td>完全一致のスコア下限保証（3-4）</td><td class="num">複数</td><td>アルゴリズム</td></tr>
            <tr><td>中</td><td>個別同義語・スペル辞書追加（4-2）</td><td class="num">~{len(C)}</td><td>辞書</td></tr>
            <tr><td>低</td><td>ソース転記ミスの起票（E）</td><td class="num">{len(E)}</td><td>データ</td></tr>
          </tbody>
        </table>
        <div class="callout ok">
          辞書（C/4-1）は本 playground で検証後にマージ判断。アルゴリズム（B）は <code>rcs/</code> 本体の
          スコアリング変更を伴うため、回帰テスト（baseline 比較で high からの降格 0 を維持）を通してから適用。
        </div>
      </section>
"""

    return (HEAD.format(desc="RCS 未解決レコードのアルゴリズム/辞書改善案",
                        title="RCS 改善案 — アルゴリズム / 辞書")
            + sidebar + hero + summary + method + effective + algo + dictsec + priority + FOOT)


def build_expansion(rows) -> str:
    D = rows_for(rows, cat="D_homba_gap")
    total = len(rows)

    fams = [
        ("HCP-MMP / Glasser 2016 微細皮質野",
         re.compile(r"\barea\s+([A-Z0-9]|\d)", re.I),
         "ヒト皮質を 180 野に分割する HCP-MMP。HOMBA は葉・回・一部の細分まで。"
         "<code>area 55b</code>, <code>Visual area V3/V6/V7</code>, <code>Somatosensory area 1/2</code> は実在し正答するが、"
         "<code>Prefrontal area 8Av</code>, <code>Parietal area PGi</code>, <code>Temporal area TE1a</code>, "
         "<code>Visual area V3A/V4/V8</code> 等の多くは親止まり。"),
        ("カテコールアミン細胞群 (A1–A13)",
         re.compile(r"cell group", re.I),
         "HOMBA には <code>A8 dopamine cell group</code> 等の一部のみ。"
         "<code>A1/A4/A5 catecholaminergic</code>, <code>A11/A13 dopamine</code> は未収載で A8 に誤着。"),
        ("個別小脳小葉 (vermis / intermediate)",
         re.compile(r"cerebellar lobule", re.I),
         "HOMBA は <code>cerebellar vermis</code> / <code>cerebellar morphology</code> 粒度。"
         "<code>Lobule 1–10 Vermis/Intermediate</code> の個別小葉が無い。"),
        ("皮質層 (cortical layer)",
         re.compile(r"piriform cortex,\s*layer", re.I),
         "<code>Piriform cortex, layer 1/2/3</code>。HOMBA は層構造を一部領域でしか持たない。"),
        ("齧歯類固有の領域",
         re.compile(r"(barrel field|representation|frontal association|dysgranular zone)", re.I),
         "<code>barrel field</code>, <code>fore/hindlimb/trunk/face representation</code>, "
         "<code>frontal association</code>。ヒト中心の HOMBA とスコープ不一致。"),
        ("末梢・感覚器官",
         re.compile(r"(cochlea|spiral ganglion|vestibular apparatus)", re.I),
         "<code>Cochlea</code>, <code>Spiral ganglion</code>, <code>Vestibular apparatus</code>。"
         "HOMBA は中枢神経系が対象。中枢の核（cochlear nuclei 等）に誤着。"),
    ]

    assigned = set()
    sections = []
    counted = 0
    for name, pat, note in fams:
        members = [r for r in D if pat.search(r["query"]) and r["query"] not in assigned]
        for r in members:
            assigned.add(r["query"])
        counted += len(members)
        sections.append((name, note, members))
    rest = [r for r in D if r["query"] not in assigned]

    sidebar_links = "\n".join(
        f'        <a href="#fam{i}">{esc(name)} ({len(members)})</a>'
        for i, (name, _n, members) in enumerate(sections))

    sidebar = f"""    <aside class="sidebar">
      <h2>目次</h2>
      <nav>
        <a href="#summary">サマリー</a>
{sidebar_links}
        <a href="#famX">その他 ({len(rest)})</a>
        <a href="#policy">拡張の考え方</a>
      </nav>
      <h2 style="margin-top:1rem">関連</h2>
      <nav>
        <a href="improvement_proposals.html">← アルゴリズム/辞書改善案</a>
        <a href="index.html">辞書改善ループ報告</a>
      </nav>
    </aside>
"""

    hero = f"""    <main class="main">
      <header class="hero">
        <p class="eyebrow">ROSETTA Candidate Search · Playground · Ontology</p>
        <h1>HOMBA オントロジー拡張案<br />粒度ギャップ {len(D)} 件</h1>
        <p class="meta">
          <code>unresolved_round3.csv</code>（{total} 件）のうち、HOMBA に該当粒度が<strong>存在しない</strong>入力。
          辞書・アルゴリズムでは解決不可で、現状は正しい親へのフォールバックが最善。
        </p>
        <div class="toplinks">
          <a href="improvement_proposals.html">① アルゴリズム / 辞書改善案</a>
          <a class="active" href="homba_expansion.html">② HOMBA オントロジー拡張案</a>
        </div>
      </header>
"""

    summary = f"""      <section id="summary">
        <h2>サマリー</h2>
        <p>
          未解決 {total} 件のうち <strong>{len(D)} 件（{100*len(D)/total:.1f}%）</strong>は、
          入力の標準名が HOMBA に存在しないことが原因。これらは RCS の不具合ではなく
          <strong>オントロジー側のカバレッジ課題</strong>であり、別管理とする。
        </p>
        <div class="summary-grid">
          {''.join(f'''<div class="stat-card"><div class="label">{esc(name)}</div>
            <div class="value">{len(members)}</div></div>''' for name, _n, members in sections)}
          <div class="stat-card"><div class="label">その他</div><div class="value">{len(rest)}</div></div>
        </div>
        <div class="callout warn">
          <strong>注意:</strong> HOMBA はヒト中心の中枢神経オントロジー。齧歯類固有領域・末梢器官の追加は
          スコープ判断が必要で、無条件追加は推奨しない。代替として「外部語彙 → HOMBA 親」への
          公式マッピング表を別途持つ選択肢もある。
        </div>
      </section>
"""

    fam_sections = []
    for i, (name, note, members) in enumerate(sections):
        fam_sections.append(f"""      <section id="fam{i}">
        <h2>{esc(name)}（{len(members)} 件）</h2>
        <p>{note}</p>
        {tbl_simple(members)}
      </section>
""")

    rest_section = f"""      <section id="famX">
        <h2>その他の粒度ギャップ（{len(rest)} 件）</h2>
        {tbl_simple(rest)}
      </section>
"""

    policy = """      <section id="policy">
        <h2>拡張の考え方（提案）</h2>
        <ol>
          <li><strong>スコープ判断を先に。</strong> ヒト皮質の微細野（HCP-MMP）は HOMBA 本来の対象に近く、
              追加価値が高い。末梢・齧歯類固有はスコープ外の可能性が高く、マッピング表で吸収する方が安全。</li>
          <li><strong>親子関係を保って追加。</strong> 例: HCP-MMP 野は対応する葉/回の子として登録し、
              acronym（V3A, PGi, 8Av…）を alias に持たせる。</li>
          <li><strong>層・細胞群は系統的に。</strong> cortical layer / catecholamine cell group は
              個別 1 件ずつでなく、命名規約を決めて一括設計する。</li>
          <li><strong>追加後は RCS で再評価。</strong> 追加エントリにより親フォールバックが直接マッチへ昇格し、
              <code>needs_review/low</code> が <code>high</code> 化することを <code>rcs_eval.py</code> で確認。</li>
        </ol>
        <div class="callout info">
          本レポートの対象は「正しい親に落ちているだけで意味的破綻はしていない」群。
          意味的に誤っている（弱トークン誤着等）の修正は
          <a href="improvement_proposals.html">アルゴリズム/辞書改善案</a>側で扱う。
        </div>
      </section>
"""

    return (HEAD.format(desc="HOMBA オントロジー拡張案（粒度ギャップ）",
                        title="HOMBA オントロジー拡張案")
            + sidebar + hero + summary + "".join(fam_sections) + rest_section + policy + FOOT)


def main() -> None:
    rows = load()
    (HERE / "improvement_proposals.html").write_text(build_improvement(rows), encoding="utf-8")
    (HERE / "homba_expansion.html").write_text(build_expansion(rows), encoding="utf-8")
    print("wrote improvement_proposals.html and homba_expansion.html")


if __name__ == "__main__":
    main()
