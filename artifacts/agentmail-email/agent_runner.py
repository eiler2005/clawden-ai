"""
OpenClaw agent invocation helpers for AgentMail-driven workflows.
"""
from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import DockerException, NotFound


OPENCLAW_AGENT_ID = os.environ.get("OPENCLAW_AGENT_ID", "main").strip() or "main"
OPENCLAW_AGENT_FALLBACK_ID = os.environ.get("OPENCLAW_AGENT_FALLBACK_ID", "main").strip() or "main"
OPENCLAW_AGENT_TIMEOUT_SECONDS = int(os.environ.get("OPENCLAW_AGENT_TIMEOUT_SECONDS", "900"))
OPENCLAW_AGENT_THINKING = os.environ.get("OPENCLAW_AGENT_THINKING", "medium").strip() or "medium"
OPENCLAW_EXEC_CONTAINER = os.environ.get("OPENCLAW_EXEC_CONTAINER", "openclaw-openclaw-gateway-1").strip() or "openclaw-openclaw-gateway-1"


class AgentRunError(RuntimeError):
    def __init__(self, message: str, *, tail: list[str] | None = None):
        super().__init__(message)
        self.tail = tail or []


@dataclass
class AgentRunResult:
    payload: dict[str, Any]
    output_tail: list[str]
    agent_id: str


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines.pop()
        return "\n".join(lines).strip()
    return stripped


def extract_json_payload(text: str) -> Any:
    stripped = strip_markdown_fences(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(stripped):
            if ch not in "[{":
                continue
            try:
                payload, _ = decoder.raw_decode(stripped[idx:])
                return payload
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON payload found in agent output")


def _looks_like_missing_agent(output: str) -> bool:
    lowered = output.lower()
    return "agent not found" in lowered or "unknown agent" in lowered


def _build_command(agent_id: str, prompt: str, timeout_seconds: int) -> list[str]:
    return [
        "/usr/local/bin/openclaw",
        "agent",
        "--agent",
        agent_id,
        "--thinking",
        OPENCLAW_AGENT_THINKING,
        "--timeout",
        str(timeout_seconds),
        "--message",
        prompt,
    ]


def _run_command(agent_id: str, prompt: str, timeout_seconds: int) -> tuple[str, list[str], int]:
    client = None
    try:
        client = docker.from_env()
        container = client.containers.get(OPENCLAW_EXEC_CONTAINER)
        result = container.exec_run(
            _build_command(agent_id, prompt, timeout_seconds),
            environment={"NO_COLOR": "1"},
            stdout=True,
            stderr=True,
            user="1000:1000",
        )
    except NotFound as exc:
        raise AgentRunError(f"OpenClaw container '{OPENCLAW_EXEC_CONTAINER}' not found") from exc
    except DockerException as exc:
        raise AgentRunError(f"Failed to exec into OpenClaw container '{OPENCLAW_EXEC_CONTAINER}': {exc}") from exc
    finally:
        with contextlib.suppress(Exception):
            if client is not None:
                client.close()

    output = result.output
    if isinstance(output, (tuple, list)):
        parts = [chunk.decode("utf-8", errors="replace").strip() for chunk in output if chunk]
        combined = "\n".join(part for part in parts if part).strip()
    else:
        combined = (output or b"").decode("utf-8", errors="replace").strip()
    tail = combined.splitlines()[-16:] if combined else []
    return combined, tail, int(result.exit_code)


def run_agent_json(prompt: str, *, timeout_seconds: int | None = None) -> AgentRunResult:
    timeout_seconds = timeout_seconds or OPENCLAW_AGENT_TIMEOUT_SECONDS
    attempted = [OPENCLAW_AGENT_ID]
    output, tail, returncode = _run_command(OPENCLAW_AGENT_ID, prompt, timeout_seconds)

    if returncode != 0 and OPENCLAW_AGENT_FALLBACK_ID not in attempted and _looks_like_missing_agent(output):
        attempted.append(OPENCLAW_AGENT_FALLBACK_ID)
        output, tail, returncode = _run_command(OPENCLAW_AGENT_FALLBACK_ID, prompt, timeout_seconds)
        agent_id = OPENCLAW_AGENT_FALLBACK_ID
    else:
        agent_id = OPENCLAW_AGENT_ID

    if returncode != 0:
        raise AgentRunError(f"openclaw agent failed via '{agent_id}' (exit={returncode})", tail=tail)

    try:
        payload = extract_json_payload(output)
    except ValueError as exc:
        raise AgentRunError(f"{exc} via '{agent_id}'", tail=tail) from exc

    if not isinstance(payload, dict):
        raise AgentRunError("Agent returned non-object JSON payload", tail=tail)

    if payload.get("ok") is False:
        raise AgentRunError("Agent returned ok=false payload", tail=tail)

    return AgentRunResult(payload=payload, output_tail=tail, agent_id=agent_id)
