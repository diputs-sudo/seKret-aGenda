from backend.rag.fusion import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_unions_sources_by_card_id():
    results = reciprocal_rank_fusion(
        {
            "fast_vector": [
                {"card_id": "card-1", "score": 0.8, "tag": "AI caution"},
                {"card_id": "card-2", "score": 0.7, "tag": "Regulation"},
            ],
            "sqlite_fts": [
                {"card_id": "card-2", "score": 0.9, "tag": "Regulation"},
                {"card_id": "card-1", "score": 0.6, "tag": "AI caution"},
            ],
        }
    )

    assert {row["card_id"] for row in results} == {"card-1", "card-2"}
    assert results[0]["retrieval_score"] == results[1]["retrieval_score"]
    assert results[0]["source_ranks"]
    assert results[0]["source_scores"]
