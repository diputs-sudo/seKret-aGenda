from backend.rag import SearchMode, parse_query_intent


def test_parse_query_intent_extracts_filters_and_opponent_claim():
    intent = parse_query_intent(
        'author:Tucker year:2020 section:"AT: Hyperwar" '
        "Opponent says AI escalates because of automation.",
        mode="draft",
    )

    assert intent.mode == "draft"
    assert intent.author_filter == "Tucker"
    assert intent.year_min == 2020
    assert intent.year_max == 2020
    assert intent.section_filter == "AT: Hyperwar"
    assert intent.opponent_claim == "AI escalates because of automation"
    assert "automation" in intent.concepts
    assert "control" in intent.concepts
    assert "escalation" in intent.concepts
    assert "author:Tucker" not in intent.search_text


def test_parse_query_intent_detects_lookup_and_search_modes():
    assert parse_query_intent("Tucker 20").search_mode == SearchMode.CITATION
    assert parse_query_intent("Tucker").search_mode == SearchMode.AUTHOR
    assert parse_query_intent("AT: Hyperwar").search_mode == SearchMode.SECTION
    assert (
        parse_query_intent("Opponent says AI escalates.").search_mode
        == SearchMode.ARGUMENT
    )
    assert (
        parse_query_intent("Human oversight prevents AI mistakes.").search_mode
        == SearchMode.GENERAL
    )


def test_parse_query_intent_tracks_stopwords_and_phrase_concepts():
    intent = parse_query_intent("Penguins on Mars")

    assert "on" in intent.ignored_stopwords
    assert "on" not in intent.concepts

    oversight = parse_query_intent("Human oversight prevents AI mistakes.")

    assert "human_control" in oversight.phrase_concepts
