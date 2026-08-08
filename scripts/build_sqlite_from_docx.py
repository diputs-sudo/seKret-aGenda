#!/usr/bin/env python3
"""Build the SQLite ground-truth DB from a DOCX fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.sqlite_store import connect, count_rows, init_db, save_document
from backend.parser import parse_docx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx_path", type=Path)
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    args = parser.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()

    document = parse_docx(args.docx_path)
    connection = connect(args.db)
    init_db(connection)
    save_document(connection, document)
    counts = count_rows(connection)
    connection.close()

    print(f"Built {args.db}")
    print(f"Document: {document.name}")
    print(f"Sections: {counts['sections']}")
    print(f"Cards: {counts['evidence_cards']}")
    print(f"Citations: {counts['citations']}")
    print(f"Highlights: {counts['highlights']}")


if __name__ == "__main__":
    main()
