from backend.rag.mechanism import mechanism_match, parse_mechanism


def test_mechanism_parser_separates_automation_escalation_from_revenue():
    query = parse_mechanism("AI escalates because of automation")
    escalation_card = parse_mechanism(
        "AI improves warning accuracy and reduces unintended escalation."
    )
    revenue_card = parse_mechanism(
        "AI behavior manipulation increases sportsbook revenue."
    )

    assert "ai" in query.actor_groups
    assert "automation" in query.cause_groups
    assert "escalat" in query.effect_groups
    assert mechanism_match(query, escalation_card) > mechanism_match(query, revenue_card)


def test_mechanism_parser_keeps_distinct_phrases_without_static_aliases():
    query = parse_mechanism("Human oversight prevents AI mistakes")
    government_card = parse_mechanism("Government control over state borders is weak.")

    assert "human_oversight" in query.object_groups
    assert "government_control" in government_card.object_groups
    assert mechanism_match(query, government_card) < 0.3


def test_mechanism_normalizes_behavioral_optimization_language():
    query = parse_mechanism(
        "How do sportsbooks use machine learning to maximize bettor engagement?"
    )
    card = parse_mechanism(
        "AI tracks gambling habits and creates individualized offers."
    )
    unrelated = parse_mechanism("Bitcoin transactions settle on a public ledger.")

    assert "artificial_intelligence" in query.object_groups
    assert "artificial_intelligence" in card.object_groups
    assert "wagering" in query.object_groups
    assert "wagering" in card.object_groups
    assert "behavioral_tracking" in card.object_groups
    assert mechanism_match(query, card) > mechanism_match(query, unrelated)
