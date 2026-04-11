"""
Shared OmniRoute helpers.

Supports both normal JSON chat completions and text/event-stream responses.
"""
import json
from typing import Any

import aiohttp

from models import LLMCompletion


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


def has_markdown_fences(text: str) -> bool:
    return "```" in text


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
    raise ValueError("No valid JSON payload found in LLM response")


async def read_completion(
    resp: aiohttp.ClientResponse,
    default_model: str,
) -> LLMCompletion:
    """
    Read either OpenAI-compatible JSON or SSE responses from OmniRoute.
    """
    content_type = resp.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        data = await resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage", {}) or {}
        return LLMCompletion(
            text=content,
            model_id=data.get("model", default_model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    chunks: list[str] = []
    model_id = default_model
    prompt_tokens = 0
    completion_tokens = 0

    async for raw_line in resp.content:
        line = raw_line.decode("utf-8", errors="ignore").strip()
        if not line.startswith("data:"):
            continue

        payload = line.removeprefix("data:").strip()
        if payload == "[DONE]":
            break

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if "model" in data:
            model_id = data["model"]
        if "usage" in data:
            usage = data["usage"] or {}
            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
            completion_tokens = usage.get("completion_tokens", completion_tokens)

        choice = (data.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content") or message.get("content") or ""
        if content:
            chunks.append(content)

    return LLMCompletion(
        text="".join(chunks).strip(),
        model_id=model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


async def call_chat_completion(
    session: aiohttp.ClientSession,
    *,
    url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    default_model: str,
) -> LLMCompletion:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with session.post(
        f"{url}/chat/completions",
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout_seconds),
    ) as resp:
        resp.raise_for_status()
        return await read_completion(resp, default_model=default_model)
