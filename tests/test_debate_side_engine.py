from backend.debate import (
    ClaimRelation,
    DebateIntent,
    DebateSide,
    DebateSideEngine,
    Owner,
    Perspective,
    RoundContext,
    build_retrieval_probes,
    parse_debate_query,
    parse_structured_claim,
)
from backend.debate.relationships import claim_component_coverage
from backend.debate.relationships import classify_claim_relationship
from backend.debate.side_engine import _final_score


def test_debate_query_consumes_opponent_control_language():
    query = parse_debate_query(
        "opponent argues AI sports betting increases addiction"
    )

    assert query.intent == DebateIntent.ANSWER
    assert query.perspective == Perspective.OPPONENT
    assert query.opponent_claim == "AI sports betting increases addiction"
    assert query.semantic_query == "AI sports betting increases addiction"
    assert "opponent" not in query.topics
    assert "argues" not in query.topics


def test_debate_query_commands_set_intent():
    query = parse_debate_query("their> AI personalized betting revenue")

    assert query.intent == DebateIntent.THEIR_EVIDENCE
    assert query.semantic_query == "AI personalized betting revenue"
    assert query.control_language == ["their>"]


def test_side_engine_preserves_our_and_opponent_lanes():
    engine = DebateSideEngine()
    result = engine.build(
        "opponent says AI personalization increases betting addiction",
        [
            _card(
                "our-turn",
                owner="us",
                relationship="CONTRADICTS",
                tag="AI personalization reduces betting addiction by limiting targeting.",
                score=0.92,
            ),
            _card(
                "their-card",
                owner="opponent",
                relationship="SUPPORTS",
                tag="AI personalization increases betting addiction.",
                score=0.95,
            ),
            _card(
                "shared-defense",
                owner="shared",
                relationship="QUALIFIES",
                tag="Rules prohibit individualized promotions and reduce bettor targeting.",
                score=0.7,
            ),
        ],
        round_context=RoundContext(
            our_side=DebateSide.NEGATIVE,
            opponent_side=DebateSide.AFFIRMATIVE,
        ),
        limit_per_lane=5,
    )

    our_ids = [candidate.card_id for candidate in result.our_lane.candidates]
    their_ids = [candidate.card_id for candidate in result.opponent_lane.candidates]

    assert "our-turn" in our_ids
    assert "their-card" not in our_ids
    assert "their-card" in their_ids
    assert result.our_lane.candidates[0].owner == Owner.US
    assert result.our_lane.candidates[0].relationship == "CONTRADICTS"


def test_their_evidence_mode_prefers_opponent_owned_cards():
    engine = DebateSideEngine()
    result = engine.build(
        "their> AI personalization increases betting addiction",
        [
            _card(
                "our-answer",
                owner="us",
                relationship="CONTRADICTS",
                tag="AI personalization reduces betting addiction by limiting targeting.",
                score=0.95,
            ),
            _card(
                "their-card",
                owner="opponent",
                relationship="SUPPORTS",
                tag="AI personalization increases betting addiction.",
                score=0.7,
            ),
        ],
        limit_per_lane=5,
    )

    assert result.opponent_lane.candidates[0].card_id == "their-card"
    assert result.opponent_lane.candidates[0].owner_utility == 1.0


def test_answer_query_builds_counterclaim_and_attack_probes():
    query = parse_debate_query("opponent says Trump nuclear posture deletes diplomacy")
    probes = build_retrieval_probes(query)
    probe_text = {probe.kind: probe.text for probe in probes}

    assert probe_text["original"] == "Trump nuclear posture deletes diplomacy"
    assert "does not" in probe_text["denial"]
    assert probe_text["no_link"] == "Trump nuclear posture does not determine diplomacy"
    assert "protects or strengthens" in probe_text["turn"]
    assert "trump nuclear posture diplomacy" in probe_text["lexical"]


