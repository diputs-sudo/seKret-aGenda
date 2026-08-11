import json
import subprocess
import sys
from pathlib import Path

from backend.format_lang import compile_grammar, parse_text

ROOT = Path(__file__).resolve().parents[1]


def test_basic_template_parses_cards_with_optional_links():
    text = """-- 1 -- Smith 25
https://example.com/a
AI allows betting companies to personalize offers.
These systems can target individual behavior.

-- 2 -- Jones 24
Sports betting regulation remains fragmented.

-- 3 -- Wang 26
https://example.com/c
Federal standards could address this problem.
"""
    grammar = """-- [card] -- [author]
[link:url]?
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 3
    assert preview.summary()["fields"]["author"] == 3
    assert preview.summary()["fields"]["link"] == 2
    assert preview.summary()["fields"]["content"] == 3
    assert preview.cards[0].fields["card"] == "1"
    assert preview.cards[0].fields["author"] == "Smith 25"
    assert preview.cards[0].fields["link"] == "https://example.com/a"
    assert "target individual behavior" in preview.cards[0].fields["content"]
    assert "link" not in preview.cards[1].fields


def test_hyphenated_url_field_is_not_structurally_normalized():
    text = """-- 1 -- Smith 25
https://example.com/smith-ai-betting
Evidence paragraph.
"""
    grammar = """-- [card] -- [author]
[link:url]?
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.cards[0].fields["link"] == "https://example.com/smith-ai-betting"


def test_normalized_separator_matches_without_fuzzy_failure():
    text = """—  1  —   Smith 25
https://example.com
Evidence...
"""
    grammar = """-- [card] -- [author]
[link:url]?
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert preview.cards[0].fields["card"] == "1"
    assert preview.cards[0].fields["author"] == "Smith 25"
    assert preview.cards[0].confidence["card"] == 0.94


def test_content_collector_does_not_consume_next_card_boundary():
    text = """-- 1 -- Smith 25
First evidence paragraph.

-- 2 -- Jones 24
Second evidence paragraph.
"""
    grammar = """-- [card] -- [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 2
    assert "-- 2 -- Jones 24" not in preview.cards[0].fields["content"]
    assert preview.cards[1].fields["content"] == "Second evidence paragraph."


def test_ignored_optional_line_is_not_preserved():
    text = """-- 1 -- Smith 25
irrelevant metadata
Evidence paragraph.
"""
    grammar = """-- [card] -- [author]
[_]?
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert "_" not in preview.cards[0].fields
    assert preview.cards[0].fields["content"] == "Evidence paragraph."


def test_defaults_are_attached_to_cards():
    text = """-- 1 -- Smith 25
Evidence paragraph.
"""
    grammar = """@defaults {
owner: opponent
side: aff
}

-- [card] -- [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.cards[0].fields["owner"] == "opponent"
    assert preview.cards[0].fields["side"] == "aff"


def test_custom_field_names_can_use_hyphens():
    text = """-- 1 -- Bronx Science -- Smith 25
Evidence paragraph.
"""
    grammar = """-- [card] -- [school-name] -- [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert preview.cards[0].fields["school-name"] == "Bronx Science"


def test_alternative_card_boundaries_parse_multiple_header_styles():
    text = """-- 1 -- Smith 25
First evidence paragraph.

Card 2: Jones 24
Second evidence paragraph.
"""
    grammar = """-- [card] -- [author] | Card [card]: [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 2
    assert preview.cards[0].fields["author"] == "Smith 25"
    assert preview.cards[1].fields["card"] == "2"
    assert preview.cards[1].fields["author"] == "Jones 24"


def test_escaped_pipe_is_treated_as_literal_text():
    text = """-- 1 | Smith 25
Evidence paragraph.
"""
    grammar = r"""-- [card] \| [author] | Card [card]: [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert preview.cards[0].fields["card"] == "1"
    assert preview.cards[0].fields["author"] == "Smith 25"


def test_full_line_comments_are_ignored():
    text = """-- 1 -- Smith 25
Evidence paragraph.
"""
    grammar = """# opponent packet format
// second comment style
-- [card] -- [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert preview.cards[0].fields["author"] == "Smith 25"


def test_local_fuzzy_threshold_is_compiled_per_line():
    grammar = """-- [card] -- [author]~0.90
[content]+
"""

    compiled = compile_grammar(grammar)

    assert compiled.card_boundary.fuzzy_threshold == 0.9


def test_local_fuzzy_threshold_accepts_similar_separator_and_captures_fields():
    text = """~~ 1 ~~ Smith 25
Evidence paragraph about AI and escalation.
"""
    grammar = """-- [card] -- [author]~0.60
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 1
    assert preview.cards[0].fields["card"] == "1"
    assert preview.cards[0].fields["author"] == "Smith 25"
    assert preview.cards[0].confidence["card"] == 0.6
    assert any(
        diagnostic.code == "SA-PARSE-002"
        for diagnostic in preview.cards[0].diagnostics
    )


def test_fuzzy_boundary_protection_respects_local_threshold():
    text = """~~ 1 ~~ Smith 25
First evidence paragraph.

~~ 2 ~~ Jones 24
Second evidence paragraph.
"""
    grammar = """-- [card] -- [author]~0.60
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 2
    assert "~~ 2 ~~ Jones 24" not in preview.cards[0].fields["content"]


def test_mixed_structural_alternatives_raise_warning():
    grammar = """Source [author] | -- [card] -- [author]
[content]+
"""

    compiled = compile_grammar(grammar)

    assert "SA-GRAMMAR-005" in [diagnostic.code for diagnostic in compiled.diagnostics]


def test_grammar_validation_warns_on_consecutive_unbounded_fields():
    grammar = """[content]*
[_]*
[content]*
"""

    compiled = compile_grammar(grammar)

    codes = [diagnostic.code for diagnostic in compiled.diagnostics]
    assert "SA-GRAMMAR-004" in codes
    assert "SA-GRAMMAR-002" in codes


def test_low_confidence_fuzzy_boundary_is_not_trusted():
    text = """not really a card header Smith 25
Evidence paragraph.
"""
    grammar = """-- [card] -- [author]
[content]+
"""

    preview = parse_text(text, grammar)

    assert preview.summary()["detected_cards"] == 0


def test_format_preview_script_outputs_json(tmp_path):
    input_path = tmp_path / "input.txt"
    grammar_path = tmp_path / "grammar.sa"
    input_path.write_text(
        "-- 1 -- Smith 25\nhttps://example.com/a\nEvidence paragraph.\n",
        encoding="utf-8",
    )
    grammar_path.write_text(
        "-- [card] -- [author]\n[link:url]?\n[content]+\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/format_preview.py",
            str(input_path),
            str(grammar_path),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["summary"]["detected_cards"] == 1
    assert payload["cards"][0]["fields"]["author"] == "Smith 25"


def test_mega_format_fixture_matches_golden_behavior():
    fixture_dir = ROOT / "tests" / "format" / "mega"
    evidence = (fixture_dir / "evidence.txt").read_text(encoding="utf-8")
    grammar = (fixture_dir / "grammar.sa").read_text(encoding="utf-8")
    expected = json.loads((fixture_dir / "expected.json").read_text(encoding="utf-8"))

    payload = parse_text(evidence, grammar).to_dict()
    actual = {
        "summary": payload["summary"],
        "cards": [
            {
                "fields": card["fields"],
                "overall_confidence": card["overall_confidence"],
            }
            for card in payload["cards"]
        ],
        "diagnostic_codes": [
            diagnostic["code"]
            for diagnostic in payload["diagnostics"]
        ],
    }

    assert actual == expected
