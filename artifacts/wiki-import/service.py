from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from importer import ImportRequest, WikiImporter


PORT = int(os.environ.get("WIKI_IMPORT_PORT", "8095") or 8095)
TOKEN = os.environ.get("WIKI_IMPORT_TOKEN", "").strip()
OBSIDIAN_ROOT = Path(os.environ.get("WIKI_IMPORT_OBSIDIAN_ROOT", "/app/obsidian"))
HOST_OPT_ROOT = Path(os.environ.get("WIKI_IMPORT_HOST_OPT_ROOT", "/host-opt"))
STATE_ROOT = Path(os.environ.get("WIKI_IMPORT_STATE_ROOT", "/app/state"))

IMPORTER = WikiImporter(obsidian_root=OBSIDIAN_ROOT, host_opt_root=HOST_OPT_ROOT, state_root=STATE_ROOT)
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "wiki-import/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        if self.path == "/status":
            if not self._authorized():
                return
            self._send_json(HTTPStatus.OK, IMPORTER.status())
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        if self.path == "/trigger":
            self._handle_trigger(payload)
            return
        if self.path == "/lint":
            self._handle_lint(payload)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

    def log_message(self, fmt: str, *args) -> None:
        return

    def _handle_trigger(self, payload: dict) -> None:
        try:
            request = ImportRequest(
                source_type=str(payload.get("source_type") or "").strip(),
                source=str(payload.get("source") or "").strip(),
                target_kind=str(payload.get("target_kind") or "auto").strip(),
                title=str(payload.get("title") or "").strip(),
                import_goal=str(payload.get("import_goal") or "").strip(),
            )
            if not request.source_type or not request.source:
                raise ValueError("source_type and source are required")
            with LOCK:
                result = IMPORTER.import_source(request)
            self._send_json(HTTPStatus.OK, result)
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

    def _handle_lint(self, payload: dict) -> None:
        repair = bool(payload.get("repair", False))
        try:
            with LOCK:
                result = IMPORTER.lint(repair=repair)
            self._send_json(HTTPStatus.OK, result)
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"})

    def _authorized(self) -> bool:
        if not TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        if header == f"Bearer {TOKEN}":
            return True
        self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
        return False

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