def test_structured_claim_parses_prevention_claim():
    structured = parse_structured_claim(
        "Congress approval prevents Trump from escalating nuclear conflict"
    )

    assert structured.relation == ClaimRelation.PREVENTS
    assert structured.subject.value == "Congress approval"
    assert structured.target_actor.value == "Trump"
    assert structured.target_action.value == "escalate"
    assert structured.target_object.value == "nuclear conflict"
    assert structured.confidence >= 0.9


def test_prevention_claim_probes_are_structured_and_grammatical():
    query = parse_debate_query(
        "opponent says Congress approval prevents Trump from escalating nuclear conflict"
    )
    probe_text = {probe.kind: probe.text for probe in build_retrieval_probes(query)}

    assert probe_text["denial"] == (
        "Congressional approval does not prevent Trump from escalating nuclear conflict"
    )
    assert probe_text["turn"] == (
        "Congressional approval increases or enables Trump escalating nuclear conflict"
    )
    assert probe_text["circumvention"] == (
        "Trump can escalate nuclear conflict despite Congressional approval"
    )
    assert "Trump's ability to escalate nuclear conflict" in probe_text["no_link"]
    assert "improves Trump from escalating nuclear conflict" not in " ".join(
        probe_text.values()
    )


def test_claim_coverage_does_not_overcredit_generic_escalation():
    coverage = claim_component_coverage(
        "Congress approval prevents Trump from escalating nuclear conflict",
        "It escalates every theater.",
    )

    slots = coverage["slots"]
    details = coverage["slot_details"]
    assert coverage["score"] < 0.3
    assert slots["subject"] == 0.0
    assert slots["target_actor"] == 0.0
    assert slots["target_action"] == 1.0
    assert slots["target_object"] < 0.35
    assert details["target_object"]["kind"] == "absent"
    assert "missing subject" in coverage["warnings"]
    assert "missing relation" in coverage["warnings"]


def test_claim_coverage_rejects_unrelated_alliance_credibility_tag():
    coverage = claim_component_coverage(
        "Congress approval prevents Trump from escalating nuclear conflict",
        "It's a win-win solution. Thru the aff we revitalize alliances by signaling credibility and commitment.",
    )

    assert coverage["score"] == 0.0
    assert all(
        coverage["slots"][slot] == 0.0
        for slot in (
            "subject",
            "relation",
            "target_actor",
            "target_action",
            "target_object",
        )
    )


def test_claim_coverage_gives_partial_credit_to_congressional_signaling():
    coverage = claim_component_coverage(
        "Congress approval prevents Trump from escalating nuclear conflict",
        "Congressional signaling alone forces Trump to slow down.",
    )

    slots = coverage["slots"]
    details = coverage["slot_details"]
    assert 0.35 <= coverage["score"] <= 0.5
    assert slots["subject"] == 0.5
    assert slots["relation"] >= 0.7
    assert slots["target_actor"] == 1.0
    assert slots["target_action"] == 0.0
    assert slots["target_object"] == 0.0
    assert details["subject"]["kind"] == "semantic"
    assert "missing target_object" in coverage["warnings"]


def test_prevention_circumvention_gets_attack_alignment():
    claim = "Congress approval prevents Trump from escalating nuclear conflict"
    card = "It's unchecked. He circumvents military buffers through legal loopholes."

    coverage = claim_component_coverage(claim, card)
    relationship = classify_claim_relationship(claim, card)

    assert coverage["attack_alignment"]["type"] == "CIRCUMVENTION"
    assert coverage["attack_alignment"]["score"] >= 0.55
    assert relationship.relationship.value == "CONTRADICTS"
    assert "circumvention" in " ".join(relationship.reasons)


def test_claim_coverage_records_match_provenance_by_card_field():
    coverage = claim_component_coverage(
        "Congress approval prevents Trump from escalating nuclear conflict",
        {
            "tag": "Displayed tag does not contain the match.",
            "body": "Congressional authorization prevents executive nuclear war.",
        },
    )

    subject_provenance = coverage["slot_details"]["subject"]["provenance"]
    relation_provenance = coverage["slot_details"]["relation"]["provenance"]
    object_provenance = coverage["slot_details"]["target_object"]["provenance"]

    assert subject_provenance
    assert relation_provenance
    assert object_provenance
    assert {item["source"] for item in subject_provenance} == {"body"}
    assert relation_provenance[0]["source"] == "body"
    assert "prevents" in relation_provenance[0]["snippet"]
    assert any(item["matched"] == "nuclear" for item in object_provenance)


