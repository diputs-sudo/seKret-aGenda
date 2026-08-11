"""Claim-card relationship classification for debate side routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.rag.mechanism import extract_phrase_concepts, mechanism_match, parse_mechanism
from backend.rag.relevance import _highlight_text, _terms

from .claims import ClaimRelation, parse_structured_claim
from .model import ClaimRelationship, RelationshipResult

NEGATION_CUES = {
    "cannot",
    "doesn",
    "doesn't",
    "fail",
    "fails",
    "failed",
    "false",
    "no",
    "not",
    "prevent",
    "prevents",
    "reduce",
    "reduces",
    "wrong",
}
POSITIVE_DIRECTION_CUES = {
    "causes",
    "creates",
    "encourage",
    "encourages",
    "guarantee",
    "guarantees",
    "grow",
    "grows",
    "increase",
    "increases",
    "solve",
    "solves",
    "strengthen",
    "strengthens",
}
NEGATIVE_DIRECTION_CUES = {
    "delete",
    "deletes",
    "destroy",
    "destroys",
    "lower",
    "lowers",
    "prevent",
    "prevents",
    "reduce",
    "reduces",
    "undermine",
    "undermines",
}
GENERIC_EQUIVALENCES = {
    "approval": "authorization",
    "authorization": "approval",
    "baseline": "standard",
    "baselines": "standard",
    "congressional": "congress",
    "diplomatic": "diplomacy",
    "enforcement": "regulation",
    "escalates": "escalation",
    "escalat": "escalation",
    "executive": "president",
    "fragmented": "vary",
    "legislature": "congress",
    "lawmakers": "congress",
    "oversight": "approval",
    "presidential": "president",
    "rules": "regulation",
    "settlement": "diplomacy",
    "uniformity": "standard",
}
RELATION_EQUIVALENCES = {
    ClaimRelation.PREVENTS: {
        "block",
        "check",
        "constrain",
        "prevent",
        "restrain",
        "restrict",
        "slow",
        "stop",
    },
    ClaimRelation.CAUSES: {"cause", "create", "drive", "fuel", "lead", "produce"},
    ClaimRelation.INCREASES: {"escalation", "expand", "increase", "worsen"},
    ClaimRelation.DECREASES: {"decrease", "lower", "mitigate", "reduce"},
    ClaimRelation.ENABLES: {"allow", "enable", "empower"},
    ClaimRelation.UNDERMINES: {"delete", "destroy", "harm", "undermine"},
    ClaimRelation.SOLVES: {"fix", "resolve", "solve"},
    ClaimRelation.PROTECTS: {"preserve", "protect", "safeguard"},
    ClaimRelation.DETERS: {"deter", "discourage"},
}
SLOT_EQUIVALENCES = {
    "approval": {"authorization", "consent", "permission"},
    "authorization": {"approval", "consent", "permission"},
    "congress": {"congressional", "legislature", "lawmakers"},
    "congressional": {"congress", "legislature", "lawmakers"},
    "conflict": {"exchange", "war"},
    "diplomacy": {"diplomatic", "negotiation", "negotiations", "talks"},
    "escalate": {"escalates", "escalating", "escalation", "escalatory"},
    "nuclear": {"atomic", "nuc"},
    "president": {"presidential"},
    "trump": {"trump"},
}
CONTEXTUAL_EQUIVALENCES = {
    "approval": {"check", "checks", "oversight", "review"},
    "authorization": {"check", "checks", "oversight", "review"},
    "congress": {"senate"},
    "conflict": {"crisis"},
    "diplomacy": {"cooperation", "leverage", "settlement"},
    "escalate": {"attack", "attacks", "launch", "strike", "strikes"},
    "nuclear": {"deterrence", "strategic"},
    "president": {"commander", "executive", "leader"},
    "trump": {"commander", "executive", "president", "presidential"},
}
RELATION_CONTEXTUAL_EQUIVALENCES = {
    ClaimRelation.PREVENTS: {
        "buffer",
        "buffers",
        "circumvent",
        "circumvents",
        "unchecked",
    },
    ClaimRelation.CAUSES: {"incentive", "trigger"},
    ClaimRelation.INCREASES: {"embolden", "emboldens"},
    ClaimRelation.DECREASES: {"slow"},
    ClaimRelation.ENABLES: {"loophole", "loopholes"},
    ClaimRelation.UNDERMINES: {"erode", "erodes"},
}
SOURCE_WEIGHTS = {
    "tag": 0.95,
    "highlights": 1.0,
    "body": 0.9,
    "text": 1.0,
    "metadata": 0.85,
    "section": 0.65,
    "card_name": 0.65,
    "citation": 0.2,
}
NON_UNIQUE_CUES = {
    "already",
    "currently",
    "existing",
    "multi-billion",
    "non-unique",
    "nonunique",
    "status quo",
    "squo",
    "today",
}
MITIGATION_CUES = {
    "ban",
    "bans",
    "check",
    "checks",
    "limit",
    "limits",
    "lower",
    "lowers",
    "mitigate",
    "mitigates",
    "prevent",
    "prevents",
    "prohibit",
    "prohibits",
    "reduce",
    "reduces",
}
INDICT_CUES = {
    "assumes",
    "bad evidence",
    "flawed",
    "indict",
    "methodology",
    "no evidence",
    "overstates",
    "underfunded",
    "wrong",
}
TURN_CUES = {
    "backfire",
    "backfires",
    "helps our side",
    "impact turn",
    "link turn",
    "turns the argument",
}
CIRCUMVENTION_CUES = {
    "bypass",
    "bypasses",
    "circumvent",
    "circumvents",
    "despite",
    "evade",
    "evades",
    "loophole",
    "loopholes",
    "unchecked",
}


@dataclass(frozen=True)
class ClaimRelationAssessment:
    relationship: ClaimRelationship
    confidence: float
    overlap: float
    mechanism: float
    directness: float
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "relationship": self.relationship.value,
            "confidence": self.confidence,
            "overlap": self.overlap,
            "mechanism": self.mechanism,
            "directness": self.directness,
            "reasons": self.reasons,
        }

    def to_result(self) -> RelationshipResult:
        return RelationshipResult(
            relationship=self.relationship,
            confidence=self.confidence,
            topic_match=self.overlap,
            mechanism_match=self.mechanism,
            warrant_match=max(self.overlap * 0.6, self.mechanism),
            directness=self.directness,
            reasons=self.reasons,
        )


def classify_claim_relationship(
    claim: str,
    card: dict[str, Any] | str,
) -> ClaimRelationAssessment:
    card_text = card if isinstance(card, str) else card_relationship_text(card)
    front_text = card if isinstance(card, str) else front_relationship_text(card)
    claim_terms = _concepts(claim)
    card_terms = _concepts(card_text)
    if not claim_terms:
        return _assessment(ClaimRelationship.UNKNOWN, 0.0, 0.0, 0.0, ["empty claim"])

    overlap = len(claim_terms & card_terms) / len(claim_terms)
    claim_mechanism = parse_mechanism(claim)
    card_mechanism = parse_mechanism(card_text)
    mech = mechanism_match(claim_mechanism, card_mechanism)
    polarity_opposes = (
        claim_mechanism.polarity != 0
        and card_mechanism.polarity != 0
        and claim_mechanism.polarity != card_mechanism.polarity
        and mech >= 0.2
    )
    cues = _cue_matches(card_text)

    if overlap < 0.08 and mech < 0.08:
        coverage = claim_component_coverage(claim, card)
        attack_alignment = coverage.get("attack_alignment") or {}
        if (
            attack_alignment.get("type") == "CIRCUMVENTION"
            and float(attack_alignment.get("score") or 0.0) >= 0.55
        ):
            boosted_mech = max(mech, float(attack_alignment.get("score") or 0.0) * 0.62)
            return _assessment(
                ClaimRelationship.CONTRADICTS,
                0.56,
                overlap,
                boosted_mech,
                ["circumvention of claimed constraint"],
            )
        return _assessment(
            ClaimRelationship.IRRELEVANT,
            0.9,
            overlap,
            mech,
            ["topic and mechanism mismatch"],
        )
    direction = _direction(claim_terms, card_terms)
    if _is_non_unique_response(claim_terms, card_text, cues) and (overlap >= 0.16 or mech >= 0.18):
        return _assessment(
            ClaimRelationship.NON_UNIQUE,
            _confidence(overlap, mech, 0.78),
            overlap,
            mech,
            ["non-unique/status quo cues"],
        )
    front_assessment = _front_support_assessment(
        claim=claim,
        front_text=front_text,
        claim_terms=claim_terms,
    )
    if front_assessment is not None:
        return front_assessment

    if cues["indict"] and (overlap >= 0.04 or mech >= 0.08):
        return _assessment(
            ClaimRelationship.INDICTS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["warrant/source/mechanism indictment cues"],
        )
    if cues["turn"] and (overlap >= 0.12 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.TURNS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["turn cues"],
        )
    if polarity_opposes or direction == "opposes" or (_has_negation(card_text) and overlap >= 0.22):
        if cues["mitigate"] and not _direct_effect_opposition(claim_mechanism, card_terms):
            return _assessment(
                ClaimRelationship.MITIGATES,
                _confidence(overlap, mech, 0.78),
                overlap,
                mech,
                ["mitigation cues oppose claim"],
            )
        return _assessment(
            ClaimRelationship.CONTRADICTS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["opposes claim mechanism"],
        )
    if cues["mitigate"] and direction != "supports" and _direct_effect_opposition(claim_mechanism, card_terms):
        return _assessment(
            ClaimRelationship.CONTRADICTS,
            _confidence(overlap, mech, 0.78),
            overlap,
            mech,
            ["mitigation cue directly negates claim effect"],
        )
    if cues["mitigate"] and direction != "supports" and (overlap >= 0.08 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.MITIGATES,
            _confidence(overlap, mech, 0.72),
            overlap,
            mech,
            ["mitigation cues"],
        )
    if direction == "supports" and (overlap >= 0.1 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.8),
            overlap,
            mech,
            ["same causal direction"],
        )
    if overlap >= 0.55 or (overlap >= 0.35 and mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.86),
            overlap,
            mech,
            ["card substantially proves the claim"],
        )
    if overlap >= 0.2 or mech >= 0.18:
        return _assessment(
            ClaimRelationship.QUALIFIES,
            _confidence(overlap, mech, 0.55),
            overlap,
            mech,
            ["related but not a direct answer"],
        )
    return _assessment(
        ClaimRelationship.BACKGROUND,
        _confidence(overlap, mech, 0.35),
        overlap,
        mech,
        ["background overlap"],
    )


def card_relationship_text(card: dict[str, Any]) -> str:
    return "\n".join(
        str(part)
        for part in [
            card.get("section") or card.get("section_name"),
            card.get("tag"),
            card.get("card_name"),
            card.get("citation"),
            _highlight_text(card),
            card.get("body") or card.get("body_preview"),
        ]
        if part
    )


def front_relationship_text(card: dict[str, Any]) -> str:
    return "\n".join(
        str(part)
        for part in [
            card.get("section") or card.get("section_name"),
            card.get("tag"),
            _highlight_text(card),
        ]
        if part
    )


def claim_component_coverage(claim: str, card: dict[str, Any] | str) -> dict[str, Any]:
    structured = parse_structured_claim(claim)
    card_text = card if isinstance(card, str) else card_relationship_text(card)
    card_profile = _coverage_profile(card)
    details = {
        "subject": _slot_coverage(structured.subject.value, card_profile),
        "relation": _relation_coverage(
            structured.relation,
            structured.relation_text,
            card_profile,
        ),
        "target_actor": _slot_coverage(structured.target_actor.value, card_profile),
        "target_action": _slot_coverage(structured.target_action.value, card_profile),
        "target_object": _slot_coverage(structured.target_object.value, card_profile),
        "effect": _slot_coverage(structured.effect.value, card_profile),
    }
    attack_alignment = _attack_alignment(structured, card_text, details)
    slots = {key: float(value["score"]) for key, value in details.items()}
    populated = [
        value
        for key, value in slots.items()
        if key != "effect" and _slot_populated(structured, key)
    ]
    score = sum(populated) / len(populated) if populated else 0.0
    source_quality = _overall_source_quality(details)
    warnings = []
    if slots["target_object"] >= 0.35 and max(slots["subject"], slots["target_actor"]) < 0.2:
        warnings.append("impact-heavy match")
    if slots["target_action"] >= 0.55 and slots["target_object"] >= 0.35 and slots["subject"] < 0.2:
        warnings.append("effect-only match")
    for key, value in slots.items():
        if key == "effect" or not _slot_populated(structured, key):
            continue
        if value < 0.2:
            warnings.append(f"missing {key}")
    if score >= 0.25 and source_quality < 0.45:
        warnings.append("low source quality")
    return {
        "score": round(score, 3),
        "source_quality": source_quality,
        "slots": {key: round(value, 3) for key, value in slots.items()},
        "slot_details": details,
        "attack_alignment": attack_alignment,
        "warnings": warnings,
        "structured_claim": structured.to_dict(),
    }


def _attack_alignment(
    structured,
    card_text: str,
    details: dict[str, dict[str, object]],
) -> dict[str, object]:
    if structured.relation == ClaimRelation.PREVENTS:
        lowered = card_text.lower()
        if _has_phrase(lowered, CIRCUMVENTION_CUES):
            actor = float(details["target_actor"]["score"])
            action = float(details["target_action"]["score"])
            obj = float(details["target_object"]["score"])
            relation = float(details["relation"]["score"])
            score = 0.48 + relation * 0.25 + actor * 0.1 + action * 0.08 + obj * 0.09
            return {
                "type": "CIRCUMVENTION",
                "score": round(min(1.0, score), 3),
                "reason": "card describes bypassing or weakening the claimed constraint",
            }
    return {"type": "", "score": 0.0, "reason": ""}


def _concepts(text: str) -> set[str]:
    concepts = _terms(text) | extract_phrase_concepts(text)
    expanded = set(concepts)
    for concept in concepts:
        expanded.add(GENERIC_EQUIVALENCES.get(concept, concept))
        expanded.add(_simple_stem(concept))
    return expanded


def _coverage_profile(card: dict[str, Any] | str) -> dict[str, object]:
    occurrences: dict[str, list[dict[str, str]]] = {}
    surface: set[str] = set()
    phrases: set[str] = set()
    for source, text in _coverage_source_texts(card):
        snippet = _snippet(text)
        for term in _terms(text):
            canonical = _canonical_slot_term(term)
            if not canonical:
                continue
            surface.add(canonical)
            _add_occurrence(occurrences, canonical, source, term, snippet)
        for phrase in extract_phrase_concepts(text):
            canonical = _canonical_slot_term(phrase.replace("_", " "))
            if not canonical:
                continue
            phrases.add(canonical)
            _add_occurrence(occurrences, canonical, source, phrase.replace("_", " "), snippet)
    return {
        "surface": surface,
        "phrases": phrases,
        "all": surface | phrases,
        "occurrences": occurrences,
    }


def _coverage_source_texts(card: dict[str, Any] | str) -> list[tuple[str, str]]:
    if isinstance(card, str):
        return [("text", card)]
    metadata = card.get("metadata") or {}
    sources = [
        ("section", card.get("section") or card.get("section_name")),
        ("tag", card.get("tag")),
        ("card_name", card.get("card_name")),
        ("citation", card.get("citation")),
        ("highlights", _highlight_text(card)),
        ("body", card.get("body") or card.get("body_preview")),
        ("metadata", metadata.get("highlight_text") if not _highlight_text(card) else ""),
    ]
    return [
        (source, str(text))
        for source, text in sources
        if text
    ]


def _add_occurrence(
    occurrences: dict[str, list[dict[str, str]]],
    canonical: str,
    source: str,
    matched: str,
    snippet: str,
) -> None:
    bucket = occurrences.setdefault(canonical, [])
    record = {"source": source, "matched": matched, "snippet": snippet}
    if record not in bucket:
        bucket.append(record)


def _slot_coverage(value: str, card_profile: dict[str, object]) -> dict[str, object]:
    if not value:
        return _coverage_detail(0.0, "absent", [], [])
    slot_terms = [_canonical_slot_term(term) for term in _terms(value)]
    slot_terms = [term for term in slot_terms if term]
    if not slot_terms:
        return _coverage_detail(0.0, "absent", [], [])

    matched: list[str] = []
    provenances: list[dict[str, str]] = []
    term_scores: list[float] = []
    kinds: list[str] = []
    for term in slot_terms:
        score, kind, matched_term, provenance = _term_coverage(term, card_profile)
        term_scores.append(score)
        kinds.append(kind)
        if matched_term:
            matched.append(f"{term}->{matched_term}" if matched_term != term else term)
            provenances.extend(_annotate_provenance(provenance, term, matched_term))

    score = sum(term_scores) / len(term_scores)
    kind = _combined_kind(kinds)
    return _coverage_detail(score, kind, matched, slot_terms, provenances)


def _relation_coverage(
    relation: ClaimRelation,
    relation_text: str,
    card_profile: dict[str, object],
) -> dict[str, object]:
    if relation == ClaimRelation.UNKNOWN:
        return _coverage_detail(0.0, "absent", [], [])
    surface_terms = {
        _canonical_slot_term(term)
        for term in _terms(relation_text)
        if _canonical_slot_term(term)
    }
    semantic_terms = {
        _canonical_slot_term(term)
        for term in RELATION_EQUIVALENCES.get(relation, set())
        if _canonical_slot_term(term)
    }
    contextual_terms = {
        _canonical_slot_term(term)
        for term in RELATION_CONTEXTUAL_EQUIVALENCES.get(relation, set())
        if _canonical_slot_term(term)
    }
    card_terms = card_profile["all"]
    exact = sorted(surface_terms & card_terms)
    if exact:
        provenance = _provenance_for_terms(card_profile, exact)
        return _coverage_detail(
            _weighted_score(1.0, provenance),
            "explicit",
            exact,
            sorted(surface_terms),
            provenance,
        )
    semantic = sorted(semantic_terms & card_terms)
    if semantic:
        provenance = _provenance_for_terms(card_profile, semantic)
        return _coverage_detail(
            _weighted_score(0.72, provenance),
            "semantic",
            semantic,
            sorted(semantic_terms),
            provenance,
        )
    contextual = sorted(contextual_terms & card_terms)
    if contextual:
        provenance = _provenance_for_terms(card_profile, contextual)
        return _coverage_detail(
            _weighted_score(0.42, provenance),
            "contextual",
            contextual,
            sorted(contextual_terms),
            provenance,
        )
    return _coverage_detail(0.0, "absent", [], sorted(surface_terms | semantic_terms), [])


def _term_coverage(
    term: str,
    card_profile: dict[str, object],
) -> tuple[float, str, str, list[dict[str, str]]]:
    card_terms = card_profile["all"]
    if term in card_terms:
        provenance = _term_provenance(card_profile, term)
        return _weighted_score(1.0, provenance), "explicit", term, provenance
    semantic_aliases = {
        _canonical_slot_term(alias)
        for alias in SLOT_EQUIVALENCES.get(term, set())
        if _canonical_slot_term(alias)
    }
    semantic = sorted(semantic_aliases & card_terms)
    if semantic:
        provenance = _term_provenance(card_profile, semantic[0])
        return _weighted_score(0.72, provenance), "semantic", semantic[0], provenance
    contextual_aliases = {
        _canonical_slot_term(alias)
        for alias in CONTEXTUAL_EQUIVALENCES.get(term, set())
        if _canonical_slot_term(alias)
    }
    contextual = sorted(contextual_aliases & card_terms)
    if contextual:
        provenance = _term_provenance(card_profile, contextual[0])
        return _weighted_score(0.42, provenance), "contextual", contextual[0], provenance
    return 0.0, "absent", "", []


def _coverage_detail(
    score: float,
    kind: str,
    matched: list[str],
    expected: list[str],
    provenance: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "score": round(score, 3),
        "kind": kind,
        "matched": matched,
        "expected": expected,
        "provenance": provenance or [],
        "source_quality": _source_quality(provenance or []),
    }


def _weighted_score(base: float, provenance: list[dict[str, str]]) -> float:
    if not provenance:
        return base
    return base * _source_quality(provenance)


def _source_quality(provenance: list[dict[str, str]]) -> float:
    if not provenance:
        return 0.0
    return round(
        max(SOURCE_WEIGHTS.get(str(item.get("source") or ""), 0.5) for item in provenance),
        3,
    )


def _overall_source_quality(details: dict[str, dict[str, object]]) -> float:
    weighted_total = 0.0
    score_total = 0.0
    for key, detail in details.items():
        if key == "effect":
            continue
        score = float(detail.get("score") or 0.0)
        if score <= 0:
            continue
        quality = float(detail.get("source_quality") or 0.0)
        weighted_total += score * quality
        score_total += score
    if score_total <= 0:
        return 0.0
    return round(weighted_total / score_total, 3)


def _provenance_for_terms(
    card_profile: dict[str, object],
    terms: list[str],
) -> list[dict[str, str]]:
    provenance: list[dict[str, str]] = []
    for term in terms:
        provenance.extend(_annotate_provenance(_term_provenance(card_profile, term), term, term))
    return _dedupe_provenance(provenance)


def _term_provenance(
    card_profile: dict[str, object],
    term: str,
) -> list[dict[str, str]]:
    occurrences = card_profile.get("occurrences") or {}
    if not isinstance(occurrences, dict):
        return []
    values = occurrences.get(term) or []
    return [dict(value) for value in values[:3] if isinstance(value, dict)]


def _annotate_provenance(
    provenance: list[dict[str, str]],
    expected: str,
    matched: str,
) -> list[dict[str, str]]:
    annotated = []
    for item in provenance:
        record = dict(item)
        record["expected"] = expected
        record["matched_term"] = matched
        annotated.append(record)
    return _dedupe_provenance(annotated)


def _dedupe_provenance(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    deduped = []
    for item in items:
        key = (
            item.get("source", ""),
            item.get("matched", ""),
            item.get("snippet", ""),
            item.get("expected", ""),
            item.get("matched_term", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def _combined_kind(kinds: list[str]) -> str:
    if not kinds or all(kind == "absent" for kind in kinds):
        return "absent"
    if all(kind == "explicit" for kind in kinds):
        return "explicit"
    if any(kind == "explicit" for kind in kinds) or any(kind == "semantic" for kind in kinds):
        return "semantic"
    return "contextual"


def _slot_populated(structured, key: str) -> bool:
    return bool(getattr(structured, key).value)


def _simple_stem(concept: str) -> str:
    if concept.endswith("ing") and len(concept) > 5:
        return concept[:-3]
    if concept.endswith("ion") and len(concept) > 6:
        return concept[:-3]
    if concept.endswith("al") and len(concept) > 6:
        return concept[:-2]
    if concept.endswith("s") and len(concept) > 4:
        return concept[:-1]
    return concept


def _snippet(text: str, limit: int = 120) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _canonical_slot_term(term: str) -> str:
    normalized = term.lower().strip().replace("_", " ")
    aliases = {
        "approval": "approval",
        "authorization": "authorization",
        "congress": "congress",
        "congressional": "congress",
        "conflict": "conflict",
        "diplomatic": "diplomacy",
        "diplomacy": "diplomacy",
        "escalate": "escalate",
        "escalates": "escalate",
        "escalating": "escalate",
        "escalation": "escalate",
        "nuclear": "nuclear",
        "nuc": "nuclear",
        "president": "president",
        "presidential": "president",
        "restrains": "restrain",
        "restraining": "restrain",
        "restricts": "restrict",
        "restricting": "restrict",
        "stops": "stop",
        "stopping": "stop",
        "prevents": "prevent",
        "preventing": "prevent",
    }
    if normalized in aliases:
        return aliases[normalized]
    return _simple_stem(normalized)


def _cue_matches(text: str) -> dict[str, bool]:
    lowered = text.lower()
    terms = _terms(text)
    return {
        "indict": _has_phrase(lowered, INDICT_CUES),
        "mitigate": bool(terms & MITIGATION_CUES) or _has_phrase(lowered, MITIGATION_CUES),
        "non_unique": _has_phrase(lowered, NON_UNIQUE_CUES),
        "turn": bool(terms & TURN_CUES) or _has_phrase(lowered, TURN_CUES),
    }


def _has_phrase(text: str, phrases: set[str]) -> bool:
    for phrase in phrases:
        if " " not in phrase and "-" not in phrase:
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return True
            continue
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"\b"
        if re.search(pattern, text):
            return True
    return False


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    terms = _terms(text)
    return bool(terms & NEGATION_CUES) or bool(
        re.search(r"\b(?:no|not|cannot|doesn't|doesn['’]?t)\b", lowered)
    )


def _is_non_unique_response(
    claim_terms: set[str],
    card_text: str,
    cues: dict[str, bool],
) -> bool:
    if not cues["non_unique"]:
        return False
    lowered = card_text.lower()
    if re.search(r"\b(?:non-unique|nonunique|status quo|squo)\b", lowered):
        return True
    return bool(claim_terms & {"unique", "uniquely", "new"})


def _direction(claim_terms: set[str], card_terms: set[str]) -> str:
    claim_positive = bool(claim_terms & POSITIVE_DIRECTION_CUES)
    claim_negative = bool(claim_terms & NEGATIVE_DIRECTION_CUES)
    card_positive = bool(card_terms & POSITIVE_DIRECTION_CUES)
    card_negative = bool(card_terms & NEGATIVE_DIRECTION_CUES)
    if claim_positive and card_positive:
        return "supports"
    if claim_negative and card_negative:
        return "supports"
    if claim_positive and card_negative:
        return "opposes"
    if claim_negative and card_positive:
        return "opposes"
    return "unknown"


def _front_support_assessment(
    *,
    claim: str,
    front_text: str,
    claim_terms: set[str],
) -> ClaimRelationAssessment | None:
    if not front_text:
        return None
    front_terms = _concepts(front_text)
    if not front_terms:
        return None
    overlap = len(claim_terms & front_terms) / len(claim_terms)
    claim_mechanism = parse_mechanism(claim)
    front_mechanism = parse_mechanism(front_text)
    mech = mechanism_match(claim_mechanism, front_mechanism)
    direction = _direction(claim_terms, front_terms)
    if direction == "opposes":
        return None
    if overlap >= 0.55 or (overlap >= 0.35 and mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.88),
            overlap,
            mech,
            ["front matter substantially proves the claim"],
        )
    return None


def _direct_effect_opposition(claim_mechanism, card_terms: set[str]) -> bool:
    effects = (
        claim_mechanism.effect_groups
        - claim_mechanism.actor_groups
        - claim_mechanism.cause_groups
        - claim_mechanism.generic_terms
    )
    if not effects:
        effects = (
            claim_mechanism.object_groups
            - claim_mechanism.actor_groups
            - claim_mechanism.cause_groups
            - claim_mechanism.generic_terms
        )
    expanded_effects = set(effects)
    for effect in effects:
        expanded_effects.add(GENERIC_EQUIVALENCES.get(effect, effect))
    return bool(expanded_effects & card_terms)


def _confidence(overlap: float, mechanism: float, base: float) -> float:
    return round(max(0.0, min(1.0, base * 0.45 + overlap * 0.35 + mechanism * 0.2)), 3)


def _assessment(
    relationship: ClaimRelationship,
    confidence: float,
    overlap: float,
    mechanism: float,
    reasons: list[str],
) -> ClaimRelationAssessment:
    directness = _directness(overlap, mechanism, relationship, reasons)
    return ClaimRelationAssessment(
        relationship=relationship,
        confidence=round(confidence, 3),
        overlap=round(overlap, 3),
        mechanism=round(mechanism, 3),
        directness=round(directness, 3),
        reasons=reasons,
    )


def _directness(
    overlap: float,
    mechanism: float,
    relationship: ClaimRelationship,
    reasons: list[str],
) -> float:
    base = max(overlap * 0.65, mechanism)
    if relationship in {
        ClaimRelationship.SUPPORTS,
        ClaimRelationship.CONTRADICTS,
        ClaimRelationship.TURNS,
        ClaimRelationship.NON_UNIQUE,
    }:
        base += 0.12
    if any("front matter" in reason or "directly" in reason for reason in reasons):
        base += 0.18
    if relationship in {ClaimRelationship.BACKGROUND, ClaimRelationship.QUALIFIES}:
        base -= 0.08
    if relationship == ClaimRelationship.IRRELEVANT:
        base = 0.0
    return max(0.0, min(1.0, base))
