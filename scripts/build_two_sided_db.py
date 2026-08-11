#!/usr/bin/env python3
"""Build a two-owner SQLite DB from our and opponent DOCX packets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.sqlite_store import connect, count_rows, init_db, save_document
from backend.parser import parse_docx


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build SQLite from separate our/opponent DOCX files."
    )
    parser.add_argument("--us", type=Path, required=True, help="Our evidence DOCX")
    parser.add_argument(
        "--opponent",
        type=Path,
        required=True,
        help="Opponent evidence DOCX",
    )
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--our-side", default="unknown")
    parser.add_argument("--opponent-side", default="unknown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()

    connection = connect(args.db)
    init_db(connection)
    _save_packet(
        connection,
        path=args.us,
        owner="us",
        side=args.our_side,
    )
    _save_packet(
        connection,
        path=args.opponent,
        owner="opponent",
        side=args.opponent_side,
    )
    counts = count_rows(connection)
    connection.close()

    print(f"Built {args.db}")
    print(f"Our packet: {args.us}")
    print(f"Opponent packet: {args.opponent}")
    print(f"Documents: {counts['debate_documents']}")
    print(f"Sections: {counts['sections']}")
    print(f"Cards: {counts['evidence_cards']}")
    print(f"Citations: {counts['citations']}")
    print(f"Highlights: {counts['highlights']}")
    return 0


def _save_packet(connection, *, path: Path, owner: str, side: str) -> None:
    document = parse_docx(path)
    document.metadata.update({"owner": owner, "side": side, "packet": path.stem})
    for section in document.sections:
        section.metadata.update({"owner": owner, "side": side, "packet": path.stem})
        for card in section.cards:
            card.side = side
            card.metadata.update({"owner": owner, "side": side, "packet": path.stem})
    save_document(connection, document)


if __name__ == "__main__":
    raise SystemExit(main())