def test_claim_coverage_discounts_citation_only_argument_terms():
    claim = "Congress approval prevents Trump from escalating nuclear conflict"
    body_coverage = claim_component_coverage(
        claim,
        {
            "tag": "No visible match.",
            "body": "Congressional authorization prevents executive nuclear war.",
        },
    )
    citation_coverage = claim_component_coverage(
        claim,
        {
            "tag": "No visible match.",
            "citation": "Congressional authorization prevents executive nuclear war.",
        },
    )

    assert body_coverage["source_quality"] > citation_coverage["source_quality"]
    assert body_coverage["slots"]["target_object"] > 0.7
    assert citation_coverage["slots"]["target_object"] < 0.25
    assert citation_coverage["score"] < body_coverage["score"]


def test_final_score_rewards_attack_alignment_and_source_quality():
    base = {
        "retrieval_score": 0.55,
        "topic_score": 0.2,
        "mechanism_score": 0.35,
        "warrant_score": 0.35,
        "relationship_confidence": 0.56,
        "directness": 0.5,
        "coverage_score": 0.55,
        "evidence_strength": 0.8,
        "owner_utility": 1.0,
        "relationship_utility": 0.95,
        "side_utility": 0.5,
    }

    no_attack = _final_score(
        **base,
        attack_score=0.0,
        source_quality=0.95,
    )
    aligned = _final_score(
        **base,
        attack_score=0.9,
        source_quality=0.95,
    )
    citation_heavy = _final_score(
        **base,
        attack_score=0.9,
        source_quality=0.2,
    )

    assert aligned > no_attack
    assert aligned > citation_heavy


def test_weak_our_answer_is_audited_but_not_returned():
    engine = DebateSideEngine()
    query = parse_debate_query("opponent says Trump nuclear posture deletes diplomacy")
    assessed = engine.assess_candidates(
        query,
        [
            _card(
                "weak-answer",
                owner="us",
                relationship="CONTRADICTS",
                tag="AND causes deterrence break-down; an existential great power war.",
                citation="Santos 26 nuclear posture diplomacy",
                score=0.7,
            )
        ],
    )
    result = engine.build_from_assessed(query, assessed, limit_per_lane=5)
    decision = engine.lane_decision(assessed[0], query.intent, "our")

    assert result.our_lane.candidates == []
    assert decision["eligible"] is True
    assert decision["accepted"] is False
    assert "confidence" in decision["reason"] or "directness" in decision["reason"]


def test_opponent_lane_does_not_accept_conflict_cards():
    engine = DebateSideEngine()
    result = engine.build(
        "opponent says Trump nuclear posture deletes diplomacy",
        [
            _card(
                "their-indict",
                owner="opponent",
                relationship="INDICTS",
                tag="Claims that nuclear posture causes diplomatic collapse overstate the evidence.",
                score=0.9,
            ),
            _card(
                "their-support",
                owner="opponent",
                relationship="SUPPORTS",
                tag="Trump nuclear posture deletes diplomacy.",
                score=0.9,
            ),
        ],
        limit_per_lane=5,
    )

    opponent_ids = [candidate.card_id for candidate in result.opponent_lane.candidates]
    assert "their-support" in opponent_ids
    assert "their-indict" not in opponent_ids


def _card(
    card_id,
    *,
    owner,
    relationship,
    tag="",
    citation="",
    score=0.8,
):
    return {
        "card_id": card_id,
        "tag": tag,
        "citation": citation,
        "retrieval_score": score,
        "metadata": {"owner": owner},
        "candidate_assessment": {
            "relationship": relationship,
            "confidence": score,
            "relevance_score": score,
            "topic_match": score,
            "mechanism_match": score,
            "warrant_match": score,
            "evidence_strength": 0.8,
        },
    }
