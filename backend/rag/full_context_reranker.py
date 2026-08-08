"""Full-context reranking for hybrid card retrieval."""

from __future__ import annotations

from typing import Any

from .candidate_assessment import (
    CandidateAssessment,
    Relationship,
    classify_relationship,
    confidence_score,
    rejection_reason,
)
from .mechanism import (
    GENERIC_CONCEPTS,
    extract_phrase_concepts,
    mechanism_concepts,
    mechanism_match,
    parse_mechanism,
)
from .query_intent import QueryIntent, parse_query_intent
from .relevance import _highlight_text, _terms


class FullContextReranker:
    """Deterministic reranker over section, tag, citation, highlights, and body.

    This is the local, dependency-free reranker. A cross-encoder can replace the
    scoring method later while keeping the same input and output shape.
    """

    def rerank(
        self,
        intent_or_query: QueryIntent | str,
        cards: list[dict[str, Any]],
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        intent = (
            parse_query_intent(intent_or_query)
            if isinstance(intent_or_query, str)
            else intent_or_query
        )
        assessed = []
        for card in cards:
            assessment = self.assess(intent, card)
            enriched = dict(card)
            enriched["reranker_score"] = assessment.relevance_score
            enriched["candidate_assessment"] = assessment.to_dict()
            enriched["reranker_assessment"] = assessment.to_dict()
            enriched["reranker_input"] = reranker_input(intent, card)
            assessed.append(enriched)

        assessed.sort(
            key=lambda row: (
                float(row["reranker_score"]),
                float(row.get("retrieval_score", 0)),
            ),
            reverse=True,
        )
        return assessed[:limit] if limit is not None else assessed

    def assess(self, intent: QueryIntent, card: dict[str, Any]) -> CandidateAssessment:
        query_text = intent.opponent_claim or intent.search_text or intent.raw_query
        query_mechanism = parse_mechanism(query_text)
        query_terms = _terms(query_text) | query_mechanism.phrase_concepts
        card_mechanism = parse_mechanism(_card_mechanism_text(card))
        matched_concepts, missing_concepts = mechanism_concepts(
            query_mechanism, card_mechanism
        )
        match_locations = _match_locations(query_terms, card)
        if not query_terms:
            return _assessment(
                card,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                True,
                ["empty-query"],
                query_mechanism,
                card_mechanism,
                relationship=Relationship.IRRELEVANT,
                evidence_strength=0.0,
                confidence=0.0,
                rejection="empty query",
                matched_concepts=matched_concepts,
                missing_concepts=missing_concepts,
                match_locations=match_locations,
            )

        field_terms = _field_terms(card)
        tag_hits = query_terms & field_terms["tag"]
        highlight_hits = query_terms & field_terms["highlights"]
        body_hits = query_terms & field_terms["body"]
        citation_hits = query_terms & field_terms["citation"]
        section_hits = query_terms & field_terms["section"]

        useful_terms = (
            field_terms["tag"]
            | field_terms["highlights"]
            | field_terms["body"]
            | field_terms["citation"]
        )
        useful_hits = query_terms & useful_terms
        mechanism = mechanism_match(query_mechanism, card_mechanism)

        topic_match = _ratio(query_terms & (field_terms["tag"] | field_terms["highlights"]), query_terms)
        warrant_match = _ratio(
            query_terms & (field_terms["highlights"] | field_terms["body"]),
            query_terms,
        )
        useful_context_match = _ratio(useful_hits, query_terms)
        same_section_only = bool(section_hits and not useful_hits)

        score = (
            _hit_score(tag_hits) * 4.0
            + _hit_score(highlight_hits) * 3.0
            + _hit_score(body_hits) * 1.25
            + _hit_score(citation_hits) * 0.75
            + len(section_hits) * 0.15
            + mechanism * 10.0
            + _evidence_strength(card) * 2.0
            + float(card.get("retrieval_score", 0)) * 5.0
        )
        if same_section_only:
            score *= 0.2
        if mechanism < 0.25:
            score *= 0.45
        if not (tag_hits or highlight_hits or body_hits):
            score *= 0.4
        relevance_score = round(max(0.0, min(1.0, score / 24.0)), 3)
        relationship = classify_relationship(
            query_mechanism=query_mechanism,
            card_mechanism=card_mechanism,
            topic_match=topic_match,
            mechanism_match=mechanism,
            warrant_match=warrant_match,
        )
        evidence_strength = _evidence_strength(card)
        rejection = rejection_reason(
            relationship=relationship,
            relevance_score=relevance_score,
            mechanism_match=mechanism,
            same_section_only=same_section_only,
        )
        confidence = confidence_score(
            relevance_score=relevance_score,
            mechanism_match=mechanism,
            warrant_match=warrant_match,
            evidence_strength=evidence_strength,
            relationship=relationship,
        )

        reasons = _reasons(
            tag_hits=tag_hits,
            highlight_hits=highlight_hits,
            body_hits=body_hits,
            citation_hits=citation_hits,
            section_hits=section_hits,
            mechanism_match=mechanism,
            relationship=relationship.value,
            matched_concepts=matched_concepts,
            missing_concepts=missing_concepts,
            match_locations=match_locations,
            same_section_only=same_section_only,
        )
        if rejection:
            reasons.append(f"rejected: {rejection}")
        return _assessment(
            card,
            relevance_score,
            topic_match,
            mechanism,
            warrant_match,
            useful_context_match,
            same_section_only,
            reasons,
            query_mechanism,
            card_mechanism,
            relationship=relationship,
            evidence_strength=evidence_strength,
            confidence=confidence,
            rejection=rejection,
            matched_concepts=matched_concepts,
            missing_concepts=missing_concepts,
            match_locations=match_locations,
        )


def reranker_input(intent_or_query: QueryIntent | str, card: dict[str, Any]) -> str:
    intent = (
        parse_query_intent(intent_or_query)
        if isinstance(intent_or_query, str)
        else intent_or_query
    )
    query_text = intent.opponent_claim or intent.search_text or intent.raw_query
    return "\n".join(
        [
            "Query:",
            query_text,
            "",
            "Card:",
            "Section:",
            str(card.get("section") or card.get("section_name") or ""),
            "",
            "Tag:",
            str(card.get("tag") or ""),
            "",
            "Citation:",
            _citation_label(card),
            "",
            "Highlights:",
            _highlight_text(card) or "",
            "",
            "Body:",
            str(card.get("body") or card.get("body_preview") or ""),
        ]
    ).strip()


def _field_terms(card: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "section": _text_terms(
            str(card.get("section") or card.get("section_name") or "")
        ),
        "tag": _text_terms(str(card.get("tag") or "")),
        "citation": _terms(_citation_label(card)),
        "highlights": _text_terms(_highlight_text(card)),
        "body": _text_terms(str(card.get("body") or card.get("body_preview") or "")),
    }


def _text_terms(text: str) -> set[str]:
    return _terms(text) | extract_phrase_concepts(text)


def _card_mechanism_text(card: dict[str, Any]) -> str:
    return "\n".join(
        str(part)
        for part in [
            card.get("section") or card.get("section_name"),
            card.get("tag"),
            _highlight_text(card),
            card.get("body") or card.get("body_preview"),
        ]
        if part
    )


def _citation_label(card: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in [
            card.get("card_name"),
            card.get("author"),
            card.get("year"),
            card.get("citation"),
        ]
        if part
    )


def _ratio(matches: set[str], total: set[str]) -> float:
    return round(len(matches) / len(total), 3) if total else 0.0


def _assessment(
    card: dict[str, Any],
    relevance_score: float,
    topic_match: float,
    mechanism: float,
    warrant_match: float,
    useful_context_match: float,
    same_section_only: bool,
    reasons: list[str],
    query_mechanism,
    card_mechanism,
    *,
    relationship,
    evidence_strength: float,
    confidence: float,
    rejection: str | None,
    matched_concepts: list[str],
    missing_concepts: list[str],
    match_locations: dict[str, list[str]],
) -> CandidateAssessment:
    return CandidateAssessment(
        card_id=str(card.get("card_id") or card.get("id") or ""),
        relevance_score=round(relevance_score, 3),
        topic_match=round(topic_match, 3),
        mechanism_match=round(mechanism, 3),
        warrant_match=round(warrant_match, 3),
        relationship=relationship,
        supports_claim=relationship.value == "SUPPORTS",
        contradicts_claim=relationship.value == "CONTRADICTS",
        evidence_strength=round(evidence_strength, 3),
        confidence=round(confidence, 3),
        rejection_reason=rejection,
        matched_concepts=matched_concepts,
        missing_concepts=missing_concepts,
        match_locations=match_locations,
        reasons=reasons,
        query_mechanism=query_mechanism,
        card_mechanism=card_mechanism,
    )


def _reasons(
    *,
    tag_hits: set[str],
    highlight_hits: set[str],
    body_hits: set[str],
    citation_hits: set[str],
    section_hits: set[str],
    mechanism_match: float,
    relationship: str,
    matched_concepts: list[str],
    missing_concepts: list[str],
    match_locations: dict[str, list[str]],
    same_section_only: bool,
) -> list[str]:
    reasons = []
    if tag_hits:
        reasons.append(f"tag matched: {', '.join(sorted(tag_hits))}")
    if highlight_hits:
        reasons.append(f"highlights matched: {', '.join(sorted(highlight_hits))}")
    if body_hits:
        reasons.append(f"body matched: {', '.join(sorted(body_hits))}")
    if citation_hits:
        reasons.append(f"citation matched: {', '.join(sorted(citation_hits))}")
    if section_hits:
        reasons.append(f"section matched: {', '.join(sorted(section_hits))}")
    reasons.append(f"mechanism match: {mechanism_match:.3f}")
    reasons.append(f"relationship: {relationship}")
    if matched_concepts:
        reasons.append(f"matched concepts: {', '.join(matched_concepts)}")
    if missing_concepts:
        reasons.append(f"missing concepts: {', '.join(missing_concepts)}")
    for field_name, matches in match_locations.items():
        if matches:
            reasons.append(f"{field_name} matched: {', '.join(matches)}")
    if same_section_only:
        reasons.append("penalty: same section only")
    return reasons


def _evidence_strength(card: dict[str, Any]) -> float:
    score = 0.0
    if card.get("highlights") or _highlight_text(card):
        score += 0.45
    if card.get("citation"):
        score += 0.2
    if card.get("card_name"):
        score += 0.15
    if card.get("author"):
        score += 0.1
    if card.get("year"):
        score += 0.1
    return round(min(score, 1.0), 3)


def _hit_score(hits: set[str]) -> float:
    return round(sum(_term_weight(term) for term in hits), 3)


def _term_weight(term: str) -> float:
    if "_" in term:
        return 2.5
    if term in GENERIC_CONCEPTS:
        return 0.2
    if term in {"ai"}:
        return 0.6
    return 1.0


def _match_locations(query_terms: set[str], card: dict[str, Any]) -> dict[str, list[str]]:
    field_terms = _field_terms(card)
    return {
        field_name: sorted(query_terms & terms)
        for field_name, terms in field_terms.items()
        if query_terms & terms
    }
