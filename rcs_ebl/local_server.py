#!/usr/bin/env python3
"""Local HTTP server for RCS_EBL (API + static frontend).

Usage:
  python rcs_ebl/local_server.py
  # API:  http://127.0.0.1:8787/candidates
  # UI:   http://127.0.0.1:8787/
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import ENGINE_VERSION as RCS_ENGINE_VERSION  # noqa: E402
from rcs_ebl import ENGINE_VERSION  # noqa: E402
from rcs_ebl.ebl_candidate_generator import EblCandidateGenerator  # noqa: E402

DEFAULT_FRONTEND = REPO_ROOT / "web" / "frontend" / "ebl"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

GENERATOR: EblCandidateGenerator | None = None
FRONTEND_DIR = DEFAULT_FRONTEND


def get_generator() -> EblCandidateGenerator:
    global GENERATOR
    if GENERATOR is None:
        GENERATOR = EblCandidateGenerator()
    return GENERATOR


def _bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def handle_candidates(payload: dict) -> tuple[int, dict]:
    query = str(payload.get("query", "")).strip()
    if not query:
        return 400, {"error": "query is required"}

    top_k = int(payload.get("top_k", 10))
    top_k = max(1, min(top_k, 30))
    level = str(payload.get("level", "l3")).strip().lower()
    if level not in ("l3", "l2"):
        level = "l3"
    name_top_k = int(payload.get("name_top_k", 5))
    name_top_k = max(1, min(name_top_k, 15))

    candidates = get_generator().generate(
        query, top_k=top_k, name_top_k=name_top_k, level=level
    )
    body = {
        "query": query,
        "context": str(payload.get("context", "")).strip(),
        "top_k": top_k,
        "level": level,
        "use_ai_preprocess": False,
        "use_ai_postprocess": False,
        "candidates": candidates,
        "meta": {
            "rcs_ebl_version": ENGINE_VERSION,
            "base_rcs_version": RCS_ENGINE_VERSION,
            "engine": "RCS_EBL",
        },
    }
    return 200, body


class Handler(BaseHTTPRequestHandler):
    server_version = "RCS_EBLLocal/0.1"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "OPTIONS,POST,GET")
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "OPTIONS,POST,GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path not in ("/candidates", "/candidates-ebl"):
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON object required"})
            return
        try:
            status, body = handle_candidates(payload)
        except Exception as exc:  # noqa: BLE001 — local test server
            self._send_json(500, {"error": str(exc)})
            return
        self._send_json(status, body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/health", "/api/health"):
            self._send_json(
                200,
                {
                    "ok": True,
                    "engine": "RCS_EBL",
                    "version": ENGINE_VERSION,
                    "base_rcs": RCS_ENGINE_VERSION,
                },
            )
            return

        rel = path.lstrip("/") or "index.html"
        if ".." in rel or rel.startswith("/"):
            self._send_json(400, {"error": "bad path"})
            return
        target = (FRONTEND_DIR / rel).resolve()
        try:
            target.relative_to(FRONTEND_DIR.resolve())
        except ValueError:
            self._send_json(400, {"error": "bad path"})
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._send_json(404, {"error": "not found", "path": rel})
            return
        data = target.read_bytes()
        ctype = _guess_type(target.suffix)
        self._send_bytes(200, data, ctype)


def _guess_type(suffix: str) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
        ".txt": "text/plain; charset=utf-8",
    }.get(suffix.lower(), "application/octet-stream")


def main() -> int:
    global FRONTEND_DIR, GENERATOR
    parser = argparse.ArgumentParser(description="RCS_EBL local server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--frontend-dir",
        type=Path,
        default=DEFAULT_FRONTEND,
        help="Static frontend directory",
    )
    args = parser.parse_args()
    FRONTEND_DIR = args.frontend_dir.resolve()
    if not FRONTEND_DIR.is_dir():
        print(f"Frontend dir missing: {FRONTEND_DIR}", file=sys.stderr)
        return 1

    print("Loading EBL tables + RCS matcher...", flush=True)
    GENERATOR = EblCandidateGenerator()
    print(
        f"Ready. UI http://{args.host}:{args.port}/  "
        f"API POST http://{args.host}:{args.port}/candidates",
        flush=True,
    )
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
