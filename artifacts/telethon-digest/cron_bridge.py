#!/usr/bin/env python3
import fcntl
import json
import logging
import os
import subprocess
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] cron_bridge: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("cron_bridge")

PORT = int(os.environ.get("DIGEST_CRON_BRIDGE_PORT", "8091"))
TOKEN = os.environ.get("DIGEST_CRON_BRIDGE_TOKEN", "").strip()
STATE_DIR = Path("/app/state")
LOCK_PATH = STATE_DIR / "cron-bridge.lock"


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "telethon-digest-cron-bridge/1.0"

    def do_POST(self) -> None:
        if self.path != "/trigger":
            self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})
            return
        if not TOKEN:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"ok": False, "error": "missing_bridge_token"})
            return
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self._send(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        digest_type = str(payload.get("digest_type", "")).strip()
        if digest_type not in {"morning", "interval", "editorial"}:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_digest_type"})
            return

        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("w") as lock_fp:
            try:
                fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self._send(HTTPStatus.CONFLICT, {"ok": False, "error": "digest_already_running"})
                return

            logger.info("Bridge trigger received for %s", digest_type)
            env = os.environ.copy()
            env["DIGEST_TYPE_OVERRIDE"] = digest_type
            proc = subprocess.run(
                ["python", "digest_worker.py", "--now"],
                cwd="/app",
                env=env,
                capture_output=True,
                text=True,
            )
            output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part).strip()
            self._send(
                HTTPStatus.OK if proc.returncode == 0 else HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": proc.returncode == 0,
                    "digest_type": digest_type,
                    "exit_code": proc.returncode,
                    "tail": output.splitlines()[-12:] if output else [],
                },
            )

    def log_message(self, fmt: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send(self, status: HTTPStatus, payload: dict) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logger.info("Bridge listening on 0.0.0.0:%s", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
