from backend.rag import ArgumentBuilder, validate_sources


def test_argument_builder_clusters_and_diversifies_cards():
    cards = [
        _card("a", "Smith 24", "Doc A", "AT: Harm", "Economic harm is overstated.", 0.9),
        _card("b", "Smith 24", "Doc A", "AT: Harm", "Economic harm is overstated.", 0.85),
        _card("c", "Jones 25", "Doc B", "AT: Harm", "Status quo solves the harm.", 0.8),
    ]

    bundle = ArgumentBuilder().build("Opponent says the plan causes harm.", cards, limit=2)

    assert bundle.source_status == "BACKFILE-SOURCED"
    assert bundle.clusters
    assert len(bundle.cards) == 2
    assert {card["card_id"] for card in bundle.cards} == {"a", "c"}


def test_argument_bundle_reports_analysis_only_without_cards():
    bundle = ArgumentBuilder().build("Penguins on Mars", [], limit=3)

    assert bundle.source_status == "ANALYSIS ONLY"
    assert bundle.cards == []
    assert bundle.uncertainty


def test_source_validator_finds_valid_and_invalid_citations():
    card = _card("a", "Smith 24", "Doc A", "AT: Harm", "Economic harm is overstated.", 0.9)
    bundle = ArgumentBuilder().build("harm", [card], limit=1)

    report = validate_sources(
        "Smith 24 answers this. Fake 99 should not be trusted.",
        bundle,
    )

    assert "Smith 24" in report.valid_citations
    assert "Fake 99" in report.invalid_citations
    assert report.generated_claims[0].supporting_card_ids == ["a"]


def test_argument_builder_chooses_main_claim_from_best_cluster():
    cards = [
        _card("weird", "Bitcoin 24", "Doc C", "AT: Other", "Bitcoin transactions are slow.", 0.82),
        _card("a", "Pampus 25", "Doc A", "AT: AI", "AI tracks user habits.", 0.76),
        _card("b", "Tonko 25", "Doc B", "AT: AI", "AI personalizes user offers.", 0.74),
        _card("c", "WSC 25", "Doc C", "AT: AI", "AI optimizes user engagement.", 0.72),
    ]

    bundle = ArgumentBuilder().build(
        "AI user habits engagement",
        cards,
        limit=3,
    )

    assert bundle.main_claim == "AI tracks user habits."
    assert bundle.clusters[0].confidence > bundle.clusters[1].confidence


def _card(card_id, card_name, document, section, tag, score):
    return {
        "card_id": card_id,
        "card_name": card_name,
        "document": document,
        "section": section,
        "tag": tag,
        "citation": f"{card_name}, Example.",
        "reranker_score": score,
        "highlights": [{"text": tag}],
    }
