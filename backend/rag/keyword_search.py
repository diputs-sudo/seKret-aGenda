"""Keyword search against SQLite FTS."""

from __future__ import annotations

import sqlite3

from backend.models.sqlite_store import search_cards


def keyword_search(
    connection: sqlite3.Connection, query: str, limit: int = 10
) -> list[dict[str, object]]:
    return search_cards(connection, query, limit)
