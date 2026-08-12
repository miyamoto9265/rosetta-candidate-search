import json
import os
import sys
import types
from pathlib import Path

os.environ["DEEPSEEK_API_KEY"] = "sk-6b1e8f27bd684ca08dec0523f0856317"
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "web" / "backend"))
sys.path.insert(0, str(REPO))
boto3 = types.ModuleType("boto3")
boto3.client = lambda *a, **k: None
sys.modules["boto3"] = boto3

import lambda_function as lf
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

RCS = REPO / "rcs"
lf.GENERATOR = RosettaCandidateGenerator(
    RCS / "HOMBA_v1_fixed.csv",
    token_rules_csv=RCS / "homba_token_rules.csv",
    alias_rules_csv=RCS / "homba_alias_rules.csv",
    abbrev_rules_csv=RCS / "homba_abbrev_rules.csv",
)

QUERIES = ["CN", "PP", "PV", "ANT", "AHA", "PTN", "PHN", "SO", "BLA"]
for q in QUERIES:
    r = lf.lambda_handler({"body": json.dumps({"query": q})}, None)
    d = json.loads(r["body"])
    ai = (d.get("ai") or {}).get("results") or []
    best = ai[0] if ai else {}
    print(f"{q:5} -> {best.get('homba_id', '(none)'):16} {best.get('name', '')[:55]}")
