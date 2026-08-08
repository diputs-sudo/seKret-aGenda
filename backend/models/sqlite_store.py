"""SQLite persistence for DebateIR."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from uuid import uuid4

from backend.models import DebateDocument, EvidenceCard

SCHEMA_PATH = Path(__file__).with_name("sqlite_schema.sql")


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(SCHEMA_PATH.read_text())
    connection.commit()


def save_document(connection: sqlite3.Connection, document: DebateDocument) -> None:
    with connection:
        connection.execute("DELETE FROM debate_documents WHERE id = ?", (document.id,))
        connection.execute(
            """
            INSERT INTO debate_documents (
                id, name, source_path, source_format, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document.id,
                document.name,
                document.source_path,
                document.source_format,
                json.dumps(document.metadata),
                document.created_at.isoformat(),
            ),
        )

        for section in document.sections:
            connection.execute(
                """
                INSERT INTO sections (
                    id, document_id, parent_id, name, argument_type, order_index,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    section.id,
                    section.document_id,
                    section.parent_id,
                    section.name,
                    section.argument_type.value,
                    section.order_index,
                    json.dumps(section.metadata),
                ),
            )
            for card in section.cards:
                _insert_card(connection, card)


def search_cards(
    connection: sqlite3.Connection, query: str, limit: int = 10
) -> list[dict[str, object]]:
    fts_query = query if _is_advanced_fts_query(query) else _plain_query(query)
    if not fts_query:
        return []

    rows = _search_cards(connection, fts_query, limit)
    if rows or _is_advanced_fts_query(fts_query):
        return [_format_search_row(connection, row) for row in rows]

    fallback_query = _or_query(fts_query)
    if fallback_query == fts_query:
        return [_format_search_row(connection, row) for row in rows]
    return [
        _format_search_row(connection, row)
        for row in _search_cards(connection, fallback_query, limit)
    ]


def _search_cards(
    connection: sqlite3.Connection, query: str, limit: int
) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            evidence_cards_fts.rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards_fts
        JOIN evidence_cards ON evidence_cards.id = evidence_cards_fts.card_id
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE evidence_cards_fts MATCH ?
        ORDER BY evidence_cards_fts.rank
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()


def _format_search_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> dict[str, object]:
    result = dict(row)
    result["score"] = _score_from_rank(row["rank"])
    result["highlights"] = _card_highlights(connection, row["id"])
    return result


def _score_from_rank(rank: float) -> float:
    if rank == 0:
        return 1.0
    if rank < 0:
        raw_score = abs(rank)
        return max(round(raw_score / (1.0 + raw_score), 3), 0.001)
    return max(round(1.0 / (1.0 + rank), 3), 0.001)


def _card_highlights(
    connection: sqlite3.Connection, card_id: str, limit: int = 5
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT text, color, paragraph_index, start_char, end_char
        FROM highlights
        WHERE card_id = ?
        ORDER BY order_index
        """,
        (card_id,),
    ).fetchall()
    merged: list[dict[str, object]] = []

    for row in rows:
        text = " ".join(str(row["text"]).split())
        if not text:
            continue

        previous = merged[-1] if merged else None
        if (
            previous
            and previous["color"] == row["color"]
            and previous["paragraph_index"] == row["paragraph_index"]
        ):
            previous["text"] = f"{previous['text']} {text}"
            previous["end_char"] = row["end_char"]
        else:
            merged.append(
                {
                    "text": text,
                    "color": row["color"],
                    "paragraph_index": row["paragraph_index"],
                    "start_char": row["start_char"],
                    "end_char": row["end_char"],
                }
            )

        if len(merged) >= limit:
            break

    return merged


def _is_advanced_fts_query(query: str) -> bool:
    return any(token in query for token in ['"', " OR ", " AND ", " NOT ", "NEAR"])


def _plain_query(query: str) -> str:
    terms = _plain_terms(query)
    return " ".join(terms)


def _or_query(query: str) -> str:
    terms = _plain_terms(query)
    if len(terms) < 2:
        return query
    quoted_terms = [f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms]
    return " OR ".join(quoted_terms)


def _plain_terms(query: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", query)


def count_rows(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "debate_documents",
        "sections",
        "evidence_cards",
        "citations",
        "highlights",
    ]
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
    }


def embedding_records(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT
            evidence_cards.id AS card_id,
            debate_documents.name AS document_name,
            sections.name AS section,
            evidence_cards.tag,
            evidence_cards.card_name,
            citations.author,
            citations.year,
            group_concat(highlights.text, ' ') AS highlight_text
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        LEFT JOIN highlights ON highlights.card_id = evidence_cards.id
        GROUP BY evidence_cards.id
        ORDER BY sections.order_index, evidence_cards.paragraph_start
        """
    ).fetchall()

    records = []
    for row in rows:
        section = row["section"] or ""
        tag = row["tag"] or ""
        highlights = " ".join(str(row["highlight_text"] or "").split())
        embedding_text = "\n\n".join(part for part in [section, tag, highlights] if part)
        records.append(
            {
                "card_id": row["card_id"],
                "document_name": row["document_name"],
                "section": section,
                "tag": tag,
                "card_name": row["card_name"],
                "author": row["author"],
                "year": row["year"],
                "highlight_text": highlights,
                "embedding_text": embedding_text,
            }
        )
    return records


def _insert_card(connection: sqlite3.Connection, card: EvidenceCard) -> None:
    topical = None if card.topical is None else int(card.topical)
    connection.execute(
        """
        INSERT INTO evidence_cards (
            id, document_id, section_id, tag, card_name, body, category, topical,
            content_hash, paragraph_start, paragraph_end, source_format,
            metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card.id,
            card.document_id,
            card.section_id,
            card.tag,
            card.card_name,
            card.body,
            card.category,
            topical,
            card.content_hash,
            card.paragraph_start,
            card.paragraph_end,
            card.source_format,
            json.dumps(card.metadata),
            card.created_at.isoformat(),
        ),
    )
    connection.execute(
        """
        INSERT INTO citations (id, card_id, raw, author, year, source_url)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            card.id,
            card.citation.raw,
            card.citation.author,
            card.citation.year,
            card.citation.source_url,
        ),
    )
    for order_index, highlight in enumerate(card.highlights):
        connection.execute(
            """
            INSERT INTO highlights (
                id, card_id, text, color, paragraph_index, run_index, start_char,
                end_char, order_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                card.id,
                highlight.text,
                highlight.color,
                highlight.paragraph_index,
                highlight.run_index,
                highlight.start_char,
                highlight.end_char,
                order_index,
            ),
        )
    connection.execute(
        """
        INSERT INTO evidence_cards_fts (
            card_id, tag, card_name, citation, body
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            card.id,
            card.tag,
            card.card_name or "",
            card.citation.raw,
            card.body,
        ),
    )
