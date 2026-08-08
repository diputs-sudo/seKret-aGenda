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
    assert "conflict_escalation" in query.effect_groups
    assert mechanism_match(query, escalation_card) > mechanism_match(query, revenue_card)


def test_mechanism_parser_does_not_treat_generic_control_as_human_control():
    query = parse_mechanism("Human oversight prevents AI mistakes")
    government_card = parse_mechanism("Government control over state borders is weak.")

    assert "human_control" in query.object_groups
    assert "government_control" in government_card.object_groups
    assert mechanism_match(query, government_card) < 0.3
