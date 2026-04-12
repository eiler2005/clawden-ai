"""
Direct AgentMail HTTP client used by the inbox-email bridge.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


class AgentMailApiError(RuntimeError):
    pass


@dataclass
class AgentMailApiClient:
    api_key: str
    base_url: str = "https://api.agentmail.to"
    timeout_seconds: int = 30
    user_agent: str = "clawden-agentmail-bridge/1.0"

    @staticmethod
    def _format_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        current = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text = current.isoformat(timespec="seconds")
        if text.endswith("+00:00"):
            return text[:-6] + "Z"
        return text

    @classmethod
    def from_env(cls) -> "AgentMailApiClient":
        api_key = os.environ.get("AGENTMAIL_API_KEY", "").strip()
        if not api_key:
            raise AgentMailApiError("missing_agentmail_api_key")
        return cls(
            api_key=api_key,
            base_url=os.environ.get("AGENTMAIL_API_BASE_URL", "https://api.agentmail.to").strip()
            or "https://api.agentmail.to",
            timeout_seconds=int(os.environ.get("AGENTMAIL_API_TIMEOUT_SECONDS", "30") or 30),
            user_agent=os.environ.get("AGENTMAIL_API_USER_AGENT", "clawden-agentmail-bridge/1.0").strip()
            or "clawden-agentmail-bridge/1.0",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        qs = urllib.parse.urlencode(
            {
                key: value
                for key, value in (query or {}).items()
                if value is not None and value != ""
            },
            doseq=True,
        )
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        if qs:
            url = f"{url}?{qs}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AgentMailApiError(f"AgentMail API {method} {path} failed: {exc.code} {body[:400]}") from exc
        except urllib.error.URLError as exc:
            raise AgentMailApiError(f"AgentMail API {method} {path} failed: {exc}") from exc

    def list_inboxes(self, *, limit: int = 100) -> list[dict[str, Any]]:
        data = self._request("GET", "/v0/inboxes", query={"limit": limit})
        return list(data.get("inboxes", []) or [])

    def list_messages(
        self,
        inbox_id: str,
        *,
        limit: int = 100,
        page_token: str | None = None,
        before: datetime | None = None,
        after: datetime | None = None,
        ascending: bool | None = None,
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "limit": limit,
            "page_token": page_token,
            "before": self._format_datetime(before),
            "after": self._format_datetime(after),
            "ascending": str(bool(ascending)).lower() if ascending is not None else None,
        }
        if labels:
            query["labels"] = labels
        return self._request("GET", f"/v0/inboxes/{urllib.parse.quote(inbox_id, safe='')}/messages", query=query)

    def get_thread(self, inbox_id: str, thread_id: str) -> dict[str, Any]:
        return self._request(
            "GET",
            f"/v0/inboxes/{urllib.parse.quote(inbox_id, safe='')}/threads/{urllib.parse.quote(thread_id, safe='')}",
        )

    def update_message(
        self,
        inbox_id: str,
        message_id: str,
        *,
        add_labels: list[str] | None = None,
        remove_labels: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v0/inboxes/{urllib.parse.quote(inbox_id, safe='')}/messages/{urllib.parse.quote(message_id, safe='')}",
            payload={
                "add_labels": add_labels or None,
                "remove_labels": remove_labels or None,
            },
        )
