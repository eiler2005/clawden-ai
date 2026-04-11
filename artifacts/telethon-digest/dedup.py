"""
LLM-based post deduplication (separate module — no Telethon deps).

Makes one batch async call to OmniRoute medium tier to cluster similar posts.
Keeps the highest-scoring post per cluster; attaches also_mentioned list.
Gracefully skips on any error (dedup is optional).
"""
import logging
import os
from typing import List

import aiohttp

from models import Post
from omniroute_client import call_chat_completion, extract_json_payload

logger = logging.getLogger(__name__)

_OMNIROUTE_URL = os.environ.get("OMNIROUTE_URL", "http://omniroute:20129/v1")
_OMNIROUTE_KEY = os.environ.get("OMNIROUTE_API_KEY", "")
_DEDUP_MODEL = "medium"  # light tier can't reliably output JSON


async def deduplicate_posts(posts: List[Post], config: dict) -> List[Post]:
    """
    Cluster similar posts via one batch LLM call.
    For each cluster keep the highest-scoring post; attach also_mentioned list.
    Returns deduplicated list sorted by score desc.
    Gracefully returns original list on any error.
    """
    if not config.get("dedup_enabled", False) or len(posts) < 2:
        return posts

    items = [
        {"idx": i, "channel": p.channel_name, "text": p.text[:300]}
        for i, p in enumerate(posts)
    ]

    system_prompt = (
        "You are a deduplication assistant. Given a list of Telegram posts, "
        "identify groups of posts covering the same news story or topic. "
        "Return ONLY a JSON array of clusters. Each cluster is an array of post indices. "
        "Posts that are unique go into their own single-element cluster. "
        "Do not explain — output raw JSON only. Example: [[0,3],[1],[2,4,5]]"
    )
    import json

    user_prompt = json.dumps(items, ensure_ascii=False)

    try:
        async with aiohttp.ClientSession() as session:
            completion = await call_chat_completion(
                session,
                url=_OMNIROUTE_URL,
                api_key=_OMNIROUTE_KEY,
                payload={
                    "model": _DEDUP_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 1024,
                    "temperature": 0,
                    "stream": False,
                },
                timeout_seconds=60,
                default_model=_DEDUP_MODEL,
            )
            raw = completion.text

        if not raw:
            raise ValueError("Empty response from dedup LLM")

        payload = extract_json_payload(raw)
        if not isinstance(payload, list):
            raise ValueError("Dedup response is not a JSON array")
        clusters: list[list[int]] = []
        for cluster in payload:
            if not isinstance(cluster, list):
                raise ValueError("Dedup cluster is not a list")
            clean_cluster: list[int] = []
            for value in cluster:
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    clean_cluster.append(value)
                    continue
                if isinstance(value, str) and value.lstrip("-").isdigit():
                    clean_cluster.append(int(value))
                    continue
                raise ValueError(f"Invalid dedup index: {value!r}")
            clusters.append(clean_cluster)

    except Exception as e:
        logger.warning(f"Dedup skipped ({e})")
        return posts

    # Build result: canonical post per cluster (highest score)
    seen: set[int] = set()
    result: list[Post] = []

    for cluster in clusters:
        valid = [i for i in cluster if 0 <= i < len(posts)]
        if not valid:
            continue
        canonical_idx = max(valid, key=lambda i: posts[i].score)
        canonical = posts[canonical_idx]
        others = [posts[i].channel_name for i in valid if i != canonical_idx]
        canonical.also_mentioned = others
        seen.add(canonical_idx)
        result.append(canonical)

    # Add any posts not mentioned in any cluster
    for i, p in enumerate(posts):
        if i not in seen:
            result.append(p)

    result.sort(key=lambda p: p.score, reverse=True)
    logger.info(f"Dedup: {len(posts)} posts → {len(result)} after LLM clustering")
    return result
