#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


DEFAULT_URL = "http://wiki-import:8095"


def _token() -> str:
    direct = os.environ.get("WIKI_IMPORT_TOKEN", "").strip()
    if direct:
        return direct
    token_file = os.environ.get("WIKI_IMPORT_TOKEN_FILE", "/run/secrets/wiki_import_token")
    try:
        with open(token_file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""


def _read_payload(args: argparse.Namespace) -> dict:
    if args.json:
        return json.loads(args.json)
    raw = sys.stdin.read().strip()
    if raw:
        return json.loads(raw)
    return {}


def _request(method: str, path: str, payload: dict | None = None) -> int:
    base_url = os.environ.get("WIKI_IMPORT_URL", DEFAULT_URL).rstrip("/")
    token = _token()
    if not token:
        print(json.dumps({"ok": False, "error": "missing_wiki_import_token"}, ensure_ascii=False))
        return 2

    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            sys.stdout.write(response.read().decode("utf-8"))
            sys.stdout.write("\n")
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        print(json.dumps({"ok": False, "http_status": exc.code, "error": detail}, ensure_ascii=False))
        return 1
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}, ensure_ascii=False))
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Call the internal wiki-import bridge.")
    parser.add_argument("command", choices=["trigger", "lint", "status", "maintain"])
    parser.add_argument("--json", help="JSON payload. If omitted, JSON is read from stdin.")
    args = parser.parse_args()

    if args.command == "status":
        return _request("GET", "/status")
    if args.command == "trigger":
        return _request("POST", "/trigger", _read_payload(args))
    if args.command == "lint":
        return _request("POST", "/lint", _read_payload(args))
    if args.command == "maintain":
        return _request("POST", "/maintain", _read_payload(args))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
