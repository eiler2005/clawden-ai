"""Free Reddit hybrid adapter for last30days-skill.

Primary transport:
- old.reddit.com JSON via curl

Fallback transports:
- Reddit search RSS / subreddit search RSS
- Reddit thread comments RSS for best-effort enrichment

This module is copied into the pinned upstream last30days-skill during image
build and called from pipeline.py instead of reddit_public.py.
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse


USER_AGENT = "last30days/3.0 (research tool)"
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

DEPTH_LIMITS = {
    "quick": 10,
    "default": 25,
    "deep": 50,
}

ENRICH_LIMITS = {
    "quick": 3,
    "default": 5,
    "deep": 8,
}

RSS_RELEVANCE_BASE = 0.22
RSS_RELEVANCE_CAP = 0.46

STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}


def _log(msg: str) -> None:
    sys.stderr.write(f"[RedditHybrid] {msg}\n")
    sys.stderr.flush()


def _curl_fetch(url: str, *, accept: str, timeout: int = 15) -> tuple[int, str, str] | None:
    marker_status = "__L30D_STATUS__:"
    marker_type = "__L30D_TYPE__:"
    cmd = [
        "curl",
        "-sS",
        "-L",
        "-A",
        USER_AGENT,
        "-H",
        f"Accept: {accept}",
        "--connect-timeout",
        "10",
        "--max-time",
        str(timeout),
        "-w",
        f"\n{marker_status}%{{http_code}}\n{marker_type}%{{content_type}}",
        url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        _log(f"curl unavailable for {url}: {exc}")
        return None

    payload = result.stdout
    status_idx = payload.rfind(f"\n{marker_status}")
    type_idx = payload.rfind(f"\n{marker_type}")
    if status_idx == -1 or type_idx == -1 or type_idx < status_idx:
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            _log(f"curl failed for {url}: {stderr[:160]}")
        return None

    body = payload[:status_idx]
    status_line = payload[status_idx + len(f"\n{marker_status}") : type_idx].strip()
    content_type = payload[type_idx + len(f"\n{marker_type}") :].strip()

    try:
        status = int(status_line)
    except ValueError:
        _log(f"invalid curl status for {url}: {status_line!r}")
        return None

    return status, content_type, body


def _clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _token_overlap(query: str, text: str) -> float:
    query_tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in STOPWORDS
    }
    if not query_tokens:
        return 0.0
    haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
    overlap = len(query_tokens & haystack)
    return overlap / float(len(query_tokens))


def _rss_relevance(query: str, title: str, excerpt: str) -> float:
    overlap = max(_token_overlap(query, title), _token_overlap(query, f"{title} {excerpt}"))
    score = RSS_RELEVANCE_BASE + (overlap * 0.28)
    return round(min(RSS_RELEVANCE_CAP, max(0.12, score)), 3)


def _build_search_url(query: str, *, subreddit: str | None, limit: int) -> str:
    encoded_query = quote_plus(query)
    if subreddit:
        sub = subreddit.lstrip("r/").strip()
        return (
            f"https://old.reddit.com/r/{sub}/search.json"
            f"?q={encoded_query}&restrict_sr=on&sort=relevance&t=month&limit={limit}&raw_json=1"
        )
    return (
        f"https://old.reddit.com/search.json"
        f"?q={encoded_query}&sort=relevance&t=month&limit={limit}&raw_json=1"
    )


def _build_rss_url(query: str, *, subreddit: str | None) -> str:
    encoded_query = quote_plus(query)
    if subreddit:
        sub = subreddit.lstrip("r/").strip()
        return (
            f"https://www.reddit.com/r/{sub}/search.rss"
            f"?q={encoded_query}&restrict_sr=on&sort=relevance&t=month"
        )
    return f"https://www.reddit.com/search.rss?q={encoded_query}&sort=relevance&t=month"


def _extract_subreddit_label(raw_label: str) -> str:
    label = (raw_label or "").strip()
    if label.startswith("r/"):
        return label[2:]
    return label


def _parse_json_posts(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    children = data.get("data", {}).get("children", [])
    posts: list[dict[str, Any]] = []
    for index, child in enumerate(children, start=1):
        if child.get("kind") != "t3":
            continue
        post = child.get("data", {})
        permalink = str(post.get("permalink", "")).strip()
        if not permalink or "/comments/" not in permalink:
            continue
        created_utc = post.get("created_utc")
        date_str = None
        if created_utc:
            try:
                dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                date_str = dt.strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                date_str = None

        score = int(post.get("score", 0) or 0)
        num_comments = int(post.get("num_comments", 0) or 0)
        posts.append(
            {
                "id": f"R{index}",
                "title": str(post.get("title", "")).strip(),
                "url": f"https://www.reddit.com{permalink}",
                "score": score,
                "num_comments": num_comments,
                "subreddit": str(post.get("subreddit", "")).strip(),
                "created_utc": float(created_utc) if created_utc else None,
                "author": str(post.get("author", "[deleted]")) or "[deleted]",
                "selftext": str(post.get("selftext", "") or "")[:500],
                "date": date_str,
                "engagement": {
                    "score": score,
                    "num_comments": num_comments,
                    "upvote_ratio": post.get("upvote_ratio"),
                },
                "relevance": _compute_json_relevance(score, num_comments),
                "why_relevant": "Reddit old.reddit JSON search",
                "metadata": {"retrieval_transport": "json"},
            }
        )
    return posts


def _compute_json_relevance(score: int, num_comments: int) -> float:
    score_component = min(1.0, max(0.0, score / 500.0))
    comments_component = min(1.0, max(0.0, num_comments / 200.0))
    return round((score_component * 0.6) + (comments_component * 0.4), 3)


def _search_json(query: str, *, depth: str, subreddit: str | None = None, timeout: int = 15) -> List[Dict[str, Any]]:
    limit = DEPTH_LIMITS.get(depth, DEPTH_LIMITS["default"])
    url = _build_search_url(query, subreddit=subreddit, limit=limit)
    response = _curl_fetch(url, accept="application/json", timeout=timeout)
    if not response:
        return []
    status, content_type, body = response
    if status != 200:
        _log(f"JSON search returned {status} for {url}")
        return []
    if "json" not in content_type.lower():
        _log(f"JSON search returned non-JSON content for {url}: {content_type}")
        return []
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        _log(f"JSON decode failed for {url}: {exc}")
        return []
    return _dedupe_posts(_parse_json_posts(payload))[:limit]


def _parse_rss_posts(feed_text: str, *, query: str) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        _log(f"RSS parse error: {exc}")
        return []

    posts: list[dict[str, Any]] = []
    for index, entry in enumerate(root.findall("atom:entry", ATOM_NS), start=1):
        raw_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        if not raw_id.startswith("t3_"):
            continue
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        link = entry.find("atom:link", ATOM_NS)
        url = link.get("href", "").strip() if link is not None else ""
        if "/comments/" not in url:
            continue
        content = entry.findtext("atom:content", default="", namespaces=ATOM_NS) or ""
        excerpt = _clean_text(content)[:500]
        published = (
            entry.findtext("atom:published", default="", namespaces=ATOM_NS)
            or entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        )
        author_name = ""
        author = entry.find("atom:author", ATOM_NS)
        if author is not None:
            author_name = (author.findtext("atom:name", default="", namespaces=ATOM_NS) or "").strip()

        subreddit = ""
        category = entry.find("atom:category", ATOM_NS)
        if category is not None:
            subreddit = _extract_subreddit_label(category.get("label", "") or category.get("term", ""))

        posts.append(
            {
                "id": f"R{index}",
                "title": title,
                "url": url,
                "score": 0,
                "num_comments": 0,
                "subreddit": subreddit,
                "created_utc": None,
                "author": author_name or "[deleted]",
                "selftext": excerpt[:500],
                "date": _parse_iso_date(published),
                "engagement": {
                    "score": 0,
                    "num_comments": 0,
                    "upvote_ratio": None,
                },
                "relevance": _rss_relevance(query, title, excerpt),
                "why_relevant": "Reddit RSS search fallback",
                "metadata": {"retrieval_transport": "rss"},
            }
        )
    return _dedupe_posts(posts)


def _search_rss(query: str, *, depth: str, subreddit: str | None = None, timeout: int = 15) -> List[Dict[str, Any]]:
    limit = DEPTH_LIMITS.get(depth, DEPTH_LIMITS["default"])
    url = _build_rss_url(query, subreddit=subreddit)
    response = _curl_fetch(url, accept="application/atom+xml", timeout=timeout)
    if not response:
        return []
    status, _, body = response
    if status != 200:
        _log(f"RSS search returned {status} for {url}")
        return []
    return _parse_rss_posts(body, query=query)[:limit]


def _search_one(query: str, *, depth: str, subreddit: str | None = None, timeout: int = 15) -> List[Dict[str, Any]]:
    json_posts = _search_json(query, depth=depth, subreddit=subreddit, timeout=timeout)
    if json_posts:
        return json_posts
    return _search_rss(query, depth=depth, subreddit=subreddit, timeout=timeout)


def _dedupe_posts(posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_urls: set[str] = set()
    unique: list[dict[str, Any]] = []
    for post in posts:
        url = post.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(post)
    for index, post in enumerate(unique, start=1):
        post["id"] = f"R{index}"
    return unique


def _comments_rss_url(url: str) -> str | None:
    parsed = urlparse(url)
    if "reddit.com" not in parsed.netloc:
        return None
    path = parsed.path.rstrip("/")
    if not path or "/comments/" not in path:
        return None
    return f"https://www.reddit.com{path}/.rss"


def _parse_comments_feed(feed_text: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    try:
        root = ET.fromstring(feed_text)
    except ET.ParseError as exc:
        _log(f"comments RSS parse error: {exc}")
        return None, []

    submission: dict[str, Any] | None = None
    comments: list[dict[str, Any]] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        raw_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        content = _clean_text(entry.findtext("atom:content", default="", namespaces=ATOM_NS) or "")
        published = (
            entry.findtext("atom:published", default="", namespaces=ATOM_NS)
            or entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        )
        date_value = _parse_iso_date(published)
        author = entry.find("atom:author", ATOM_NS)
        author_name = ""
        if author is not None:
            author_name = (author.findtext("atom:name", default="", namespaces=ATOM_NS) or "").strip()
        link = entry.find("atom:link", ATOM_NS)
        url = link.get("href", "").strip() if link is not None else ""

        if raw_id.startswith("t3_"):
            submission = {
                "title": title,
                "selftext": content[:500],
                "date": date_value,
                "url": url,
            }
            continue

        if raw_id.startswith("t1_") and author_name not in {"[deleted]", "[removed]"} and content:
            comments.append(
                {
                    "author": author_name or "[deleted]",
                    "body": content[:300],
                    "excerpt": content[:200],
                    "date": date_value,
                    "url": url,
                }
            )

    return submission, comments


def _extract_comment_insights(comments: List[Dict[str, Any]], limit: int = 5) -> List[str]:
    insights: list[str] = []
    for comment in comments:
        body = (comment.get("body") or "").strip()
        if len(body) < 30:
            continue
        if re.match(r"^(this|same|agreed|exactly|yep|nope|yes|no|thanks|thank you)\.?$", body.lower()):
            continue
        snippet = body[:150]
        if len(body) > 150:
            for index, char in enumerate(snippet):
                if char in ".!?" and index > 50:
                    snippet = snippet[: index + 1]
                    break
            else:
                snippet = snippet.rstrip() + "..."
        insights.append(snippet)
        if len(insights) >= limit:
            break
    return insights


def _enrich_post(item: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    rss_url = _comments_rss_url(item.get("url", ""))
    if not rss_url:
        return item
    response = _curl_fetch(rss_url, accept="application/atom+xml", timeout=timeout)
    if not response:
        return item
    status, _, body = response
    if status != 200:
        return item

    submission, comments = _parse_comments_feed(body)
    if submission and not item.get("selftext"):
        item["selftext"] = submission.get("selftext", "")[:500]
    if submission and not item.get("date") and submission.get("date"):
        item["date"] = submission["date"]

    top_comments = comments[:5]
    if top_comments:
        item["top_comments"] = [
            {
                "author": comment.get("author", ""),
                "date": comment.get("date"),
                "excerpt": comment.get("excerpt", ""),
                "url": comment.get("url", ""),
            }
            for comment in top_comments
        ]
        item["comment_insights"] = _extract_comment_insights(top_comments)

    metadata = dict(item.get("metadata") or {})
    metadata["comment_transport"] = "rss"
    item["metadata"] = metadata
    return item


def _enrich_posts(posts: List[Dict[str, Any]], depth: str = "default") -> List[Dict[str, Any]]:
    limit = ENRICH_LIMITS.get(depth, ENRICH_LIMITS["default"])
    to_enrich = posts[:limit]
    rest = posts[limit:]
    if not to_enrich:
        return posts

    result_map: dict[int, Dict[str, Any]] = {}
    try:
        with ThreadPoolExecutor(max_workers=min(limit, 4)) as executor:
            futures = {executor.submit(_enrich_post, post, 10): idx for idx, post in enumerate(to_enrich)}
            import concurrent.futures

            done, not_done = concurrent.futures.wait(futures, timeout=45)
            for future in done:
                idx = futures[future]
                try:
                    result_map[idx] = future.result(timeout=0)
                except Exception:
                    result_map[idx] = to_enrich[idx]
            for future in not_done:
                idx = futures[future]
                result_map[idx] = to_enrich[idx]
                future.cancel()
    except Exception:
        return posts

    enriched = [result_map[idx] for idx in range(len(to_enrich))]
    return enriched + rest


def _search_subreddit(sub: str, topic: str, depth: str, timeout: int = 15) -> List[Dict[str, Any]]:
    try:
        return _search_one(topic, depth=depth, subreddit=sub, timeout=timeout)
    except Exception as exc:
        _log(f"subreddit search failed for r/{sub}: {exc}")
        return []


def search_reddit_hybrid(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
    subreddits: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    all_posts: list[dict[str, Any]] = []

    if subreddits:
        _log(f"searching {len(subreddits)} targeted subreddits")
        workers = min(4, len(subreddits))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_search_subreddit, sub, topic, depth): sub for sub in subreddits}
            for future in futures:
                sub = futures[future]
                try:
                    sub_posts = future.result(timeout=30)
                    _log(f"  -> {len(sub_posts)} results from r/{sub}")
                    all_posts.extend(sub_posts)
                except (Exception, FuturesTimeoutError) as exc:
                    _log(f"  -> r/{sub} failed: {exc}")

    global_posts = _search_one(topic, depth=depth, subreddit=None)
    all_posts.extend(global_posts)

    deduped = _dedupe_posts(all_posts)

    filtered = []
    for item in deduped:
        date_value = item.get("date")
        if date_value is None or (from_date <= date_value <= to_date):
            filtered.append(item)

    filtered.sort(
        key=lambda item: (
            item.get("engagement", {}).get("score", 0),
            item.get("engagement", {}).get("num_comments", 0),
            item.get("date") or "",
        ),
        reverse=True,
    )

    enriched = _enrich_posts(filtered, depth=depth)
    for index, item in enumerate(enriched, start=1):
        item["id"] = f"R{index}"
    return enriched
