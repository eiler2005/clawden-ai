#!/usr/bin/env python3
"""AgentMail inbox-email bridge + Redis Streams consumer."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import redis as redis_lib
from dotenv import load_dotenv

from agent_runner import AgentRunError, run_agent_json
from event_store import append_events, list_events, trim_old_events
from models import DigestPrepResult, PollPrepResult
from poster import post_html_message, render_digest, render_poll_batch
from prompts import build_commit_labels_prompt, build_digest_prompt, build_prepare_poll_prompt
import state_store

load_dotenv("/app/email.env", override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] agentmail-email: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("agentmail-email")

PORT = int(os.environ.get("EMAIL_BRIDGE_PORT", "8092"))
TOKEN = os.environ.get("EMAIL_BRIDGE_TOKEN", "").strip()
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config.json"))
STATE_DIR = Path("/app/state")
STATUS_PATH = STATE_DIR / "email-bridge-status.json"

STREAM_JOBS = "ingest:jobs:email"
STREAM_DLQ = "dlq:failed"
CONSUMER_GROUP = "email-workers"
CONSUMER_NAME = "agentmail-email-worker"
BLOCK_MS = 5000

VALID_JOB_TYPES = {"poll", "digest"}
VALID_DIGEST_TYPES = {"morning", "interval", "editorial"}


def load_config() -> dict:
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    inbox_ref = os.environ.get("AGENTMAIL_INBOX_REF", "").strip()
    if inbox_ref:
        data["inbox_ref"] = inbox_ref
    return data


def _make_redis() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


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


def _write_status(r: redis_lib.Redis | None, payload: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if r is not None:
        state_store.set_status(r, payload)


def _tail_union(*tails: list[str]) -> list[str]:
    lines: list[str] = []
    for tail in tails:
        lines.extend(tail)
    return lines[-16:]


def _event_retention_days(config: dict) -> int:
    return int(config.get("event_retention_days", 7) or 7)


def _labels(config: dict) -> dict[str, str]:
    current = config.get("labels", {}) or {}
    return {
        "polled": str(current.get("polled", "benka/polled")),
        "low_signal": str(current.get("low_signal", "benka/low-signal")),
        "digested": str(current.get("digested", "benka/digested")),
    }


def _collect_message_ids(events) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for event in events:
        for message_id in event.message_ids:
            if message_id and message_id not in seen:
                seen.add(message_id)
                result.append(message_id)
    return result


def _apply_label_actions(inbox_ref: str, label_actions: dict[str, list[str]]) -> list[str]:
    cleaned = {
        label: sorted({message_id for message_id in message_ids if str(message_id).strip()})
        for label, message_ids in label_actions.items()
        if sorted({message_id for message_id in message_ids if str(message_id).strip()})
    }
    if not cleaned:
        return ["label commit skipped (no-op)"]
    result = run_agent_json(build_commit_labels_prompt(inbox_ref=inbox_ref, label_actions=cleaned))
    return result.output_tail


def _prepare_poll_result(
    *,
    config: dict,
    run_id: str,
    inbox_ref: str,
    since_dt: datetime,
    until_dt: datetime,
    mode: str,
) -> tuple[PollPrepResult, list[str]]:
    result = run_agent_json(
        build_prepare_poll_prompt(
            inbox_ref=inbox_ref,
            topic_name=str(config.get("topic_name", "inbox-email")),
            since_iso=since_dt.isoformat(),
            until_iso=until_dt.isoformat(),
            labels=_labels(config),
            low_signal_hints=[str(v) for v in config.get("low_signal_hints", [])],
            mode=mode,
        )
    )
    return (
        PollPrepResult.from_payload(
            result.payload,
            run_id=run_id,
            inbox_ref=inbox_ref,
            telegram_topic=str(config.get("topic_name", "inbox-email")),
        ),
        result.output_tail,
    )


def _persist_catchup_if_needed(
    r: redis_lib.Redis,
    *,
    config: dict,
    run_id: str,
    inbox_ref: str,
    since_dt: datetime,
    until_dt: datetime,
) -> list[str]:
    poll_result, tail = _prepare_poll_result(
        config=config,
        run_id=f"{run_id}-catchup",
        inbox_ref=inbox_ref,
        since_dt=since_dt,
        until_dt=until_dt,
        mode="catchup",
    )

    if poll_result.publish_events:
        append_events(r, poll_result.publish_events, retention_days=_event_retention_days(config))

    tail_commit = _apply_label_actions(inbox_ref, poll_result.label_actions)
    state_store.set_dt(r, state_store.last_poll_key(inbox_ref), until_dt)
    state_store.set_dt(r, state_store.last_poll_success_key(inbox_ref), until_dt)
    trim_old_events(r, retention_days=_event_retention_days(config))
    return _tail_union(tail, tail_commit)


def _process_poll(r: redis_lib.Redis, *, data: dict[str, str], config: dict) -> list[str]:
    inbox_ref = data.get("inbox_ref") or str(config.get("inbox_ref", "")).strip()
    if not inbox_ref:
        raise RuntimeError("missing_inbox_ref")

    run_id = data.get("run_id", str(uuid.uuid4()))
    lock_name = state_store.lock_key(inbox_ref, "poll")
    if not state_store.acquire_lock(r, lock_name, run_id, ttl_seconds=900):
        raise RuntimeError("poll_lock_busy")

    try:
        now = datetime.now(timezone.utc)
        last_poll_at = state_store.get_dt(r, state_store.last_poll_key(inbox_ref))
        since_dt = last_poll_at or (now - timedelta(minutes=int(config.get("poll_bootstrap_lookback_minutes", 30) or 30)))
        poll_result, prep_tail = _prepare_poll_result(
            config=config,
            run_id=run_id,
            inbox_ref=inbox_ref,
            since_dt=since_dt,
            until_dt=now,
            mode="poll",
        )

        if poll_result.publish_events:
            html = render_poll_batch(poll_result, window_start=since_dt, window_end=now)
            posted = asyncio.run(post_html_message(html))
            if not posted:
                raise RuntimeError("telegram_post_failed")
            append_events(r, poll_result.publish_events, retention_days=_event_retention_days(config))

        commit_tail = _apply_label_actions(inbox_ref, poll_result.label_actions)
        state_store.set_dt(r, state_store.last_poll_key(inbox_ref), now)
        state_store.set_dt(r, state_store.last_poll_success_key(inbox_ref), now)
        trim_old_events(r, retention_days=_event_retention_days(config))
        return _tail_union(prep_tail, commit_tail)
    finally:
        state_store.release_lock(r, lock_name, run_id)


def _process_digest(r: redis_lib.Redis, *, data: dict[str, str], config: dict) -> list[str]:
    inbox_ref = data.get("inbox_ref") or str(config.get("inbox_ref", "")).strip()
    digest_type = data.get("digest_type", "interval")
    if not inbox_ref:
        raise RuntimeError("missing_inbox_ref")
    if digest_type not in VALID_DIGEST_TYPES:
        raise RuntimeError("invalid_digest_type")

    run_id = data.get("run_id", str(uuid.uuid4()))
    lock_name = state_store.lock_key(inbox_ref, "digest")
    if not state_store.acquire_lock(r, lock_name, run_id, ttl_seconds=1800):
        raise RuntimeError("digest_lock_busy")

    try:
        now = datetime.now(timezone.utc)
        last_digest_at = state_store.get_dt(r, state_store.last_digest_key(inbox_ref))
        window_start = last_digest_at or (now - timedelta(hours=int(config.get("digest_bootstrap_lookback_hours", 24) or 24)))

        last_poll_success = state_store.get_dt(r, state_store.last_poll_success_key(inbox_ref))
        lag_grace = timedelta(minutes=int(config.get("poll_lag_grace_minutes", 15) or 15))
        catchup_tail: list[str] = []
        if last_poll_success is None or (now - last_poll_success) > lag_grace:
            catchup_since = state_store.get_dt(r, state_store.last_poll_key(inbox_ref)) or window_start
            catchup_tail = _persist_catchup_if_needed(
                r,
                config=config,
                run_id=run_id,
                inbox_ref=inbox_ref,
                since_dt=catchup_since,
                until_dt=now,
            )

        events = list_events(r, inbox_ref=inbox_ref, start=window_start, end=now)
        if not events:
            state_store.set_dt(r, state_store.last_digest_key(inbox_ref), now)
            trim_old_events(r, retention_days=_event_retention_days(config))
            return _tail_union(catchup_tail, ["digest skipped (no derived events)"])

        result = run_agent_json(
            build_digest_prompt(
                digest_type=digest_type,
                topic_name=str(config.get("topic_name", "inbox-email")),
                window_start=window_start,
                window_end=now,
                events=events,
            )
        )
        digest = DigestPrepResult.from_payload(result.payload, digest_type=digest_type)
        html = render_digest(digest, events, window_start=window_start, window_end=now)
        posted = asyncio.run(post_html_message(html))
        if not posted:
            raise RuntimeError("telegram_post_failed")

        digested_label = _labels(config)["digested"]
        commit_tail = _apply_label_actions(inbox_ref, {digested_label: _collect_message_ids(events)})
        state_store.set_dt(r, state_store.last_digest_key(inbox_ref), now)
        trim_old_events(r, retention_days=_event_retention_days(config))
        return _tail_union(catchup_tail, result.output_tail, commit_tail)
    finally:
        state_store.release_lock(r, lock_name, run_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "agentmail-email-bridge/1.0"

    def do_GET(self) -> None:
        if self.path == "/health":
            status = _load_status()
            self._send(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "service": "agentmail-email-bridge",
                    "running": bool(status.get("running")),
                    "last_job_type": status.get("job_type"),
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
        if not REDIS_URL:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "integration_bus_not_configured"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_json"})
            return

        job_type = str(payload.get("job_type", "")).strip()
        if job_type not in VALID_JOB_TYPES:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_job_type"})
            return

        digest_type = str(payload.get("digest_type", "")).strip()
        if job_type == "digest" and digest_type not in VALID_DIGEST_TYPES:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "invalid_digest_type"})
            return

        run_id = str(uuid.uuid4())
        config = load_config()
        inbox_ref = str(payload.get("inbox_ref") or config.get("inbox_ref", "")).strip()
        if not inbox_ref:
            self._send(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "missing_inbox_ref"})
            return

        try:
            r = _make_redis()
            r.xadd(
                STREAM_JOBS,
                {
                    "run_id": run_id,
                    "job_type": job_type,
                    "digest_type": digest_type,
                    "inbox_ref": inbox_ref,
                    "requested_at": _utc_now(),
                    "requested_by": "cron",
                    "window_hint": str(payload.get("window_hint", "")).strip(),
                },
            )
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to enqueue email job: %s", exc)
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": "bus_unavailable", "detail": str(exc)})
            return

        self._send(
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "status": "enqueued",
                "run_id": run_id,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "inbox_ref": inbox_ref,
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


def _consumer_loop_inner(r: redis_lib.Redis) -> None:
    try:
        r.xgroup_create(STREAM_JOBS, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Consumer group '%s' created on '%s'", CONSUMER_GROUP, STREAM_JOBS)
    except redis_lib.exceptions.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise

    logger.info("Email consumer loop ready — listening on '%s'", STREAM_JOBS)
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
        job_type = data.get("job_type", "poll")
        digest_type = data.get("digest_type", "")
        run_id = data.get("run_id", msg_id)
        started_at = _utc_now()

        _write_status(
            r,
            {
                "ok": True,
                "running": True,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": None,
                "exit_code": None,
                "tail": [],
            },
        )

        try:
            config = load_config()
            if job_type == "poll":
                tail = _process_poll(r, data=data, config=config)
            else:
                tail = _process_digest(r, data=data, config=config)
            exit_code = 0
        except AgentRunError as exc:
            logger.error("Agent run failed for run_id=%s: %s", run_id, exc)
            exit_code = 1
            tail = exc.tail or [str(exc)]
        except Exception as exc:
            logger.error("Email pipeline failed for run_id=%s: %s", run_id, exc)
            exit_code = 1
            tail = [str(exc)]

        finished_at = _utc_now()
        _write_status(
            r,
            {
                "ok": exit_code == 0,
                "running": False,
                "job_type": job_type,
                "digest_type": digest_type or None,
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "exit_code": exit_code,
                "tail": tail[-12:],
            },
        )

        if exit_code != 0:
            try:
                r.xadd(
                    STREAM_DLQ,
                    {
                        "source": "email",
                        "job_type": job_type,
                        "digest_type": digest_type,
                        "msg_id": msg_id,
                        "run_id": run_id,
                        "error": tail[-1] if tail else "unknown_error",
                        "failed_at": finished_at,
                    },
                )
            except redis_lib.exceptions.RedisError as exc:
                logger.error("Failed to write email DLQ entry: %s", exc)

        try:
            r.xack(STREAM_JOBS, CONSUMER_GROUP, msg_id)
        except redis_lib.exceptions.RedisError as exc:
            logger.error("Failed to XACK email msg_id=%s: %s", msg_id, exc)


def consumer_loop() -> None:
    logger.info("Email consumer loop starting (REDIS_URL=%s)", REDIS_URL)
    while True:
        try:
            r = _make_redis()
            r.ping()
            _consumer_loop_inner(r)
        except redis_lib.exceptions.ConnectionError as exc:
            logger.error("Redis connection lost: %s — reconnecting in 10s", exc)
            time.sleep(10)
        except Exception as exc:
            logger.error("Email consumer unexpected error: %s — restarting in 5s", exc)
            time.sleep(5)


def main() -> None:
    if not REDIS_URL:
        logger.warning("REDIS_URL is not set — consumer loop disabled, /trigger will return 503")
    else:
        thread = threading.Thread(target=consumer_loop, daemon=True, name="email-consumer")
        thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    logger.info("AgentMail email bridge listening on 0.0.0.0:%s", PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
