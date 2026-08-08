from backend.prompt import GenerationMode, PromptBuilder


def test_prompt_builder_formats_cards():
    prompt = PromptBuilder.build(
        "Why is AI cautious?",
        [
            {
                "section": "AT: Hyperwar",
                "tag": "AI is risk-averse.",
                "citation": "Tucker 20, Defense One.",
                "highlights": [
                    {"text": "AI can be more cautious than humans."},
                    {"text": "The machine took far less risk."},
                ],
            }
        ],
        mode=GenerationMode.EXPLAIN,
    )

    assert "Input\nWhy is AI cautious?" in prompt
    assert "Tag:\nAI is risk-averse." in prompt
    assert "- AI can be more cautious than humans." in prompt
    assert "Sources" in prompt


def test_prompt_builder_draft_mode_uses_debate_voice():
    prompt = PromptBuilder.build(
        "Opponent says AI escalates because of automation.",
        [
            {
                "section": "AT: Hyperwar",
                "tag": "AI is risk-averse.",
                "citation": "Tucker 20, Defense One.",
                "highlights": [{"text": "The machine took far less risk."}],
            }
        ],
        mode=GenerationMode.DRAFT,
    )

    assert "competitive debater" in prompt
    assert "20-30 second rebuttal" in prompt
    assert "Do not sound like a textbook" in prompt
