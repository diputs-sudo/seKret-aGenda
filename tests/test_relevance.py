from backend.rag import RelevanceReranker


def test_relevance_reranker_rejects_same_section_unrelated_tag():
    cards = [
        {
            "score": 0.9,
            "section": "AT: hyperwar",
            "tag": "2. Regulations fail",
            "card_name": "Shapiro 26",
            "metadata": {
                "highlight_text": "EU AI Act companies go elsewhere. They go to America."
            },
        },
        {
            "score": 0.8,
            "section": "AT: hyperwar",
            "tag": "AI defuses escalation.",
            "card_name": "Cox 21",
            "metadata": {
                "highlight_text": "AI improves false positives and reduces unintended escalation."
            },
        },
        {
            "score": 0.7,
            "section": "AT: hyperwar",
            "tag": "Humans maintain control and stabilize dynamics.",
            "card_name": "Goldfarb 22",
            "metadata": {
                "highlight_text": "Humans engineer objectives and judgment remains important in war, which stabilizes dynamics and checks aggression."
            },
        },
    ]

    results = RelevanceReranker().rerank("automation escalation", cards, limit=3)
    names = [card["card_name"] for card in results]

    assert "Cox 21" in names
    assert "Goldfarb 22" in names
    assert "Shapiro 26" not in names
