import json
from collections import Counter

recs = json.load(
    open("playgrounds/260802_playground/runs/ai_eval/records.json", encoding="utf-8")
)
reg = [
    r
    for r in recs
    if r["changed"] and r["off_label"] == "aligned" and r["ai_label"] in ("wrong", "partial_or_narrower")
]
print("aligned->bad:", len(reg))
for r in reg:
    print(f"{r['query']!r:42} off={r['off_name'][:48]!r}")
    print(f"{'':42} ai ={r['ai_name'][:48]!r} rel={r['ai_relation']}")
