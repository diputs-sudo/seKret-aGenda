from backend.rag import FullContextReranker, Relationship, RelevanceGate, parse_query_intent, reranker_input


def test_reranker_input_contains_complete_card_context():
    intent = parse_query_intent("Opponent says AI escalates because of automation.")
    card = {
        "section": "AT: Hyperwar",
        "tag": "AI is risk-averse.",
        "card_name": "Tucker 20",
        "author": "Tucker",
        "year": 2020,
        "citation": "Tucker 20, Defense One.",
        "highlights": [{"text": "AI can be more cautious than humans."}],
        "body": "Machines lower confidence under limited data.",
    }

    text = reranker_input(intent, card)

    assert "Query:\nAI escalates because of automation" in text
    assert "Section:\nAT: Hyperwar" in text
    assert "Tag:\nAI is risk-averse." in text
    assert "Citation:\nTucker 20 Tucker 2020 Tucker 20, Defense One." in text
    assert "Highlights:\nAI can be more cautious than humans." in text
    assert "Body:\nMachines lower confidence under limited data." in text


def test_full_context_reranker_downranks_same_section_only_match():
    intent = parse_query_intent("Opponent says AI escalates because of automation.")
    cards = [
        {
            "card_id": "shapiro",
            "retrieval_score": 0.05,
            "section": "AT: Hyperwar",
            "tag": "Regulations fail.",
            "card_name": "Shapiro 26",
            "highlights": [
                {"text": "EU AI Act causes companies to relocate to America."}
            ],
        },
        {
            "card_id": "cox",
            "retrieval_score": 0.02,
            "section": "AT: Hyperwar",
            "tag": "AI defuses escalation.",
            "card_name": "Cox 21",
            "highlights": [
                {"text": "AI improves warning accuracy and reduces unintended escalation."}
            ],
            "body": "AI systems help decision-makers avoid false alarms in war.",
        },
        {
            "card_id": "goldfarb",
            "retrieval_score": 0.01,
            "section": "AT: Hyperwar",
            "tag": "Humans maintain control and stabilize dynamics.",
            "card_name": "Goldfarb 22",
            "highlights": [
                {
                    "text": "Human judgment remains central to military AI decision-making."
                }
            ],
        },
    ]

    results = FullContextReranker().rerank(intent, cards)

    assert results[0]["card_id"] == "cox"
    assert results[0]["reranker_score"] > results[1]["reranker_score"]
    assert results[0]["reranker_assessment"]["mechanism_match"] > 0
    assert results[0]["candidate_assessment"]["relationship"] == Relationship.CONTRADICTS.value
    rejected = [row for row in results if row["card_id"] in {"goldfarb", "shapiro"}]
    assert all(row["candidate_assessment"]["rejection_reason"] for row in rejected)


def test_relevance_gate_rejects_irrelevant_mechanism_cards():
    intent = parse_query_intent("Opponent says AI escalates because of automation.")
    cards = [
        {
            "card_id": "cox",
            "retrieval_score": 0.02,
            "section": "AT: Hyperwar",
            "tag": "AI defuses escalation.",
            "card_name": "Cox 21",
            "highlights": [
                {"text": "AI improves warning accuracy and reduces unintended escalation."}
            ],
        },
        {
            "card_id": "revenue",
            "retrieval_score": 0.05,
            "section": "AT: AI",
            "tag": "AI increases betting revenue.",
            "card_name": "Market 25",
            "highlights": [
                {"text": "AI behavior manipulation increases sportsbook revenue."}
            ],
        },
    ]

    reranked = FullContextReranker().rerank(intent, cards)
    accepted, rejected = RelevanceGate().split(reranked)

    assert [card["card_id"] for card in accepted] == ["cox"]
    assert [card["card_id"] for card in rejected] == ["revenue"]
    assert rejected[0]["candidate_assessment"]["relationship"] in {
        Relationship.BACKGROUND.value,
        Relationship.IRRELEVANT.value,
    }


def test_relevance_gate_rejects_cyber_router_card_for_ai_escalation():
    intent = parse_query_intent("Opponent says AI escalates because of automation.")
    cards = [
        {
            "card_id": "router",
            "retrieval_score": 0.08,
            "section": "Cyber crime",
            "tag": "Outdated routers increase cyber crime.",
            "card_name": "Remington 25",
            "highlights": [
                {"text": "Outdated routers create cyber vulnerabilities and crime."}
            ],
        }
    ]

    reranked = FullContextReranker().rerank(intent, cards)
    accepted, rejected = RelevanceGate().split(reranked)

    assert accepted == []
    assert rejected[0]["candidate_assessment"]["relationship"] == Relationship.IRRELEVANT.value
    assert "ai" in rejected[0]["candidate_assessment"]["missing_concepts"]
    assert "automation" in rejected[0]["candidate_assessment"]["missing_concepts"]
    assert "escalat" in rejected[0]["candidate_assessment"]["missing_concepts"]


def test_reranker_score_does_not_ceiling_on_repeated_phrase_matches():
    intent = parse_query_intent("AI sports betting")
    cards = [
        {
            "card_id": "pampus",
            "retrieval_score": 0.05,
            "section": "AT: State money used for addiction rehab",
            "tag": (
                "Turn: Nationally unregulated market causes companies to use AI "
                "for money in sports betting."
            ),
            "card_name": "Pampus 25",
            "highlights": [
                {
                    "text": (
                        "AI used grow revenue in sports betting and bans technologies "
                        "that manipulate habits."
                    )
                }
            ],
            "body": (
                "AI sports betting operators use automation to grow revenue in the "
                "betting market."
            ),
        }
    ]

    result = FullContextReranker().rerank(intent, cards)[0]

    assert 0.7 <= result["reranker_score"] < 0.9
