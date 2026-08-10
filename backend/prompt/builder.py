"""Prompt builder for grounded answers."""

from __future__ import annotations

from enum import Enum
from typing import Any


class GenerationMode(str, Enum):
    EXPLAIN = "explain"
    DRAFT = "draft"
    SUMMARIZE = "summarize"


class PromptBuilder:
    @staticmethod
    def build(
        query: str,
        cards: list[dict[str, Any]],
        mode: GenerationMode | str = GenerationMode.DRAFT,
    ) -> str:
        mode = GenerationMode(mode)
        sections = _mode_instructions(mode)
        sections.extend(["", "Input", query, "", "-----------------", "", "Evidence"])

        if not cards:
            sections.append("No evidence cards were retrieved.")
            return "\n".join(sections).strip()

        for index, card in enumerate(cards, start=1):
            _append_card(sections, index, card)

        sections.extend(
            [
                "",
                *_output_instructions(mode),
            ]
        )
        return "\n".join(sections).strip()

    @staticmethod
    def build_from_bundle(
        bundle: Any,
        mode: GenerationMode | str = GenerationMode.DRAFT,
    ) -> str:
        mode = GenerationMode(mode)
        sections = _mode_instructions(mode)
        sections.extend(
            [
                "",
                "Input",
                str(bundle.opponent_claim or bundle.query),
                "",
                "Source Status:",
                str(bundle.source_status),
                "",
                "Main Claim:",
                str(bundle.main_claim),
                "",
                "Warrants:",
            ]
        )
        if bundle.warrants:
            sections.extend(f"- {warrant}" for warrant in bundle.warrants)
        else:
            sections.append("- No sourced warrants available.")

        sections.extend(["", "Argument Clusters:"])
        if bundle.clusters:
            for index, cluster in enumerate(bundle.clusters, start=1):
                sections.extend(
                    [
                        f"Cluster {index}",
                        f"Thesis: {cluster.thesis}",
                        f"Confidence: {cluster.confidence:.3f}",
                    ]
                )
        else:
            sections.append("No evidence clusters were built.")

        sections.extend(["", "-----------------", "", "Evidence"])
        if not bundle.cards:
            sections.append("No evidence cards were retrieved.")
        else:
            for index, card in enumerate(bundle.cards, start=1):
                _append_card(sections, index, card)

        sections.extend(["", *_output_instructions(mode)])
        if bundle.source_status == "ANALYSIS ONLY":
            sections.extend(
                [
                    "Do not cite backfile cards because none passed the source gate.",
                    "Label the response [ANALYSIS ONLY].",
                ]
            )
        else:
            sections.append("Label the response [BACKFILE-SOURCED].")
        return "\n".join(sections).strip()


def _mode_instructions(mode: GenerationMode) -> list[str]:
    common = [
        "Use ONLY the provided evidence.",
        "Do not invent facts, authors, or citations.",
        "If the evidence is insufficient, say what is missing.",
        "Cite cards by card name when possible.",
    ]

    if mode == GenerationMode.EXPLAIN:
        return [
            "You are explaining debate evidence to someone who is learning the argument.",
            *common,
            "Explain what the evidence says, why it matters, and how it answers the input.",
            "Use clear, plain language.",
        ]

    if mode == GenerationMode.SUMMARIZE:
        return [
            "You are summarizing retrieved debate evidence for fast prep.",
            *common,
            "Use compact bullet points.",
            "Prioritize tags, warrants, and citations.",
        ]

    return [
        "You are assisting a competitive debater during prep or a round.",
        *common,
        "Write a concise rebuttal in debate voice.",
        "Sound direct, strategic, and usable out loud.",
        "Do not sound like a textbook or encyclopedia.",
    ]


def _append_card(sections: list[str], index: int, card: dict[str, Any]) -> None:
    sections.extend(
        [
            "",
            f"Card {index}",
            "",
            "Card ID:",
            str(card.get("card_id") or card.get("id") or ""),
            "",
            "Section:",
            str(card.get("section") or ""),
            "",
            "Tag:",
            str(card.get("tag") or ""),
            "",
            "Citation:",
            str(card.get("citation") or card.get("card_name") or ""),
            "",
            "Highlights:",
        ]
    )
    highlights = card.get("highlights") or []
    if highlights:
        for highlight in highlights:
            text = str(highlight.get("text", "")).strip()
            if text:
                sections.append(f"- {text}")
    else:
        sections.append("- No highlights captured.")
    sections.extend(["", "-----------------"])


def _output_instructions(mode: GenerationMode) -> list[str]:
    if mode == GenerationMode.EXPLAIN:
        return [
            "Write an explanation.",
            "End with a Sources list using the card names or citations.",
        ]
    if mode == GenerationMode.SUMMARIZE:
        return [
            "Write 3-5 bullets.",
            "End with a Sources list using the card names or citations.",
        ]
    return [
        "Write a 20-30 second rebuttal.",
        "Start with a short answer like 'No.' when appropriate.",
        "Use the retrieved tags and highlights as warrants.",
        "End with a Sources list using the card names or citations.",
    ]
