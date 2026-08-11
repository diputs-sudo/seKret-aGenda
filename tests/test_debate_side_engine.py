from backend.debate import (
    DebateIntent,
    DebateSide,
    DebateSideEngine,
    Owner,
    Perspective,
    RoundContext,
    build_retrieval_probes,
    parse_debate_query,
)


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
    assert "preserves improves diplomacy" in probe_text["counterclaim"]
    assert "causal link is weak" in probe_text["no_link"]
    assert "claimed harm" in probe_text["turn"]
    assert "trump nuclear posture diplomacy" in probe_text["lexical"]


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
