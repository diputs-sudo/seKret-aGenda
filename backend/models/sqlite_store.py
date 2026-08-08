"""SQLite persistence for DebateIR."""

from __future__ import annotations

import json
import re
import sqlite3
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from backend.models import DebateDocument, EmbeddingKind, EvidenceCard

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


def search_author_citation_cards(
    connection: sqlite3.Connection, query: str, limit: int = 20
) -> list[dict[str, object]]:
    terms = _plain_terms(query)
    if not terms:
        return []

    clauses = []
    params: list[object] = []
    for term in terms:
        pattern = f"%{term}%"
        clauses.append(
            """
            (
                citations.author LIKE ?
                OR evidence_cards.card_name LIKE ?
                OR citations.raw LIKE ?
            )
            """
        )
        params.extend([pattern, pattern, pattern])

    params.append(limit)
    rows = connection.execute(
        f"""
        SELECT
            0.0 AS rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE {" OR ".join(clauses)}
        ORDER BY sections.order_index, evidence_cards.paragraph_start
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_format_search_row(connection, row) for row in rows]


def lookup_author_cards(
    connection: sqlite3.Connection,
    author: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    pattern = f"%{author}%"
    rows = connection.execute(
        """
        SELECT
            0.0 AS rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE
            citations.author LIKE ?
            OR evidence_cards.card_name LIKE ?
            OR citations.raw LIKE ?
        ORDER BY
            CASE
                WHEN lower(citations.author) = lower(?) THEN 0
                WHEN lower(evidence_cards.card_name) LIKE lower(?) THEN 1
                ELSE 2
            END,
            sections.order_index,
            evidence_cards.paragraph_start
        LIMIT ?
        """,
        (pattern, pattern, pattern, author, f"{author}%", limit),
    ).fetchall()
    return [_format_search_row(connection, row) for row in rows]


def lookup_citation_cards(
    connection: sqlite3.Connection,
    author: str,
    year: int,
    limit: int = 20,
) -> list[dict[str, object]]:
    short_year = f"{year % 100:02d}"
    exact_labels = [
        f"{author} {short_year}",
        f"{author} {year}",
        f"{author} '{short_year}",
        f"{author} ’{short_year}",
    ]
    exact_rows = connection.execute(
        """
        SELECT
            0.0 AS rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE
            lower(evidence_cards.card_name) IN (?, ?, ?, ?)
            OR (lower(citations.author) = lower(?) AND citations.year = ?)
        ORDER BY sections.order_index, evidence_cards.paragraph_start
        LIMIT ?
        """,
        (
            *(label.lower() for label in exact_labels),
            author,
            year,
            limit,
        ),
    ).fetchall()
    if exact_rows:
        return [_format_search_row(connection, row) for row in exact_rows]

    author_pattern = f"%{author}%"
    card_pattern = f"%{author}%{short_year}%"
    rows = connection.execute(
        """
        SELECT
            0.0 AS rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE
            (
                (citations.author LIKE ? OR evidence_cards.card_name LIKE ? OR citations.raw LIKE ?)
                AND citations.year = ?
            )
            OR evidence_cards.card_name LIKE ?
        ORDER BY
            CASE
                WHEN lower(citations.author) = lower(?) AND citations.year = ? THEN 0
                WHEN lower(evidence_cards.card_name) LIKE lower(?) THEN 1
                ELSE 2
            END,
            sections.order_index,
            evidence_cards.paragraph_start
        LIMIT ?
        """,
        (
            author_pattern,
            author_pattern,
            author_pattern,
            year,
            card_pattern,
            author,
            year,
            card_pattern,
            limit,
        ),
    ).fetchall()
    return [_format_search_row(connection, row) for row in rows]


def lookup_section_cards(
    connection: sqlite3.Connection,
    section: str,
    limit: int = 50,
) -> list[dict[str, object]]:
    pattern = f"%{section}%"
    rows = connection.execute(
        """
        SELECT
            0.0 AS rank,
            evidence_cards.id,
            debate_documents.name AS document_name,
            sections.name AS section_name,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.author,
            citations.year,
            citations.raw AS citation,
            substr(evidence_cards.body, 1, 500) AS body_preview
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE sections.name LIKE ?
        ORDER BY
            CASE WHEN lower(sections.name) = lower(?) THEN 0 ELSE 1 END,
            evidence_cards.paragraph_start
        LIMIT ?
        """,
        (pattern, section, limit),
    ).fetchall()
    return [_format_search_row(connection, row) for row in rows]


def load_cards_by_ids(
    connection: sqlite3.Connection, card_ids: list[str]
) -> dict[str, dict[str, object]]:
    if not card_ids:
        return {}

    placeholders = ",".join("?" for _ in card_ids)
    rows = connection.execute(
        f"""
        SELECT
            evidence_cards.id AS card_id,
            debate_documents.name AS document,
            sections.name AS section,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.body,
            evidence_cards.category,
            evidence_cards.topical,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.raw AS citation,
            citations.author,
            citations.year
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE evidence_cards.id IN ({placeholders})
        """,
        card_ids,
    ).fetchall()

    cards = {str(row["card_id"]): dict(row) for row in rows}
    for card_id in cards:
        cards[card_id]["highlights"] = card_highlights(connection, card_id)
    return cards


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
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
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
    result["highlights"] = card_highlights(connection, row["id"])
    return result


def _score_from_rank(rank: float) -> float:
    if rank == 0:
        return 1.0
    if rank < 0:
        raw_score = abs(rank)
        return max(round(raw_score / (1.0 + raw_score), 3), 0.001)
    return max(round(1.0 / (1.0 + rank), 3), 0.001)


def card_highlights(
    connection: sqlite3.Connection, card_id: str, limit: int | None = None
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        SELECT
            text,
            color,
            highlight_color,
            paragraph_index,
            run_index,
            start_char,
            end_char,
            style,
            font_size,
            bold,
            underline
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

        row_bold = bool(row["bold"]) if row["bold"] is not None else None
        row_underline = (
            bool(row["underline"]) if row["underline"] is not None else None
        )
        previous = merged[-1] if merged else None
        if (
            previous
            and previous["color"] == row["color"]
            and previous["paragraph_index"] == row["paragraph_index"]
            and previous["style"] == row["style"]
            and previous["font_size"] == row["font_size"]
            and previous["bold"] == row_bold
            and previous["underline"] == row_underline
        ):
            previous["text"] = f"{previous['text']} {text}"
            previous["end_char"] = row["end_char"]
        else:
            merged.append(
                {
                    "text": text,
                    "color": row["color"],
                    "highlight_color": row["highlight_color"] or row["color"],
                    "paragraph_index": row["paragraph_index"],
                    "run_index": row["run_index"],
                    "start_char": row["start_char"],
                    "end_char": row["end_char"],
                    "style": row["style"],
                    "font_size": row["font_size"],
                    "bold": row_bold,
                    "underline": row_underline,
                }
            )

        if limit is not None and len(merged) >= limit:
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


def embedding_records(
    connection: sqlite3.Connection,
    kind: EmbeddingKind | str = EmbeddingKind.FAST,
) -> list[dict[str, object]]:
    kind = EmbeddingKind(kind)
    rows = connection.execute(
        """
        SELECT
            evidence_cards.id AS card_id,
            debate_documents.name AS document_name,
            debate_documents.source_path AS document_source_path,
            debate_documents.metadata_json AS document_metadata_json,
            sections.name AS section,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.body,
            evidence_cards.category,
            evidence_cards.topical,
            evidence_cards.source_path,
            evidence_cards.source_format,
            evidence_cards.content_hash,
            citations.author,
            citations.year,
            citations.raw AS citation,
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
        citation = row["citation"] or ""
        body = row["body"] or ""
        if kind == EmbeddingKind.FAST:
            embedding_text = "\n\n".join(
                part for part in [section, tag, highlights] if part
            )
        else:
            embedding_text = "\n\n".join(
                part for part in [section, tag, citation, highlights, body] if part
            )
        document_metadata = _json_object(row["document_metadata_json"])
        records.append(
            {
                "card_id": row["card_id"],
                "document_name": row["document_name"],
                "section": section,
                "tag": tag,
                "card_name": row["card_name"],
                "argument_name": row["argument_name"],
                "author": row["author"],
                "year": row["year"],
                "citation": citation,
                "category": row["category"],
                "topical": None if row["topical"] is None else bool(row["topical"]),
                "source_path": row["source_path"] or row["document_source_path"],
                "source_format": row["source_format"],
                "content_hash": row["content_hash"],
                "parser_version": document_metadata.get("parser_version", ""),
                "embedding_kind": kind.value,
                "highlight_text": highlights,
                "embedding_text": embedding_text,
                "source_text_hash": _text_hash(embedding_text),
            }
        )
    return records


def _insert_card(connection: sqlite3.Connection, card: EvidenceCard) -> None:
    topical = None if card.topical is None else int(card.topical)
    connection.execute(
        """
        INSERT INTO evidence_cards (
            id, document_id, section_id, tag, card_name, argument_name, body,
            category, topical, side, source_path, content_hash, paragraph_start,
            paragraph_end, source_format,
            metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card.id,
            card.document_id,
            card.section_id,
            card.tag,
            card.card_name,
            card.argument_name,
            card.body,
            card.category,
            topical,
            card.side,
            card.source_path,
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
                id, card_id, text, color, highlight_color, paragraph_index,
                run_index, start_char, end_char, style, font_size, bold,
                underline, order_index
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                card.id,
                highlight.text,
                highlight.color,
                highlight.color,
                highlight.paragraph_index,
                highlight.run_index,
                highlight.start_char,
                highlight.end_char,
                highlight.style,
                highlight.font_size,
                None if highlight.bold is None else int(highlight.bold),
                None if highlight.underline is None else int(highlight.underline),
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


def _text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
