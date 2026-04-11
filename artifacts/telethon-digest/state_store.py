"""
Persistent per-channel watermarks: last_seen_msg_id and last_run timestamp.
State is stored in /app/state/state.json inside the container.
"""
import json
import os
import time
from pathlib import Path

STATE_PATH = Path(os.environ.get("STATE_PATH", "/app/state/state.json"))


def _load() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2))


def get_cursor(channel_id: int) -> int:
    """Return last seen message ID for a channel (0 if never read)."""
    data = _load()
    return data.get("cursors", {}).get(str(channel_id), 0)


def set_cursor(channel_id: int, msg_id: int):
    data = _load()
    data.setdefault("cursors", {})[str(channel_id)] = msg_id
    _save(data)


def bulk_set_cursors(cursors: dict[int, int]):
    """Update multiple channel cursors at once."""
    data = _load()
    cs = data.setdefault("cursors", {})
    for cid, mid in cursors.items():
        cs[str(cid)] = mid
    _save(data)


def get_last_run() -> float:
    data = _load()
    return data.get("last_run", 0.0)


def set_last_run(ts: float = None):
    data = _load()
    data["last_run"] = ts if ts is not None else time.time()
    _save(data)
