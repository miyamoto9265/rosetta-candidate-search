#!/usr/bin/env python3
"""Smoke-test DeepSeek API access without storing the API key.

Usage:
  set DEEPSEEK_API_KEY in your shell, then run:
    python deepseek_smoke_test.py

The key is read only from the environment.  Do not put the key in this file.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set; skipping API call.")
        return 2

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Reply with exactly: ok. This is an API connectivity test."
                ),
            }
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")
        print(f"DeepSeek API HTTP error: {exc.code}")
        print(err[:500])
        return 1
    except Exception as exc:  # noqa: BLE001 - smoke test should surface any failure.
        print(f"DeepSeek API request failed: {exc}")
        return 1

    msg = body.get("choices", [{}])[0].get("message", {}).get("content", "")
    usage = body.get("usage", {})
    print("DeepSeek API reachable.")
    print(f"model={body.get('model', MODEL)}")
    print(f"reply={msg!r}")
    if usage:
        print(f"usage={usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

