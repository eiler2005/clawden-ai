#!/usr/bin/env python3
"""Telethon Digest cron bridge + integration bus consumer.

HTTP server (GET /health, GET /status, POST /trigger) and a Redis Streams
consumer loop running as a background thread in the same process.

POST /trigger enqueues a job to `ingest:jobs:telegram` and returns 202
immediately — the digest pipeline runs asynchronously in the consumer loop.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import redis as redis_lib

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] cron_bridge: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("cron_bridge")

PORT = int(os.environ.get("DIGEST_CRON_BRIDGE_PORT", "8091"))
TOKEN = os.environ.get("DIGEST_CRON_BRIDGE_TOKEN", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()

STATE_DIR = Path("/app/state")
STATUS_PATH = STATE_DIR / "cron-bridge-status.json"

STREAM_JOBS = "ingest:jobs:telegram"
STREAM_DLQ = "dlq:failed"
CONSUMER_GROUP = "digest-workers"
CONSUMER_NAME = "cron-bridge-worker"
BLOCK_MS = 5000

VALID_DIGEST_TYPES = {"morning", "interval", "editorial"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _make_redis() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "telethon-digest-cron-bridge/2.0"

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
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": "missing_bridge_token"},
            )
            return
        if self.headers.get("Authorization", "") != f"Bearer {TOKEN}":
            self._send(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if not REDIS_URL:
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "integration_bus_not_configured"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        digest_type = str(payload.get("digest_type", "")).strip()
        if digest_type not in VALID_DIGEST_TYPES:
            self._send(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": "invalid_digest_type"},
            )
            return

        run_id = str(uuid.uuid4())
        try:
            r = _make_redis()
            r.xadd(
                STREAM_JOBS,
                {
                    "run_id": run_id,
                    "digest_type": digest_type,
                    "requested_at": _utc_now(),
                    "requested_by": "cron",
                },
            )
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to enqueue job: %s", exc)
            self._send(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": False, "error": "bus_unavailable", "detail": str(exc)},
            )
            return

        logger.info("Enqueued job run_id=%s digest_type=%s", run_id, digest_type)
        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "run_id": run_id,
                "digest_type": digest_type,
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


# ---------------------------------------------------------------------------
# Redis consumer loop (background thread)
# ---------------------------------------------------------------------------

def _run_pipeline(digest_type: str, run_id: str) -> tuple[int, list[str]]:
    """Run digest_worker.py subprocess; return (exit_code, tail_lines)."""
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
        output = "\n".join(
            p for p in [proc.stdout.strip(), proc.stderr.strip()] if p
        ).strip()
        return proc.returncode, output.splitlines()[-12:] if output else []
    except subprocess.TimeoutExpired:
        logger.error("digest_worker.py timed out for run_id=%s", run_id)
        return 124, ["timeout"]


def _consumer_loop_inner(r: redis_lib.Redis) -> None:
    """Inner consumer loop; raises on Redis errors for outer reconnect logic."""
    try:
        r.xgroup_create(STREAM_JOBS, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Consumer group '%s' created on '%s'", CONSUMER_GROUP, STREAM_JOBS)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info(
        "Consumer loop ready — listening on '%s' (group '%s')",
        STREAM_JOBS,
        CONSUMER_GROUP,
    )

    while True:
        messages = r.xreadgroup(
            CONSUMER_GROUP,
            CONSUMER_NAME,
            {STREAM_JOBS: ">"},
            block=BLOCK_MS,
            count=1,
        )

        if not messages:
            continue

        _, entries = messages[0]
        msg_id, data = entries[0]
        digest_type = data.get("digest_type", "interval")
        run_id = data.get("run_id", msg_id)
        logger.info("Processing job run_id=%s digest_type=%s", run_id, digest_type)

        started_at = _utc_now()
        _write_status({
            "ok": True,
            "running": True,
            "digest_type": digest_type,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": None,
            "exit_code": None,
            "tail": [],
        })

        exit_code, tail = _run_pipeline(digest_type, run_id)
        finished_at = _utc_now()

        _write_status({
            "ok": exit_code == 0,
            "running": False,
            "digest_type": digest_type,
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "exit_code": exit_code,
            "tail": tail,
        })

        if exit_code != 0:
            logger.error("Pipeline failed exit_code=%d run_id=%s → dlq", exit_code, run_id)
            try:
                r.xadd(STREAM_DLQ, {
                    "source": "telegram",
                    "msg_id": msg_id,
                    "run_id": run_id,
                    "error": f"exit_code={exit_code}",
                    "failed_at": finished_at,
                })
            except redis_lib.exceptions.RedisError as exc:
                logger.error("Failed to write dlq entry: %s", exc)
        else:
            logger.info("Pipeline completed OK run_id=%s", run_id)

        try:
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to XACK msg_id=%s: %s", msg_id, exc)


def consumer_loop() -> None:
    """Background thread: connect to Redis, run consumer loop with reconnect."""
    logger.info("Consumer loop starting (REDIS_URL=%s)", REDIS_URL)
    while True:
        try:
            r = _make_redis()
            r.ping()
            _consumer_loop_inner(r)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("Redis connection lost: %s — reconnecting in 10s", exc)
            time.sleep(10)
        except Exception as exc:
            logger.error("Consumer loop unexpected error: %s — restarting in 5s", exc)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not REDIS_URL:
        logger.warning(
            "REDIS_URL is not set — consumer loop disabled, /trigger will return 503"
        )
    else:
        t = threading.Thread(target=consumer_loop, daemon=True, name="redis-consumer")
        t.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logger.info("Bridge listening on 0.0.0.0:%s", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
