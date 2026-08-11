import json
from pathlib import Path

from backend.debate import ClaimRelationship, classify_claim_relationship

ROOT = Path(__file__).resolve().parents[1]


def test_relationship_benchmark():
    cases = json.loads(
        (ROOT / "tests" / "debate" / "relationships" / "benchmark.json").read_text(
            encoding="utf-8"
        )
    )

    misses = []
    for case in cases:
        assessment = classify_claim_relationship(case["claim"], case["card"])
        expected = ClaimRelationship(case["expected"])
        if assessment.relationship != expected:
            misses.append(
                {
                    "claim": case["claim"],
                    "card": case["card"],
                    "expected": expected.value,
                    "actual": assessment.relationship.value,
                    "assessment": assessment.to_dict(),
                }
            )

    assert not misses


def test_supporting_card_is_not_our_answer():
    from backend.debate import DebateSideEngine

    result = DebateSideEngine().build(
        "opponent says Trump nuclear posture deletes diplomacy",
        [
            {
                "card_id": "goessmann",
                "tag": "Trump's nuclear posture deletes diplomacy and guarantees accidental escalation.",
                "metadata": {"owner": "us"},
                "retrieval_score": 0.95,
                "candidate_assessment": {
                    "relationship": "QUALIFIES",
                    "confidence": 0.9,
                    "topic_match": 0.9,
                    "mechanism_match": 0.7,
                    "warrant_match": 0.9,
                    "evidence_strength": 0.8,
                },
            }
        ],
    )

    assert result.our_lane.candidates == []
    assert result.opponent_lane.candidates == []
