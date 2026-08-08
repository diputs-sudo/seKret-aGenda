#!/usr/bin/env python3
"""Print every pipeline step for one debate-generation test prompt."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.llm import LLMError, OllamaLLM
from backend.prompt import GenerationMode, PromptBuilder
from backend.rag import RetrievalEngine, SearchRequest

DEFAULT_PROMPT = "Opponent says AI escalates because of automation."


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--query", default=DEFAULT_PROMPT)
    parser.add_argument("--mode", choices=["draft", "explain", "summarize"], default="draft")
    parser.add_argument("--candidates", type=int, default=20)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--llm", action="store_true", help="Call local Gemma through Ollama.")
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    engine = RetrievalEngine(args.db)

    _step("Step 1. User Prompt")
    _print(args.query)
    print("Nothing fancy.")

    _step("Step 2. Intent Detection")
    intent = _detect_intent(args.mode)
    _print(f"Mode: {args.mode}")
    print("Result:")
    _print(intent)
    print("No AI required.")

    _step("Step 3. Embedding")
    embedding_debug = _debug_embedding(args.query)
    print("embedding = embed(query)")
    print("Status: placeholder until the real embedding model is wired in.")
    _print(f"Debug vector id: {embedding_debug['id']}")
    _print(f"Debug dimensions: {embedding_debug['dimensions']}")
    _print(f"Debug preview: {embedding_debug['preview']}")

    _step("Step 4. Vector Search")
    print("Query Vector")
    print("Result:")
    _print(f"Top {args.candidates} nearest cards")
    print()
    print("Status: Chroma/vector search is not wired yet.")
    print("Fallback running today: SQLite FTS candidate retrieval through RetrievalEngine.")
    candidates = engine.search(SearchRequest(query=args.query, limit=args.candidates))
    _print_card_list(candidates)

    _step("Step 5. Reranking")
    reranked = _rerank(candidates, args.top)
    _print(f"Input: Top {len(candidates)} candidates")
    print("Operation:")
    print("Remove low-score cards, group by section/tag, keep strongest cards.")
    print("Result:")
    _print(f"Top {len(reranked)}")
    _print_card_list(reranked)

    _step("Step 6. Argument Builder")
    argument = _build_argument(reranked)
    _print_argument(argument)

    _step("Step 7. Prompt Builder")
    prompt_cards = _argument_to_prompt_cards(argument)
    prompt = PromptBuilder.build(args.query, prompt_cards, mode=GenerationMode(args.mode))
    _print(prompt)

    _step("Step 8. LLM")
    if not args.llm:
        print("Skipped by default so this debug script is deterministic.")
        print("Run with --llm to call local Gemma 3 4B through Ollama.")
        answer = _mock_answer(argument)
    else:
        llm = OllamaLLM(model=args.model)
        try:
            chunks = []
            for chunk in llm.stream(prompt):
                print(_ascii(chunk), end="", flush=True)
                chunks.append(chunk)
            print()
            answer = "".join(chunks)
        except LLMError as exc:
            _print(f"LLM failed: {exc}")
            answer = _mock_answer(argument)
            print("Using mock final output for the remaining debug step.")

    _step("Step 9. Post Processing")
    final_output = _post_process(answer, argument)
    _print(final_output)

    _step("Final Output")
    _print(final_output)


def _step(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _print(text: object = "") -> None:
    print(_ascii(str(text)))


def _ascii(text: str) -> str:
    return text.encode("ascii", "ignore").decode("ascii")


def _detect_intent(mode: str) -> str:
    if mode == "draft":
        return "Need rebuttal"
    if mode == "explain":
        return "Need card explanation"
    return "Need prep summary"


def _debug_embedding(query: str) -> dict[str, object]:
    digest = hashlib.sha256(query.encode("utf-8")).digest()
    preview = [round((byte / 255.0) * 2 - 1, 3) for byte in digest[:8]]
    return {
        "id": hashlib.sha256(query.encode("utf-8")).hexdigest()[:12],
        "dimensions": 8,
        "preview": preview,
    }


def _rerank(cards: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    reranked: list[dict[str, Any]] = []
    for card in sorted(cards, key=lambda item: item.get("score", 0), reverse=True):
        key = (str(card.get("section")), str(card.get("tag")))
        if key in seen:
            continue
        seen.add(key)
        reranked.append(card)
        if len(reranked) >= limit:
            break
    return reranked


def _build_argument(cards: list[dict[str, Any]]) -> dict[str, Any]:
    primary = cards[0] if cards else {}
    supporting_claims = []
    for card in cards:
        tag = str(card.get("tag") or "").strip()
        if tag and tag not in supporting_claims:
            supporting_claims.append(tag)

    evidence = []
    for card in cards:
        evidence.append(
            {
                "card_id": card.get("card_id"),
                "card_name": card.get("card_name") or card.get("author") or "Unknown",
                "section": card.get("section"),
                "tag": card.get("tag"),
                "score": card.get("score"),
                "citation": card.get("citation"),
                "highlights": card.get("highlights", []),
            }
        )

    return {
        "section": primary.get("section", "No section"),
        "main_claim": primary.get("tag", "No main claim"),
        "supporting_claims": supporting_claims,
        "evidence": evidence,
    }


def _argument_to_prompt_cards(argument: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for item in argument["evidence"]:
        cards.append(
            {
                "section": argument["section"],
                "tag": item["tag"],
                "citation": item["citation"],
                "card_name": item["card_name"],
                "highlights": item["highlights"],
            }
        )
    return cards


def _post_process(answer: str, argument: dict[str, Any]) -> str:
    body, _, _sources = answer.partition("Sources:")
    citations = []
    for item in argument["evidence"]:
        citation = str(item["card_name"]).strip()
        if citation and citation not in citations:
            citations.append(citation)

    lines = [body.strip(), "", "Sources"]
    lines.extend(f"- {citation}" for citation in citations)
    return "\n".join(line for line in lines if line is not None).strip()


def _mock_answer(argument: dict[str, Any]) -> str:
    evidence = argument["evidence"]
    first = evidence[0]["card_name"] if evidence else "the retrieved evidence"
    second = evidence[1]["card_name"] if len(evidence) > 1 else None
    if second:
        return (
            f"No.\n\n{first} answers the automation claim by showing humans still "
            "control the key judgment calls around AI systems. "
            f"{second} adds that regulatory or development constraints do not prove "
            "runaway escalation by themselves. Together, the retrieved Hyperwar cards "
            "give you a rebuttal: automation does not eliminate human control, and AI "
            "can improve decision quality rather than force escalation.\n\nSources:\n"
            f"- {first}\n- {second}"
        )
    return (
        f"No.\n\n{first} answers the automation claim by showing the retrieved "
        "evidence does not support runaway escalation.\n\nSources:\n"
        f"- {first}"
    )


def _print_card_list(cards: list[dict[str, Any]]) -> None:
    if not cards:
        print("No cards found.")
        return
    for card in cards:
        source = card.get("card_name") or card.get("author") or "Unknown"
        _print(f"{source:<18} {float(card.get('score', 0)):.3f}  {card.get('section')}  |  {card.get('tag')}")


def _print_argument(argument: dict[str, Any]) -> None:
    print("Argument:")
    print()
    print("Section:")
    _print(argument["section"])
    print()
    print("Main Claim:")
    _print(argument["main_claim"])
    print()
    print("Supporting Claims:")
    for claim in argument["supporting_claims"]:
        _print(f"- {claim}")
    print()
    print("Evidence:")
    for item in argument["evidence"]:
        _print(f"- {item['card_name']} ({float(item.get('score') or 0):.3f})")


if __name__ == "__main__":
    main()
