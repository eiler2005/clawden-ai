"""Patch the pinned upstream last30days-skill checkout during Docker build."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


IMPORT_NEEDLE = "    reddit,\n    reddit_public,\n"
IMPORT_INSERT = "    reddit,\n    reddit_hybrid,\n    reddit_public,\n"

REDDIT_BRANCH_OLD = """    if source == "reddit":
        # Use raw_topic so expand_reddit_queries() generates diverse variants
        # from the original user topic, not the planner's narrowed search_query.
        reddit_query = raw_topic or subquery.search_query
        # Public Reddit first (free, gets comments); SC as backup
        try:
            public_results = reddit_public.search_reddit_public(
                reddit_query, from_date, to_date, depth=depth,
                subreddits=subreddits,
            )
            if public_results:
                return public_results, {}
        except Exception as exc:
            sys.stderr.write(
                f"[Reddit] Public search failed ({type(exc).__name__}: {exc})"
            )
            if not config.get("SCRAPECREATORS_API_KEY"):
                sys.stderr.write("\\n")
                return [], {}
            sys.stderr.write(", using ScrapeCreators backup\\n")
        # Fallback to ScrapeCreators if public returned empty or raised
        if config.get("SCRAPECREATORS_API_KEY"):
            try:
                result = reddit.search_and_enrich(
                    reddit_query,
                    from_date,
                    to_date,
                    depth=depth,
                    token=config.get("SCRAPECREATORS_API_KEY"),
                    subreddits=subreddits,
                )
                return reddit.parse_reddit_response(result), {}
            except Exception as exc:
                sys.stderr.write(
                    f"[Reddit] ScrapeCreators backup also failed "
                    f"({type(exc).__name__}: {exc})\\n"
                )
        return [], {}
"""

REDDIT_BRANCH_NEW = """    if source == "reddit":
        # Use raw_topic so Reddit gets the original topic, not only the planner's
        # narrowed subquery wording.
        reddit_query = raw_topic or subquery.search_query
        try:
            hybrid_results = reddit_hybrid.search_reddit_hybrid(
                reddit_query, from_date, to_date, depth=depth,
                subreddits=subreddits,
            )
            if hybrid_results:
                return hybrid_results, {}
        except Exception as exc:
            sys.stderr.write(
                f"[Reddit] Hybrid search failed ({type(exc).__name__}: {exc})"
            )
            if not config.get("SCRAPECREATORS_API_KEY"):
                sys.stderr.write("\\n")
                return [], {}
            sys.stderr.write(", using ScrapeCreators backup\\n")
        if config.get("SCRAPECREATORS_API_KEY"):
            try:
                result = reddit.search_and_enrich(
                    reddit_query,
                    from_date,
                    to_date,
                    depth=depth,
                    token=config.get("SCRAPECREATORS_API_KEY"),
                    subreddits=subreddits,
                )
                return reddit.parse_reddit_response(result), {}
            except Exception as exc:
                sys.stderr.write(
                    f"[Reddit] ScrapeCreators backup also failed "
                    f"({type(exc).__name__}: {exc})\\n"
                )
        return [], {}
"""


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Failed to locate {label} in upstream file")
    return text.replace(old, new, 1)


def patch_skill(skill_root: Path) -> None:
    skill_root = skill_root.resolve()
    lib_dir = skill_root / "scripts" / "lib"
    pipeline_path = lib_dir / "pipeline.py"
    if not pipeline_path.exists():
        raise SystemExit(f"Missing pipeline.py in {skill_root}")

    pipeline_text = pipeline_path.read_text()
    pipeline_text = _replace_once(
        pipeline_text,
        IMPORT_NEEDLE,
        IMPORT_INSERT,
        label="pipeline import block",
    )
    pipeline_text = _replace_once(
        pipeline_text,
        REDDIT_BRANCH_OLD,
        REDDIT_BRANCH_NEW,
        label="Reddit pipeline branch",
    )
    pipeline_path.write_text(pipeline_text)

    source_module = Path(__file__).with_name("reddit_hybrid.py")
    target_module = lib_dir / "reddit_hybrid.py"
    shutil.copyfile(source_module, target_module)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("Usage: patch_last30days_skill.py /path/to/last30days-skill")
    patch_skill(Path(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
