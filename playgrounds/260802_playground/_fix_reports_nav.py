from pathlib import Path

FILES = [
    "web/frontend/reports/2026-06-25.html",
    "web/frontend/reports/2026-08-02.html",
    "web/frontend/reports/2026-08-02/summary_report.html",
    "web/frontend/reports/2026-08-02/rcs_ai_rerank_article.html",
]

for f in FILES:
    p = Path(f)
    t = p.read_text(encoding="utf-8")
    t = t.replace('href="./2026-08-02.html"', 'href="./2026-08-12.html"')
    t = t.replace('href="../2026-08-02.html"', 'href="../2026-08-12.html"')
    t = t.replace(' aria-current="page">Reports', '>Reports')
    p.write_text(t, encoding="utf-8")
    print("updated", f)
