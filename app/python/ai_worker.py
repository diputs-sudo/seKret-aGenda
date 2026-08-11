#!/usr/bin/env python3
"""Placeholder Python worker for future AI/ML features.

The Tauri application owns the desktop UI and local database workflow. This
worker is intentionally tiny for now, but gives the app a stable process
boundary for future embedding, reranking, and generation calls.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()

    if args.health:
        print(
            json.dumps(
                {
                    "ok": True,
                    "python": sys.version.split()[0],
                    "platform": platform.platform(),
                    "role": "ai-worker-placeholder",
                },
                indent=2,
            )
        )
        return 0

    print("No worker command supplied.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
