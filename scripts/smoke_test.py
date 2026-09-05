#!/usr/bin/env python3
"""
HTTP smoke checks against a Braelo backend.

Usage:
  BRAELO_SMOKE_BASE_URL=https://host python scripts/smoke_test.py

Exits 0 when required probes pass. Does not require credentials.
Live auth/listing/chat journeys remain a manual QA checklist.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = (os.getenv("BRAELO_SMOKE_BASE_URL") or os.getenv("PUBLIC_BACKEND_URL") or "").rstrip(
    "/"
)
TIMEOUT = float(os.getenv("BRAELO_SMOKE_TIMEOUT", "15"))


def fetch(path: str) -> tuple[int, dict | str]:
    url = f"{BASE}{path}"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode("utf-8", errors="replace")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def main() -> int:
    if not BASE:
        print("BRAELO_SMOKE_BASE_URL is required", file=sys.stderr)
        return 2
    failures = []
    status, body = fetch("/healthz")
    print(f"GET /healthz -> {status} {body}")
    if status != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        failures.append("healthz")
    status, body = fetch("/readyz")
    print(f"GET /readyz -> {status} {body}")
    if status not in (200, 503) or not isinstance(body, dict):
        failures.append("readyz")
    elif body.get("status") == "unavailable":
        failures.append("readyz-unavailable")
    if failures:
        print("SMOKE FAILED:", ", ".join(failures), file=sys.stderr)
        return 1
    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
