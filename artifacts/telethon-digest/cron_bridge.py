#!/usr/bin/env python3
import fcntl
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
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
STATUS_PATH = STATE_DIR / "cron-bridge-status.json"


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_status() -> dict:
    if not STATUS_PATH.exists():
        return {"ok": True, "running": False}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "running": False, "error": "status_unreadable"}


def _write_status(payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "telethon-digest-cron-bridge/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            status = _load_status()
            self._send(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "telethon-digest-cron-bridge",
                    "running": bool(status.get("running")),
                    "last_digest_type": status.get("digest_type"),
                    "last_started_at": status.get("started_at"),
                    "last_finished_at": status.get("finished_at"),
                    "last_exit_code": status.get("exit_code"),
                },
            )
            return
        if self.path == "/status":
            self._send(HTTPStatus.OK, _load_status())
            return
        self._send(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not_found"})

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
                status = _load_status()
                self._send(
                    HTTPStatus.CONFLICT,
                    {
                        "ok": False,
                        "error": "digest_already_running",
                        "running": bool(status.get("running", True)),
                        "digest_type": status.get("digest_type"),
                        "started_at": status.get("started_at"),
                    },
                )
                return

            logger.info("Bridge trigger received for %s", digest_type)
            started_at = _utc_now()
            _write_status(
                {
                    "ok": True,
                    "running": True,
                    "digest_type": digest_type,
                    "started_at": started_at,
                    "finished_at": None,
                    "exit_code": None,
                    "tail": [],
                }
            )
            env = os.environ.copy()
            env["DIGEST_TYPE_OVERRIDE"] = digest_type
            try:
                proc = subprocess.run(
                    ["python", "digest_worker.py", "--now"],
                    cwd="/app",
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5400,
                )
                output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part).strip()
                response_payload = {
                    "ok": proc.returncode == 0,
                    "running": False,
                    "digest_type": digest_type,
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "exit_code": proc.returncode,
                    "tail": output.splitlines()[-12:] if output else [],
                }
                status = HTTPStatus.OK if proc.returncode == 0 else HTTPStatus.INTERNAL_SERVER_ERROR
            except subprocess.TimeoutExpired as exc:
                output = "\n".join(
                    part.strip()
                    for part in [
                        (exc.stdout or "").strip(),
                        (exc.stderr or "").strip(),
                    ]
                    if part
                ).strip()
                response_payload = {
                    "ok": False,
                    "running": False,
                    "digest_type": digest_type,
                    "started_at": started_at,
                    "finished_at": _utc_now(),
                    "exit_code": 124,
                    "error": "digest_worker_timeout",
                    "tail": output.splitlines()[-12:] if output else [],
                }
                status = HTTPStatus.GATEWAY_TIMEOUT
            _write_status(response_payload)
            self._send(status, response_payload)

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
