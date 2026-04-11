#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config",
        nargs="?",
        default="secrets/telethon-digest/config.local.json",
        help="Path to fetched Telethon Digest config/catalog",
    )
    parser.add_argument("--folder", help="Only list one folder")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include groups/supergroups; default lists broadcast channels only",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.config).read_text(encoding="utf-8"))
    folders = data.get("folders", [])
    for folder in folders:
        if args.folder and folder.get("name") != args.folder:
            continue
        channels = folder.get("channels", [])
        if not args.all:
            channels = [ch for ch in channels if ch.get("broadcast") is True]
        print(f"\n[{folder.get('name')}] {len(channels)}")
        for ch in channels:
            ch_type = ch.get("type", "unknown")
            print(f"{ch['id']}\t{ch_type}\t{ch['name']}")


if __name__ == "__main__":
    main()
