"""Patch guide HTML pages with trust signals (meta, nav, footer)."""
import re
from pathlib import Path

FE = Path(__file__).resolve().parent.parent / "web" / "frontend"

FOOTER = """
    <footer class="site-footer" role="contentinfo">
      <div class="site-footer-inner">
        <h2>ROSETTA Candidate Search</h2>
        <p>Research application for mapping brain-region names to HOMBA ontology entries. Not a login, payment, or credential collection site.</p>
        <nav aria-label="フッターナビゲーション">
          <a href="index.html">候補検索</a>
          <a href="about.html">このサイトについて</a>
          <a href="scoring-guide.html">スコアリング解説</a>
          <a href="walkthrough-bla.html">Walkthrough (BLA)</a>
          <a href="humans.txt">humans.txt</a>
        </nav>
        <p class="disclaimer">
          Official URL: <a href="https://rcs.mymt.site/">https://rcs.mymt.site/</a>
          · Engine v0.3.1 · <a href="about.html#contact">Contact / security</a>
        </p>
      </div>
    </footer>
"""

META = {
    "scoring-guide.html": {
        "title": "ROSETTA Candidate Search — スコアリング解説",
        "desc": "RCS 候補スコアの計算方法・アルゴリズム・パラメータ解説。研究用 HOMBA 候補検索ツールの技術ドキュメント。",
        "canonical": "https://rcs.mymt.site/scoring-guide.html",
        "active": "guide",
    },
    "walkthrough-bla.html": {
        "title": "RCS Walkthrough — Left basolateral amygdala (BLA)",
        "desc": "ROSETTA Candidate Search の処理フロー詳細（BLA クエリ例）。研究用ツールの内部動作ドキュメント。",
        "canonical": "https://rcs.mymt.site/walkthrough-bla.html",
        "active": "walkthrough",
    },
}


def nav(active: str) -> str:
    items = [
        ("index.html", "候補検索", "search"),
        ("scoring-guide.html", "スコアリング解説", "guide"),
        ("walkthrough-bla.html", "Walkthrough (BLA)", "walkthrough"),
        ("about.html", "このサイトについて", "about"),
    ]
    links = []
    for href, label, key in items:
        cur = ' aria-current="page"' if key == active else ""
        links.append(f'      <a href="{href}"{cur}>{label}</a>')
    return (
        '  <header class="site-nav">\n'
        '    <div class="site-nav-inner">\n'
        '      <a href="index.html" class="site-brand">ROSETTA Candidate Search</a>\n'
        '      <nav class="site-nav-links" aria-label="サイトメニュー">\n'
        + "\n".join(links)
        + "\n      </nav>\n"
        "    </div>\n"
        "  </header>\n"
    )


def head_block(info: dict) -> str:
    return f"""  <meta name="description" content="{info['desc']}" />
  <meta name="author" content="ROSETTA Candidate Search" />
  <meta name="robots" content="index, follow" />
  <link rel="canonical" href="{info['canonical']}" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="{info['title']}" />
  <meta property="og:description" content="{info['desc']}" />
  <meta property="og:url" content="{info['canonical']}" />
  <meta property="og:locale" content="ja_JP" />
  <meta property="og:site_name" content="ROSETTA Candidate Search" />
  <link rel="stylesheet" href="site-trust.css" />
"""


def patch_file(name: str) -> None:
    path = FE / name
    content = path.read_text(encoding="utf-8")
    info = META[name]

    # Replace nav block
    content = re.sub(
        r"  <header class=\"site-nav\">.*?</header>\n",
        nav(info["active"]),
        content,
        count=1,
        flags=re.DOTALL,
    )

    # Insert meta after viewport if not present
    if "name=\"description\"" not in content:
        content = content.replace(
            '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
            '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
            + head_block(info),
            1,
        )
    elif "site-trust.css" not in content:
        content = content.replace(
            '  <link rel="stylesheet" href="site-nav.css" />',
            '  <link rel="stylesheet" href="site-nav.css" />\n  <link rel="stylesheet" href="site-trust.css" />',
            1,
        )

    # Trust notice after body layout opens (scoring guide) or after hero query-input
    trust = """
      <div class="trust-notice" role="note">
        <strong>研究用ドキュメント</strong>
        ROSETTA Candidate Search（<a href="about.html">公式サイト</a>）の技術解説です。
        パスワード・決済情報の入力はありません。
      </div>
"""
    if "class=\"trust-notice\"" not in content:
        if name == "scoring-guide.html":
            content = content.replace(
                '    <div class="meta-bar">',
                trust + "\n    <div class=\"meta-bar\">",
                1,
            )
        else:
            content = content.replace(
                '    <div class="meta-bar">',
                trust + "\n    <div class=\"meta-bar\">",
                1,
            )

    # Replace old footer
    content = re.sub(
        r"\n    <footer>.*?</footer>\n  </div>\n</body>",
        FOOTER + "\n  </div>\n</body>",
        content,
        count=1,
        flags=re.DOTALL,
    )

    # Update title tag
    content = re.sub(
        r"<title>.*?</title>",
        f"<title>{info['title']}</title>",
        content,
        count=1,
    )

    path.write_text(content, encoding="utf-8")
    print(f"Patched {name}")


def main() -> None:
    patch_file("scoring-guide.html")
    patch_file("walkthrough-bla.html")


if __name__ == "__main__":
    main()
