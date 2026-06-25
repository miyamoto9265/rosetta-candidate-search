"""Move scoring guide HTML files into web/frontend."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "web" / "frontend"


def nav(active: str) -> str:
    items = [
        ("index.html", "候補検索", "search"),
        ("scoring-guide.html", "スコアリング解説", "guide"),
        ("walkthrough-bla.html", "Walkthrough (BLA)", "walkthrough"),
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


def patch_guide(content: str, active: str) -> str:
    content = content.replace("RCS_SCORING_WALKTHROUGH_BLA.html", "walkthrough-bla.html")
    content = content.replace("RCS_SCORING_GUIDE.html", "scoring-guide.html")
    content = content.replace(
        "  <title>",
        '  <link rel="stylesheet" href="site-nav.css" />\n  <title>',
        1,
    )
    content = content.replace("<body>", "<body>\n" + nav(active), 1)
    return content


def main() -> None:
    sg_src = ROOT / "RCS_SCORING_GUIDE.html"
    wt_src = ROOT / "RCS_SCORING_WALKTHROUGH_BLA.html"

    sg = patch_guide(sg_src.read_text(encoding="utf-8"), "guide")
    (FE / "scoring-guide.html").write_text(sg, encoding="utf-8")

    wt = patch_guide(wt_src.read_text(encoding="utf-8"), "walkthrough")
    wt = re.sub(r'    <a class="nav-back" href="[^"]+">[^<]+</a>\s*\n', "", wt)
    (FE / "walkthrough-bla.html").write_text(wt, encoding="utf-8")

    sg_src.unlink()
    wt_src.unlink()
    print("OK: scoring-guide.html, walkthrough-bla.html")


if __name__ == "__main__":
    main()
