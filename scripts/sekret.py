#!/usr/bin/env python3
"""Interactive CLI for seKret aGenda."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.generation import GenerationService
from backend.llm import LLMError, OllamaLLM
from backend.prompt import GenerationMode
from backend.rag import RetrievalEngine, SearchRequest

MODES = {"search", "explain", "draft", "summarize"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    service = GenerationService(args.db, OllamaLLM(model=args.model))
    retrieval = RetrievalEngine(args.db)
    current_mode = "draft"
    print("seKret aGenda")
    print(f"Mode: {current_mode}")
    print("Type an input, /mode <mode>, /help, or Ctrl-D to exit.")
    print()

    while True:
        try:
            query = input(f"{current_mode}> ").strip()
        except EOFError:
            print()
            return

        if not query:
            continue

        command_result = _handle_command(query, current_mode)
        if command_result.handled:
            if command_result.mode:
                current_mode = command_result.mode
            continue

        print("Searching...")
        print()

        if current_mode == "search":
            rows = retrieval.search(SearchRequest(query=query, limit=args.limit))
            _print_search_results(rows)
            continue

        print("Generating...")
        print()
        try:
            cards, chunks = service.stream_answer(
                query,
                limit=args.limit,
                mode=GenerationMode(current_mode),
            )
            print("-" * 45)
            for chunk in chunks:
                print(chunk, end="", flush=True)
            print()
        except LLMError as exc:
            print(f"Generation failed: {exc}")
            continue

        print()
        print("Sources:")
        for card in cards:
            source = card.get("card_name") or card.get("author") or card.get("citation")
            print(f"- {source}: {card.get('tag')}")
        print()


class CommandResult:
    def __init__(self, handled: bool, mode: str | None = None):
        self.handled = handled
        self.mode = mode


def _handle_command(text: str, current_mode: str) -> CommandResult:
    if not text.startswith("/"):
        return CommandResult(False)

    parts = text.split()
    command = parts[0].lower()

    if command == "/mode":
        if len(parts) == 1:
            print(f"Current mode: {current_mode}")
            print("Available modes: search, explain, draft, summarize")
            print()
            return CommandResult(True)

        mode = parts[1].lower()
        if mode not in MODES:
            print(f"Unknown mode: {mode}")
            print("Available modes: search, explain, draft, summarize")
            print()
            return CommandResult(True)

        print(f"Mode: {mode}")
        print()
        return CommandResult(True, mode)

    if command == "/help":
        print("Commands:")
        print("- /mode")
        print("- /mode search")
        print("- /mode explain")
        print("- /mode draft")
        print("- /mode summarize")
        print()
        return CommandResult(True)

    print(f"Unknown command: {command}")
    print("Try /help.")
    print()
    return CommandResult(True)


def _print_search_results(rows: list[dict[str, object]]) -> None:
    for row in rows:
        print("-" * 45)
        print(f"Score: {row['score']:.3f}")
        print()
        print("Section:")
        print(row["section"])
        print()
        print("Tag:")
        print(row["tag"])
        print()
        print("Citation:")
        source = row.get("card_name") or row.get("author") or "Unknown"
        year = row.get("year")
        print(f"{source} ({year})" if year else source)
        print()
        print("Highlights:")
        for highlight in row.get("highlights", []):
            color = f" [{highlight['color']}]" if highlight.get("color") else ""
            print(f"-{color} {_clip(str(highlight['text']), 180)}")
        print()


def _clip(text: str, max_length: int) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= max_length:
        return normalized
    return normalized[: max_length - 3].rstrip() + "..."


if __name__ == "__main__":
    main()
