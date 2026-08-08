#!/usr/bin/env python3
"""Run a small keyword search against the SQLite ground-truth DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.rag import RetrievalEngine, SearchRequest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    engine = RetrievalEngine(args.db)
    rows = engine.search(
        SearchRequest(query=args.query, limit=args.limit, include_body_preview=False)
    )

    for row in rows:
        print("-" * 45)
        print(f"Score: {row['score']:.3f}")
        print()
        print("Section:")
        print(row["section"])
        print()
        print("Tag:")
        print(row["tag"])
        print()
        print("Citation:")
        citation_label = row["card_name"] or row["author"] or "Unknown"
        if row["year"]:
            citation_label = f"{citation_label} ({row['year']})"
        print(citation_label)
        print()
        print("Highlights:")
        highlights = row.get("highlights", [])
        if highlights:
            for highlight in highlights:
                color = f" [{highlight['color']}]" if highlight.get("color") else ""
                print(f"-{color} {_clip(str(highlight['text']), 180)}")
        else:
            print("- No highlights captured.")
        print()


def _clip(text: str, max_length: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


if __name__ == "__main__":
    main()
