"""Deterministic parser for Secret Agenda evidence format templates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from typing import Any

PARSER_VERSION = "sa-format-v1"
DEFAULT_FUZZY_THRESHOLD = 0.80
ACCEPT_THRESHOLD = 0.85
WARN_THRESHOLD = 0.65
FIELD_RE = re.compile(
    r"\[(?P<name>[A-Za-z_][A-Za-z0-9_-]*)(?::(?P<type>[A-Za-z][A-Za-z0-9_-]*))?\](?P<quant>[?*+]?)"
)
URL_RE = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
DATE_RE = re.compile(
    r"^(?:\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})$"
)
BUILTIN_TYPES = {"text", "line", "block", "url", "number", "date"}
ESCAPES = {
    r"\?": "?",
    r"\*": "*",
    r"\+": "+",
    r"\|": "|",
    r"\[": "[",
    r"\]": "]",
    r"\(": "(",
    r"\)": ")",
    r"\\": "\\",
}


@dataclass(frozen=True)
class DocumentBlock:
    index: int
    text: str
    normalized_text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_text(cls, index: int, text: str, metadata: dict[str, Any] | None = None):
        return cls(
            index=index,
            text=text,
            normalized_text=normalize_text(text),
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str = "text"
    quantifier: str = ""
    ignored: bool = False
    capture_name: str = ""

    @property
    def optional(self) -> bool:
        return self.quantifier in {"?", "*"}

    @property
    def repeated(self) -> bool:
        return self.quantifier in {"*", "+"}


@dataclass(frozen=True)
class TemplateLine:
    raw: str
    normalized: str
    fields: list[FieldSpec]
    regex: re.Pattern[str]
    fuzzy_regex: re.Pattern[str]
    literal_skeleton: str
    quantifier: str = ""
    literal_skeletons: tuple[str, ...] = ()
    fuzzy_threshold: float | None = None
    alternative_field_names: tuple[tuple[str, ...], ...] = ()

    @property
    def optional(self) -> bool:
        return self.quantifier in {"?", "*"}

    @property
    def repeated(self) -> bool:
        return self.quantifier in {"*", "+"}

    @property
    def primary_field(self) -> FieldSpec | None:
        return self.fields[0] if len(self.fields) == 1 else None

    @property
    def is_content_collector(self) -> bool:
        field = self.primary_field
        return bool(field and field.name == "content" and field.repeated)

    def has_field(self, name: str) -> bool:
        return any(field.name == name for field in self.fields)


@dataclass(frozen=True)
class FormatDiagnostic:
    code: str
    message: str
    severity: str = "warning"
    card_index: int | None = None
    block_index: int | None = None
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FormatGrammar:
    source: str
    lines: list[TemplateLine]
    defaults: dict[str, str]
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD
    diagnostics: list[FormatDiagnostic] = field(default_factory=list)

    @property
    def card_boundary(self) -> TemplateLine:
        for line in self.lines:
            if line.has_field("card"):
                return line
        raise ValueError("Grammar has no [card] boundary.")

    @property
    def section_boundary(self) -> TemplateLine | None:
        for line in self.lines:
            if line.has_field("section"):
                return line
        return None


@dataclass(frozen=True)
class ParsedEvidence:
    fields: dict[str, Any]
    confidence: dict[str, float]
    diagnostics: list[FormatDiagnostic]
    block_start: int
    block_end: int

    @property
    def overall_confidence(self) -> float:
        if not self.confidence:
            return 0.0
        return round(sum(self.confidence.values()) / len(self.confidence), 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields,
            "confidence": self.confidence,
            "overall_confidence": self.overall_confidence,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "block_start": self.block_start,
            "block_end": self.block_end,
        }


@dataclass(frozen=True)
class ParsePreview:
    grammar: FormatGrammar
    cards: list[ParsedEvidence]
    diagnostics: list[FormatDiagnostic]

    def summary(self) -> dict[str, Any]:
        high = sum(1 for card in self.cards if card.overall_confidence >= ACCEPT_THRESHOLD)
        warnings = sum(
            1
            for card in self.cards
            if WARN_THRESHOLD <= card.overall_confidence < ACCEPT_THRESHOLD
        )
        failed = sum(1 for card in self.cards if card.overall_confidence < WARN_THRESHOLD)
        fields: dict[str, int] = {}
        for card in self.cards:
            for name, value in card.fields.items():
                if name.startswith("_"):
                    continue
                if value not in (None, "", []):
                    fields[name] = fields.get(name, 0) + 1
        return {
            "detected_cards": len(self.cards),
            "high_confidence": high,
            "warnings": warnings,
            "failed": failed,
            "fields": fields,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "parser_version": PARSER_VERSION,
            "summary": self.summary(),
            "cards": [card.to_dict() for card in self.cards],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def compile_grammar(source: str) -> FormatGrammar:
    defaults, fuzzy, body = _parse_directives(source)
    diagnostics = _validate_grammar_text(body)
    lines = [_compile_line(line) for line in _meaningful_lines(body)]
    if not any(line.has_field("card") for line in lines):
        diagnostics.append(
            FormatDiagnostic(
                code="SA-GRAMMAR-002",
                message="Grammar must include a [card] structural boundary.",
                severity="error",
            )
        )
    diagnostics.extend(_validate_template_lines(lines))
    return FormatGrammar(
        source=source,
        lines=lines,
        defaults=defaults,
        fuzzy_threshold=fuzzy,
        diagnostics=diagnostics,
    )


def parse_text(text: str, grammar_source: str) -> ParsePreview:
    blocks = [
        DocumentBlock.from_text(index, block)
        for index, block in enumerate(_text_blocks(text))
    ]
    return parse_blocks(blocks, compile_grammar(grammar_source))


def parse_blocks(blocks: list[DocumentBlock], grammar: FormatGrammar) -> ParsePreview:
    diagnostics = list(grammar.diagnostics)
    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return ParsePreview(grammar=grammar, cards=[], diagnostics=diagnostics)

    try:
        card_boundary = grammar.card_boundary
    except ValueError as exc:
        diagnostics.append(
            FormatDiagnostic(code="SA-GRAMMAR-002", message=str(exc), severity="error")
        )
        return ParsePreview(grammar=grammar, cards=[], diagnostics=diagnostics)

    section_boundary = grammar.section_boundary
    cards = []
    current_section: str | None = grammar.defaults.get("section")
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if section_boundary and section_boundary is not card_boundary:
            section_match = match_line(section_boundary, block, grammar.fuzzy_threshold)
            if section_match.matched:
                value = _first_preserved_value(section_match.fields)
                if value:
                    current_section = value
                index += 1
                continue

        boundary_match = match_line(card_boundary, block, grammar.fuzzy_threshold)
        if not boundary_match.matched:
            index += 1
            continue

        card, next_index = _parse_card(
            blocks=blocks,
            start=index,
            grammar=grammar,
            current_section=current_section,
        )
        cards.append(card)
        diagnostics.extend(card.diagnostics)
        index = max(next_index, index + 1)

    return ParsePreview(grammar=grammar, cards=cards, diagnostics=diagnostics)


@dataclass(frozen=True)
class LineMatch:
    matched: bool
    fields: dict[str, str]
    confidence: float
    method: str
    diagnostic: FormatDiagnostic | None = None


def match_line(
    template: TemplateLine,
    block: DocumentBlock,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
) -> LineMatch:
    fuzzy_threshold = template.fuzzy_threshold or fuzzy_threshold
    exact = template.regex.match(block.text.strip())
    if exact:
        fields = _validated_fields(template, exact.groupdict())
        if fields is not None:
            return LineMatch(True, fields, 1.0, "exact")

    normalized = template.regex.match(block.normalized_text)
    if normalized:
        fields = _validated_fields(template, normalized.groupdict())
        if fields is not None:
            return LineMatch(True, fields, 0.94, "normalized")

    skeletons = template.literal_skeletons or (template.literal_skeleton,)
    skeletons = tuple(skeleton for skeleton in skeletons if skeleton)
    if skeletons:
        strict_block_skeleton = _literal_skeleton(block.normalized_text)
        family_block_skeleton = _fuzzy_literal_skeleton(block.normalized_text)
        strict_similarity = max(
            SequenceMatcher(None, skeleton, strict_block_skeleton).ratio()
            for skeleton in skeletons
        )
        family_similarity = max(
            SequenceMatcher(None, _fuzzy_literal_skeleton(skeleton), family_block_skeleton).ratio()
            for skeleton in skeletons
        )
        similarity = max(strict_similarity, family_similarity)
        if similarity >= fuzzy_threshold:
            fuzzy = template.fuzzy_regex.match(block.normalized_text)
            fields = _validated_fields(template, fuzzy.groupdict()) if fuzzy else None
            if template.fields and not fields:
                return LineMatch(False, {}, round(similarity, 3), "fuzzy-unparsed")
            confidence = min(similarity, max(strict_similarity, fuzzy_threshold))
            return LineMatch(
                True,
                fields or {},
                round(confidence, 3),
                "fuzzy",
                FormatDiagnostic(
                    code="SA-PARSE-002",
                    message=f"Fuzzy structural match accepted at {confidence:.2f}.",
                    block_index=block.index,
                    confidence=round(confidence, 3),
                ),
            )
        if similarity >= WARN_THRESHOLD:
            return LineMatch(
                False,
                {},
                round(similarity, 3),
                "fuzzy-rejected",
                FormatDiagnostic(
                    code="SA-PARSE-003",
                    message=f"Possible structural match below threshold: {similarity:.2f}.",
                    block_index=block.index,
                    confidence=round(similarity, 3),
                ),
            )

    return LineMatch(False, {}, 0.0, "none")


def normalize_text(text: str, *, casefold: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "\u00a0": " ",
        "\t": " ",
        "\r\n": "\n",
        "\r": "\n",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"-{1,}", "--", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*--\s*", " -- ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold() if casefold else text


def _parse_card(
    *,
    blocks: list[DocumentBlock],
    start: int,
    grammar: FormatGrammar,
    current_section: str | None,
) -> tuple[ParsedEvidence, int]:
    fields: dict[str, Any] = dict(grammar.defaults)
    confidence: dict[str, float] = {}
    diagnostics: list[FormatDiagnostic] = []
    if current_section and "section" not in fields:
        fields["section"] = current_section
        confidence["section"] = 1.0

    card_index = len([name for name in fields if name == "card"])
    position = start
    boundary_seen = False
    for template in grammar.lines:
        if template is grammar.section_boundary and not any(
            field.name == "card" for field in template.fields
        ):
            continue

        if template.is_content_collector:
            content, content_confidence, position = _collect_content(
                blocks=blocks,
                start=position,
                grammar=grammar,
                card_start=start,
            )
            if content:
                fields["content"] = "\n\n".join(content)
                confidence["content"] = content_confidence
            elif not template.optional:
                diagnostics.append(
                    FormatDiagnostic(
                        code="SA-PARSE-004",
                        message="Required [content]+ field was not found.",
                        card_index=card_index,
                        block_index=blocks[start].index,
                        severity="warning",
                    )
                )
            continue

        if position >= len(blocks):
            if template.optional:
                _missing_optional(template, diagnostics, card_index)
                continue
            diagnostics.append(
                FormatDiagnostic(
                    code="SA-PARSE-005",
                    message=f"Expected template line: {template.raw}",
                    severity="warning",
                    card_index=card_index,
                    block_index=blocks[start].index,
                )
            )
            break

        match = match_line(template, blocks[position], grammar.fuzzy_threshold)
        if match.diagnostic:
            diagnostics.append(match.diagnostic)
        if not match.matched:
            if template.optional:
                _missing_optional(template, diagnostics, card_index)
                continue
            diagnostics.append(
                FormatDiagnostic(
                    code="SA-PARSE-005",
                    message=f"Expected template line: {template.raw}",
                    severity="warning",
                    card_index=card_index,
                    block_index=blocks[position].index,
                    confidence=match.confidence or None,
                )
            )
            break

        boundary_seen = boundary_seen or template.has_field("card")
        _merge_fields(fields, confidence, template, match)
        position += 1

    if not boundary_seen:
        diagnostics.append(
            FormatDiagnostic(
                code="SA-PARSE-006",
                message="Parsed card without confirming card boundary.",
                severity="error",
                block_index=blocks[start].index,
            )
        )
    return (
        ParsedEvidence(
            fields={key: value for key, value in fields.items() if not key.startswith("_")},
            confidence=confidence,
            diagnostics=diagnostics,
            block_start=blocks[start].index,
            block_end=blocks[position - 1].index if position > start else blocks[start].index,
        ),
        position,
    )


def _collect_content(
    *,
    blocks: list[DocumentBlock],
    start: int,
    grammar: FormatGrammar,
    card_start: int,
) -> tuple[list[str], float, int]:
    content = []
    position = start
    while position < len(blocks):
        if position != card_start and _is_boundary(blocks[position], grammar):
            break
        text = blocks[position].text.strip()
        if text:
            content.append(text)
        position += 1
    return content, 0.9 if content else 0.0, position


def _is_boundary(block: DocumentBlock, grammar: FormatGrammar) -> bool:
    card_match = match_line(grammar.card_boundary, block, grammar.fuzzy_threshold)
    if card_match.matched and card_match.confidence >= _boundary_threshold(grammar.card_boundary):
        return True
    section = grammar.section_boundary
    if section and section is not grammar.card_boundary:
        section_match = match_line(section, block, grammar.fuzzy_threshold)
        if section_match.matched and section_match.confidence >= _boundary_threshold(section):
            return True
    return False


def _boundary_threshold(template: TemplateLine) -> float:
    return template.fuzzy_threshold or ACCEPT_THRESHOLD


def _merge_fields(
    fields: dict[str, Any],
    confidence: dict[str, float],
    template: TemplateLine,
    match: LineMatch,
) -> None:
    for spec in template.fields:
        if spec.ignored:
            continue
        value = match.fields.get(spec.name)
        if value in (None, ""):
            continue
        fields[spec.name] = value.strip()
        confidence[spec.name] = _field_confidence(spec, value, match.confidence)


def _missing_optional(
    template: TemplateLine,
    diagnostics: list[FormatDiagnostic],
    card_index: int | None,
) -> None:
    visible_fields = [field for field in template.fields if not field.ignored]
    if template.fields and not visible_fields:
        return
    field_names = ", ".join(f"[{field.name}]" for field in visible_fields)
    diagnostics.append(
        FormatDiagnostic(
            code="SA-PARSE-001",
            message=f"Optional field missing: {field_names or template.raw}",
            card_index=card_index,
            severity="info",
        )
    )


def _compile_line(raw_line: str) -> TemplateLine:
    raw = raw_line.strip()
    raw, fuzzy_threshold = _extract_local_fuzzy(raw)
    alternatives = _split_unescaped(raw, "|")
    pattern_parts = []
    fuzzy_pattern_parts = []
    fields = []
    literal_skeletons = []
    line_quantifier = ""
    for alternative in alternatives:
        pattern, fuzzy_pattern, alternative_fields, skeleton = _compile_alternative(
            alternative,
            capture_offset=len(fields),
        )
        pattern_parts.append(f"(?:{pattern})")
        fuzzy_pattern_parts.append(f"(?:{fuzzy_pattern})")
        fields.extend(alternative_fields)
        literal_skeletons.append(skeleton)
        for field in alternative_fields:
            line_quantifier = field.quantifier or line_quantifier
    combined_pattern = "|".join(pattern_parts)
    combined_fuzzy_pattern = "|".join(fuzzy_pattern_parts)
    alternative_field_names = tuple(
        tuple(field.name for field in _compile_alternative(alternative, 0)[2])
        for alternative in alternatives
    )
    return TemplateLine(
        raw=raw,
        normalized=normalize_text(raw),
        fields=fields,
        regex=re.compile("^(?:" + combined_pattern.strip() + ")$", re.IGNORECASE),
        fuzzy_regex=re.compile(
            "^(?:" + combined_fuzzy_pattern.strip() + ")$",
            re.IGNORECASE,
        ),
        literal_skeleton=literal_skeletons[0] if literal_skeletons else "",
        quantifier=line_quantifier if len(fields) == 1 else "",
        literal_skeletons=tuple(literal_skeletons),
        fuzzy_threshold=fuzzy_threshold,
        alternative_field_names=alternative_field_names,
    )


def _compile_alternative(
    raw: str,
    capture_offset: int,
) -> tuple[str, str, list[FieldSpec], str]:
    pattern_parts = []
    fuzzy_pattern_parts = []
    fields = []
    literal_parts = []
    cursor = 0
    for match in FIELD_RE.finditer(raw):
        literal = _unescape(raw[cursor : match.start()])
        pattern_parts.append(_literal_regex(literal))
        fuzzy_pattern_parts.append(_fuzzy_literal_regex(literal))
        literal_parts.append(normalize_text(literal))
        field = FieldSpec(
            name=match.group("name"),
            type=(match.group("type") or _default_type(match.group("name"))).lower(),
            quantifier=match.group("quant") or "",
            ignored=match.group("name").startswith("_"),
            capture_name=f"sa_field_{capture_offset + len(fields)}",
        )
        fields.append(field)
        pattern_parts.append(_field_regex(field))
        fuzzy_pattern_parts.append(_field_regex(field))
        cursor = match.end()
    trailing = _unescape(raw[cursor:])
    pattern_parts.append(_literal_regex(trailing))
    fuzzy_pattern_parts.append(_fuzzy_literal_regex(trailing))
    literal_parts.append(normalize_text(trailing))
    return (
        "".join(pattern_parts).strip(),
        "".join(fuzzy_pattern_parts).strip(),
        fields,
        _literal_skeleton(" ".join(literal_parts)),
    )


def _literal_regex(literal: str) -> str:
    normalized = normalize_text(literal)
    if not normalized:
        return r"\s*"
    escaped = re.escape(normalized)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace(r"\-\-", r"\s*(?:--|-)\s*")
    return escaped


def _fuzzy_literal_regex(literal: str) -> str:
    normalized = normalize_text(literal)
    if not normalized:
        return r"\s*"
    parts = []
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char.isspace():
            while index < len(normalized) and normalized[index].isspace():
                index += 1
            parts.append(r"\s+")
            continue
        if char.isalnum():
            start = index
            while index < len(normalized) and normalized[index].isalnum():
                index += 1
            parts.append(re.escape(normalized[start:index]))
            continue
        while index < len(normalized) and not normalized[index].isalnum() and not normalized[index].isspace():
            index += 1
        parts.append(r"\s*\W+\s*")
    return "".join(parts)


def _field_regex(field: FieldSpec) -> str:
    if field.type == "url":
        body = r"(?:https?://|www\.)\S+"
    elif field.type == "number":
        body = r"-?\d+(?:\.\d+)?"
    elif field.type == "date":
        body = r"(?:\d{4}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
    else:
        body = r".+?"
    if field.ignored:
        return f"(?:{body})"
    return f"(?P<{field.capture_name}>{body})"


def _validated_fields(
    template: TemplateLine,
    values: dict[str, str | None],
) -> dict[str, str] | None:
    cleaned = {}
    for field in template.fields:
        if field.ignored:
            continue
        value = normalize_field_value(values.get(field.capture_name) or "")
        if not value:
            continue
        if value and not _validate_type(field.type, value):
            return None
        cleaned[field.name] = value
    return cleaned


def _validate_type(field_type: str, value: str) -> bool:
    if field_type == "url":
        return URL_RE.match(value) is not None
    if field_type == "number":
        return NUMBER_RE.match(value) is not None
    if field_type == "date":
        return DATE_RE.match(value) is not None
    return True


def normalize_field_value(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    replacements = {
        "\u00a0": " ",
        "\t": " ",
        "\r\n": "\n",
        "\r": "\n",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def _field_confidence(field: FieldSpec, value: str, structural_confidence: float) -> float:
    if field.type in {"url", "number", "date"} and _validate_type(field.type, value):
        return 1.0
    return round(structural_confidence, 3)


def _parse_directives(source: str) -> tuple[dict[str, str], float, str]:
    defaults: dict[str, str] = {}
    fuzzy = DEFAULT_FUZZY_THRESHOLD
    lines = source.splitlines()
    body_lines = []
    in_defaults = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            body_lines.append(line)
            continue
        if stripped.startswith("@fuzzy"):
            parts = stripped.split()
            if len(parts) == 2:
                try:
                    fuzzy = float(parts[1])
                except ValueError:
                    pass
            continue
        if stripped.startswith("@defaults") and stripped.endswith("{"):
            in_defaults = True
            continue
        if in_defaults:
            if stripped == "}":
                in_defaults = False
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                defaults[key.strip()] = value.strip().strip('"')
            continue
        body_lines.append(line)
    return defaults, fuzzy, "\n".join(body_lines)


def _validate_grammar_text(source: str) -> list[FormatDiagnostic]:
    diagnostics = []
    for match in FIELD_RE.finditer(source):
        field_type = (match.group("type") or "text").lower()
        if field_type not in BUILTIN_TYPES:
            diagnostics.append(
                FormatDiagnostic(
                    code="SA-GRAMMAR-001",
                    message=f"Unknown field type: {field_type}",
                    severity="error",
                )
            )
    return diagnostics


def _validate_template_lines(lines: list[TemplateLine]) -> list[FormatDiagnostic]:
    diagnostics = []
    for line in lines:
        if len(line.alternative_field_names) > 1:
            card_presence = ["card" in names for names in line.alternative_field_names]
            section_presence = ["section" in names for names in line.alternative_field_names]
            if any(card_presence) and not all(card_presence):
                diagnostics.append(
                    FormatDiagnostic(
                        code="SA-GRAMMAR-005",
                        message=(
                            "Mixed card-boundary alternatives are ambiguous; every "
                            f"alternative should include [card]: {line.raw}"
                        ),
                        severity="warning",
                    )
                )
            if any(section_presence) and not all(section_presence):
                diagnostics.append(
                    FormatDiagnostic(
                        code="SA-GRAMMAR-006",
                        message=(
                            "Mixed section-boundary alternatives are ambiguous; every "
                            f"alternative should include [section]: {line.raw}"
                        ),
                        severity="warning",
                    )
                )
    for left, right in zip(lines, lines[1:]):
        if _unbounded(left) and _unbounded(right):
            diagnostics.append(
                FormatDiagnostic(
                    code="SA-GRAMMAR-004",
                    message=(
                        "Two unbounded fields appear consecutively: "
                        f"{left.raw} followed by {right.raw}."
                    ),
                    severity="warning",
                )
            )
    if lines and _unbounded(lines[0]) and not any(
        any(field.name == "card" for field in line.fields) for line in lines
    ):
        diagnostics.append(
            FormatDiagnostic(
                code="SA-GRAMMAR-002",
                message="Unbounded grammar has no structural card boundary.",
                severity="error",
            )
        )
    return diagnostics


def _unbounded(line: TemplateLine) -> bool:
    return line.repeated and not line.literal_skeleton


def _meaningful_lines(source: str) -> list[str]:
    lines = []
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        lines.append(line)
    return lines


def _text_blocks(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _default_type(name: str) -> str:
    if name == "content":
        return "block"
    return "line"


def _unescape(text: str) -> str:
    for escaped, plain in ESCAPES.items():
        text = text.replace(escaped, plain)
    return text


def _extract_local_fuzzy(raw: str) -> tuple[str, float | None]:
    match = re.search(r"(?<!\\)~(?P<threshold>0(?:\.\d+)?|1(?:\.0+)?)\s*$", raw)
    if not match:
        return raw, None
    return raw[: match.start()].rstrip(), float(match.group("threshold"))


def _split_unescaped(text: str, delimiter: str) -> list[str]:
    parts = []
    current = []
    escaped = False
    for char in text:
        if escaped:
            current.append("\\" + char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == delimiter:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _literal_skeleton(text: str) -> str:
    normalized = normalize_text(text)
    return re.sub(r"[A-Za-z0-9_]+", "", normalized).strip()


def _fuzzy_literal_skeleton(text: str) -> str:
    skeleton = _literal_skeleton(text)
    skeleton = re.sub(r"\s+", " ", skeleton)
    skeleton = re.sub(r"[^\w\s]+", "#", skeleton)
    skeleton = re.sub(r"\s*#\s*", " # ", skeleton)
    return re.sub(r"\s+", " ", skeleton).strip()


def _first_preserved_value(fields: dict[str, str]) -> str | None:
    for key, value in fields.items():
        if not key.startswith("_") and value:
            return value
    return None
