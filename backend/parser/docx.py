"""DOCX parser for debate evidence files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import ZipFile

from backend.models import (
    ArgumentType,
    Citation,
    DebateDocument,
    EvidenceCard,
    HighlightSpan,
    Section,
)

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
W = f"{{{WORD_NS['w']}}}"
IGNORED_HIGHLIGHT_VALUES = {"", "none", "white"}
IGNORED_SHADING_VALUES = {"", "auto", "ffffff", "white"}
SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?%)\]\}])")
SPACE_AFTER_OPEN_RE = re.compile(r"([(\[\{])\s+")
CONTRACTION_APOSTROPHE_RE = re.compile(
    r"\s+(['’])(?=(?:s|t|re|ve|d|ll|m)\b)", re.IGNORECASE
)


@dataclass
class ParsedRun:
    text: str
    highlight: str | None = None
    bold: bool = False
    underline: bool = False


@dataclass
class ParsedParagraph:
    index: int
    style: str | None
    text: str
    runs: list[ParsedRun] = field(default_factory=list)


@dataclass(frozen=True)
class HighlightStyles:
    paragraph_styles: set[str] = field(default_factory=set)
    character_styles: set[str] = field(default_factory=set)


def parse_docx(path: str | Path) -> DebateDocument:
    """Parse a DOCX fixture into DebateIR."""
    docx_path = Path(path)
    paragraphs = _read_paragraphs(docx_path)

    document = DebateDocument(
        name=docx_path.stem,
        source_path=str(docx_path),
        source_format="docx",
    )
    current_section: Section | None = None
    section_order = 0
    index = 0

    while index < len(paragraphs):
        paragraph = paragraphs[index]

        if _is_section_heading(paragraph):
            current_section = Section(
                document_id=document.id,
                name=paragraph.text,
                argument_type=_argument_type(paragraph.text),
                order_index=section_order,
            )
            document.sections.append(current_section)
            section_order += 1
            index += 1
            continue

        if _is_card_heading(paragraph):
            if current_section is None:
                current_section = Section(
                    document_id=document.id,
                    name="Uncategorized",
                    argument_type=ArgumentType.UNKNOWN,
                    order_index=section_order,
                )
                document.sections.append(current_section)
                section_order += 1

            card, next_index = _parse_card(
                document=document,
                section=current_section,
                paragraphs=paragraphs,
                tag_index=index,
            )
            if card is not None:
                current_section.cards.append(card)
            index = next_index
            continue

        index += 1

    return document


def _read_paragraphs(path: Path) -> list[ParsedParagraph]:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
        styles = _highlight_styles(archive)

    paragraphs: list[ParsedParagraph] = []
    for para_index, paragraph in enumerate(root.findall(".//w:body/w:p", WORD_NS)):
        style_el = paragraph.find("./w:pPr/w:pStyle", WORD_NS)
        style = style_el.attrib.get(f"{W}val") if style_el is not None else None
        paragraph_highlight = "style" if style in styles.paragraph_styles else None
        runs: list[ParsedRun] = []

        for run in paragraph.findall("./w:r", WORD_NS):
            text = _run_text(run)
            if not text:
                continue

            run_props = run.find("./w:rPr", WORD_NS)
            run_style_el = run.find("./w:rPr/w:rStyle", WORD_NS)
            run_style = (
                run_style_el.attrib.get(f"{W}val") if run_style_el is not None else None
            )
            highlight = paragraph_highlight
            bold = False
            underline = False
            if run_props is not None:
                highlight = _highlight_value(run_props) or highlight
                bold = run_props.find("./w:b", WORD_NS) is not None
                underline = run_props.find("./w:u", WORD_NS) is not None
            if not highlight and run_style in styles.character_styles:
                highlight = "style"

            runs.append(
                ParsedRun(
                    text=text,
                    highlight=highlight,
                    bold=bold,
                    underline=underline,
                )
            )

        text = _normalize_spacing("".join(run.text for run in runs))
        if text:
            paragraphs.append(
                ParsedParagraph(index=para_index, style=style, text=text, runs=runs)
            )

    return paragraphs


def _run_text(run: ET.Element) -> str:
    parts: list[str] = []
    for child in run:
        if child.tag == f"{W}t":
            parts.append(child.text or "")
        elif child.tag == f"{W}tab":
            parts.append(" ")
        elif child.tag in {f"{W}br", f"{W}cr"}:
            parts.append("\n")
    return "".join(parts)


def _highlight_styles(archive: ZipFile) -> HighlightStyles:
    try:
        root = ET.fromstring(archive.read("word/styles.xml"))
    except KeyError:
        return HighlightStyles()

    raw_styles: dict[str, tuple[str, bool, str]] = {}
    for style in root.findall("w:style", WORD_NS):
        style_id = style.attrib.get(f"{W}styleId", "")
        style_type = style.attrib.get(f"{W}type", "")
        based_on = style.find("w:basedOn", WORD_NS)
        parent_id = based_on.attrib.get(f"{W}val", "") if based_on is not None else ""
        has_highlight = _highlight_value(style.find("w:rPr", WORD_NS)) is not None
        if style_id:
            raw_styles[style_id] = (style_type, has_highlight, parent_id)

    def inherits_highlight(style_id: str, seen: set[str] | None = None) -> bool:
        if not style_id or style_id not in raw_styles:
            return False
        seen = seen or set()
        if style_id in seen:
            return False
        seen.add(style_id)
        _, has_highlight, parent_id = raw_styles[style_id]
        return has_highlight or inherits_highlight(parent_id, seen)

    paragraph_styles: set[str] = set()
    character_styles: set[str] = set()
    for style_id, (style_type, _, _) in raw_styles.items():
        if not inherits_highlight(style_id):
            continue
        if style_type == "paragraph":
            paragraph_styles.add(style_id)
        elif style_type == "character":
            character_styles.add(style_id)

    return HighlightStyles(
        paragraph_styles=paragraph_styles,
        character_styles=character_styles,
    )


def _highlight_value(run_props: ET.Element | None) -> str | None:
    if run_props is None:
        return None

    highlight_el = run_props.find("./w:highlight", WORD_NS)
    if highlight_el is not None:
        value = (highlight_el.attrib.get(f"{W}val") or "").lower()
        if value not in IGNORED_HIGHLIGHT_VALUES:
            return value

    shading_el = run_props.find("./w:shd", WORD_NS)
    if shading_el is not None:
        fill = (shading_el.attrib.get(f"{W}fill") or "").lower()
        if fill not in IGNORED_SHADING_VALUES:
            return fill

    return None


def _normalize_spacing(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", text)
    text = SPACE_AFTER_OPEN_RE.sub(r"\1", text)
    text = CONTRACTION_APOSTROPHE_RE.sub(r"\1", text)
    return text


def _is_section_heading(paragraph: ParsedParagraph) -> bool:
    return paragraph.style in {"Heading2", "Heading3"}


def _is_card_heading(paragraph: ParsedParagraph) -> bool:
    return paragraph.style == "Heading4"


def _argument_type(text: str) -> ArgumentType:
    normalized = text.strip().lower()
    if normalized.startswith("at:"):
        return ArgumentType.ANSWER_TO
    if normalized.startswith("ov") or "overview" in normalized:
        return ArgumentType.OVERVIEW
    if normalized:
        return ArgumentType.ARGUMENT
    return ArgumentType.UNKNOWN


def _parse_card(
    *,
    document: DebateDocument,
    section: Section,
    paragraphs: list[ParsedParagraph],
    tag_index: int,
) -> tuple[EvidenceCard | None, int]:
    tag_paragraph = paragraphs[tag_index]
    citation_index = tag_index + 1

    if citation_index >= len(paragraphs):
        return None, citation_index

    citation_paragraph = paragraphs[citation_index]
    if _is_section_heading(citation_paragraph) or _is_card_heading(citation_paragraph):
        return None, citation_index

    body_start = citation_index + 1
    body_end = body_start
    while body_end < len(paragraphs):
        if _is_section_heading(paragraphs[body_end]) or _is_card_heading(
            paragraphs[body_end]
        ):
            break
        body_end += 1

    body_paragraphs = paragraphs[body_start:body_end]
    body = "\n\n".join(paragraph.text for paragraph in body_paragraphs).strip()
    if not body:
        return None, body_end

    citation = _parse_citation(citation_paragraph.text)
    card = EvidenceCard(
        id=str(uuid4()),
        document_id=document.id,
        section_id=section.id,
        tag=tag_paragraph.text,
        card_name=_card_name(citation),
        citation=citation,
        body=body,
        highlights=_extract_highlights(body_paragraphs),
        paragraph_start=tag_paragraph.index,
        paragraph_end=body_paragraphs[-1].index if body_paragraphs else tag_paragraph.index,
        source_format="docx",
        metadata={
            "section_name": section.name,
            "tag_paragraph_index": tag_paragraph.index,
            "citation_paragraph_index": citation_paragraph.index,
        },
    )
    return card, body_end


def _parse_citation(raw: str) -> Citation:
    url = _first_url(raw)
    author = _first_author(raw)
    year = _first_year(raw)
    return Citation(raw=raw, author=author, year=year, source_url=url)


def _first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s)\]]+", text)
    if not match:
        return None
    url = match.group(0)
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return url


def _first_author(text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    first_chunk = re.split(r"[,(\[]", cleaned, maxsplit=1)[0].strip()
    first_chunk = re.sub(r"\s+[-–—].*$", "", first_chunk).strip()
    first_chunk = re.sub(r"\s+[‘'’]?\d{2,4}\b.*$", "", first_chunk).strip()
    if not first_chunk:
        return None
    return first_chunk.split()[-1]


def _first_year(text: str) -> int | None:
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if match:
        return int(match.group(1))

    match = re.search(r"(?:[‘']|\b)(\d{2})(?:\b|[.,\]])", text)
    if match:
        year = int(match.group(1))
        return 2000 + year if year < 70 else 1900 + year

    return None


def _card_name(citation: Citation) -> str | None:
    if citation.author and citation.year:
        return f"{citation.author} {citation.year % 100:02d}"
    if citation.author:
        return citation.author
    return None


def _extract_highlights(paragraphs: list[ParsedParagraph]) -> list[HighlightSpan]:
    highlights: list[HighlightSpan] = []
    for paragraph in paragraphs:
        offset = 0
        active_text: list[str] = []
        active_color: str | None = None
        active_start: int | None = None
        active_run_index: int | None = None

        for run_index, run in enumerate(paragraph.runs):
            start = offset
            end = offset + len(run.text)
            offset = end

            if run.highlight:
                if active_color == run.highlight:
                    active_text.append(run.text)
                else:
                    _append_highlight(
                        highlights,
                        active_text,
                        active_color,
                        paragraph.index,
                        active_run_index,
                        active_start,
                        start,
                    )
                    active_text = [run.text]
                    active_color = run.highlight
                    active_start = start
                    active_run_index = run_index
            else:
                _append_highlight(
                    highlights,
                    active_text,
                    active_color,
                    paragraph.index,
                    active_run_index,
                    active_start,
                    start,
                )
                active_text = []
                active_color = None
                active_start = None
                active_run_index = None

        _append_highlight(
            highlights,
            active_text,
            active_color,
            paragraph.index,
            active_run_index,
            active_start,
            offset,
        )

    return highlights


def _append_highlight(
    highlights: list[HighlightSpan],
    text_parts: list[str],
    color: str | None,
    paragraph_index: int,
    run_index: int | None,
    start_char: int | None,
    end_char: int,
) -> None:
    text = _normalize_spacing("".join(text_parts))
    if not text:
        return
    highlights.append(
        HighlightSpan(
            text=text,
            color=color,
            paragraph_index=paragraph_index,
            run_index=run_index,
            start_char=start_char,
            end_char=end_char,
        )
    )
