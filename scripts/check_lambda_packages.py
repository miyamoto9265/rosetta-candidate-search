#!/usr/bin/env python3
"""Invoke the built Lambda packages offline (no AWS credentials, no AI).

Usage:
  python scripts/check_lambda_packages.py main   # dist/package      (rcs-api / rcs-mcp)
  python scripts/check_lambda_packages.py ebl    # dist/package_ebl  (rcs-ebl-api)

Run it with the Lambda runtime's Python (package_lambda.sh builds the caches there):
  docker run --rm --entrypoint python -v "$PWD:/repo" -w /repo \
    public.ecr.aws/lambda/python:3.14 scripts/check_lambda_packages.py main
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGES = {"main": REPO_ROOT / "dist" / "package", "ebl": REPO_ROOT / "dist" / "package_ebl"}

for name in list(os.environ):
    if name.startswith(("DEEPSEEK_", "MCP_BEARER_", "AWS_ACCESS", "AWS_SECRET", "AWS_SESSION")):
        del os.environ[name]
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")
os.environ.setdefault("ALLOWED_ORIGIN", "https://rcs.cobrac.site")


def _event(body: object, method: str = "POST", headers: dict[str, str] | None = None) -> dict:
    return {
        "requestContext": {"http": {"method": method}},
        "headers": headers or {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{'PASS' if ok else 'FAIL'} {label}{f' ({detail})' if detail else ''}")
    return ok


def check_main(pkg: Path) -> bool:
    import lambda_function
    import mcp_function

    started = time.perf_counter()
    loaded = lambda_function._load_from_cache(pkg / "rcs" / "generator_cache.pkl")
    ok = _check("rcs generator cache loads", loaded is not None, f"{time.perf_counter() - started:.2f}s")

    res = lambda_function.lambda_handler(
        _event({"query": "Pulvinar nucleus", "top_k": 3,
                "use_ai_preprocess": False, "use_ai_postprocess": False}),
        None,
    )
    body = json.loads(res["body"])
    top = (body.get("candidates") or [{}])[0].get("homba_id")
    ok &= _check("rcs-api /candidates", res["statusCode"] == 200 and top == "HOMBA:10409", f"top={top}")

    res = mcp_function.lambda_handler(_event({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), None)
    ok &= _check("rcs-mcp without token -> 401", res["statusCode"] == 401, f"status={res['statusCode']}")

    os.environ["MCP_BEARER_TOKENS"] = "offline-check-token"
    auth = {"content-type": "application/json", "authorization": "Bearer offline-check-token"}
    res = mcp_function.lambda_handler(
        _event({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=auth), None
    )
    tools = [t["name"] for t in json.loads(res["body"])["result"]["tools"]] if res["statusCode"] == 200 else []
    ok &= _check("rcs-mcp tools/list", len(tools) == 4, ",".join(tools))

    res = mcp_function.lambda_handler(
        _event(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "search_bna_candidates", "arguments": {"query": "left DLPFC", "top_k": 3}}},
            headers=auth,
        ),
        None,
    )
    text = json.dumps(json.loads(res["body"]).get("result", {})) if res["statusCode"] == 200 else ""
    ok &= _check("rcs-mcp search_bna_candidates", "A8vl" in text, f"status={res['statusCode']}")

    def call(rpc_id: int, name: str, arguments: dict) -> dict:
        res = mcp_function.lambda_handler(
            _event({"jsonrpc": "2.0", "id": rpc_id, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}}, headers=auth),
            None,
        )
        if res["statusCode"] != 200:
            return {}
        content = json.loads(res["body"]).get("result", {}).get("content") or [{}]
        return json.loads(content[0].get("text") or "{}")

    atlases = {hid: (call(10 + i, "get_homba_term", {"homba_id": hid}).get("sabra") or {}).get("atlas")
               for i, hid in enumerate(("HOMBA:10339", "HOMBA:10297", "HOMBA:10317", "HOMBA:10172"))}
    expected = {"HOMBA:10339": "DHBA", "HOMBA:10297": "DHBA", "HOMBA:10317": "DHBA", "HOMBA:10172": "BNA"}
    ok &= _check("rcs-mcp get_homba_term SABRA boundary (neocortex = BNA)", atlases == expected, json.dumps(atlases))
    definition = call(20, "get_sabra_definition", {})
    ok &= _check("rcs-mcp get_sabra_definition boundary_version",
                 definition.get("boundary_version") == "2026-10-04", str(definition.get("boundary_version")))
    return ok


def check_ebl(pkg: Path) -> bool:
    import lambda_function

    started = time.perf_counter()
    loaded = lambda_function._load_from_cache()
    ok = _check("rcs_ebl generator cache loads", loaded is not None, f"{time.perf_counter() - started:.2f}s")

    res = lambda_function.lambda_handler(_event({"query": "left DLPFC", "top_k": 3}), None)
    body = json.loads(res["body"])
    abbrs = [c.get("bna_area_abbr") for c in body.get("candidates") or []]
    ok &= _check("rcs-ebl-api /candidates-ebl", res["statusCode"] == 200 and "A8vl" in abbrs, ",".join(map(str, abbrs)))
    return ok


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in PACKAGES:
        print(__doc__, file=sys.stderr)
        return 2
    kind = sys.argv[1]
    pkg = PACKAGES[kind]
    if not pkg.is_dir():
        print(f"Missing {pkg}. Run scripts/package_lambda{'_ebl' if kind == 'ebl' else ''}.sh first.", file=sys.stderr)
        return 2
    # Import only from the package so missing files in the zip surface here.
    sys.path[:] = [str(pkg)] + [p for p in sys.path[1:] if not p.startswith(str(REPO_ROOT))]
    os.chdir(pkg)
    ok = check_main(pkg) if kind == "main" else check_ebl(pkg)
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
