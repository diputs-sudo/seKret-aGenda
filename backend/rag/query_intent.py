"""Deterministic query understanding for retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .relevance import QUERY_EXPANSIONS, _terms
from .mechanism import extract_phrase_concepts, ignored_stopwords

AUTHOR_RE = re.compile(r"\bauthor:([A-Za-z][\w'’-]*)", re.IGNORECASE)
YEAR_RE = re.compile(r"\byear:(\d{4})(?:-(\d{4}))?", re.IGNORECASE)
SECTION_RE = re.compile(r'\bsection:(?:"([^"]+)"|([^\s]+))', re.IGNORECASE)
CATEGORY_RE = re.compile(r"\bcategory:([A-Za-z][\w-]*)", re.IGNORECASE)
TOPICAL_RE = re.compile(r"\btopical:(true|false|yes|no|1|0)", re.IGNORECASE)
COUNT_RE = re.compile(r"\bcount:(\d{1,2})", re.IGNORECASE)
OPPONENT_PREFIX_RE = re.compile(
    r"^\s*(?:opponent|they|other team)\s+(?:says?|argues?|claims?)\s+", re.IGNORECASE
)
CARD_CITATION_RE = re.compile(
    r"^\s*(?P<author>[A-Za-z][A-Za-z'’-]{1,})\s+"
    r"(?P<year>\d{4}|[‘'’]\d{2}|\d{2})\s*$"
)
AUTHOR_ONLY_RE = re.compile(r"^\s*[A-Za-z][A-Za-z'’-]{2,}\s*$")
SECTION_LOOKUP_RE = re.compile(r"^\s*(?:AT:|OV\b|Overview\b).+", re.IGNORECASE)


class SearchMode(str, Enum):
    ARGUMENT = "argument"
    AUTHOR = "author"
    CITATION = "citation"
    SECTION = "section"
    GENERAL = "general"


@dataclass(frozen=True)
class QueryIntent:
    raw_query: str
    mode: str = "search"
    search_mode: SearchMode = SearchMode.GENERAL
    search_text: str = ""
    opponent_claim: str | None = None
    concepts: list[str] = field(default_factory=list)
    phrase_concepts: list[str] = field(default_factory=list)
    ignored_stopwords: list[str] = field(default_factory=list)
    author_filter: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    section_filter: str | None = None
    category_filter: str | None = None
    topical_filter: bool | None = None
    requested_count: int | None = None


def parse_query_intent(query: str, mode: str = "search") -> QueryIntent:
    """Parse simple exact filters and debate concepts without calling an LLM."""
    author_filter = _first_group(AUTHOR_RE, query)
    section_filter = _section_filter(query)
    category_filter = _first_group(CATEGORY_RE, query)
    topical_filter = _topical_filter(query)
    requested_count = _count_filter(query)
    year_min, year_max = _year_filter(query)

    search_text = _strip_filters(query)
    opponent_claim = _opponent_claim(search_text)
    citation_match = CARD_CITATION_RE.match(search_text)
    if citation_match and not author_filter:
        author_filter = citation_match.group("author")
        year_min = year_max = _normalize_year(citation_match.group("year"))
    if SECTION_LOOKUP_RE.match(search_text) and not section_filter:
        section_filter = search_text
    if AUTHOR_ONLY_RE.match(search_text) and not author_filter:
        author_filter = search_text

    search_mode = _search_mode(
        search_text=search_text,
        opponent_claim=opponent_claim,
        author_filter=author_filter,
        year_min=year_min,
        section_filter=section_filter,
        citation_match=bool(citation_match),
    )
    concept_text = opponent_claim or search_text
    concepts = _concepts(concept_text)
    phrase_concepts = sorted(extract_phrase_concepts(concept_text))
    ignored = sorted(ignored_stopwords(query))

    return QueryIntent(
        raw_query=query,
        mode=mode,
        search_mode=search_mode,
        search_text=search_text,
        opponent_claim=opponent_claim,
        concepts=concepts,
        phrase_concepts=phrase_concepts,
        ignored_stopwords=ignored,
        author_filter=author_filter,
        year_min=year_min,
        year_max=year_max,
        section_filter=section_filter,
        category_filter=category_filter,
        topical_filter=topical_filter,
        requested_count=requested_count,
    )


def _strip_filters(query: str) -> str:
    text = query
    for pattern in (AUTHOR_RE, YEAR_RE, SECTION_RE, CATEGORY_RE, TOPICAL_RE, COUNT_RE):
        text = pattern.sub("", text)
    return " ".join(text.split())


def _opponent_claim(text: str) -> str | None:
    claim = OPPONENT_PREFIX_RE.sub("", text).strip(" .")
    if claim != text.strip(" .") and claim:
        return claim
    return None


def _concepts(text: str) -> list[str]:
    terms = _terms(text)
    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_EXPANSIONS.get(term, set()))
    return sorted(expanded)


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1) if match else None


def _section_filter(text: str) -> str | None:
    match = SECTION_RE.search(text)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _year_filter(text: str) -> tuple[int | None, int | None]:
    match = YEAR_RE.search(text)
    if not match:
        return None, None
    start = int(match.group(1))
    end = int(match.group(2) or match.group(1))
    return start, end


def _normalize_year(value: str) -> int:
    digits = value.strip("‘'’")
    if len(digits) == 4:
        return int(digits)
    year = int(digits)
    return 2000 + year if year < 70 else 1900 + year


def _search_mode(
    *,
    search_text: str,
    opponent_claim: str | None,
    author_filter: str | None,
    year_min: int | None,
    section_filter: str | None,
    citation_match: bool,
) -> SearchMode:
    if opponent_claim:
        return SearchMode.ARGUMENT
    if section_filter and SECTION_LOOKUP_RE.match(section_filter):
        return SearchMode.SECTION
    if author_filter and year_min is not None:
        return SearchMode.CITATION
    if author_filter:
        return SearchMode.AUTHOR
    if citation_match:
        return SearchMode.CITATION
    if AUTHOR_ONLY_RE.match(search_text):
        return SearchMode.AUTHOR
    return SearchMode.GENERAL


def _topical_filter(text: str) -> bool | None:
    match = TOPICAL_RE.search(text)
    if not match:
        return None
    return match.group(1).lower() in {"true", "yes", "1"}


def _count_filter(text: str) -> int | None:
    match = COUNT_RE.search(text)
    if not match:
        return None
    return max(1, min(int(match.group(1)), 50))
