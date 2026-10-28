"""Markdown-aware chunking: text -> blocks -> heading sections -> chunks."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from app.storage.records import ChunkInput

if TYPE_CHECKING:
    from app.extraction import ExtractedPage


# ---------------------------------------------------------------------------
# Markdown patterns and records
# ---------------------------------------------------------------------------
# Patterns recognize supported syntax; records retain heading and line provenance.

# Capture a fence of 3+ backticks or tildes after optional leading whitespace.
# Examples: "  ```python" captures "```"; "~~~" captures "~~~".
_FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})")
# Capture the heading level (1-6 hashes) and title after up to 3 whitespace characters.
# Example: "  ## Setup" captures ("##", "Setup"); "#tag" does not match.
_HEADING_PATTERN = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
# Capture indentation before bullets or numbered markers at the start of each line.
# Examples: "  - item" captures two spaces; "1. item" and "1) item" capture "".
_LIST_ITEM_PATTERN = re.compile(r"^( {0,3})(?:[-+*]|\d+[.)])[ \t]+", re.MULTILINE)
# Match sentence-ending . ! ? followed only by optional closing quotes, ) or ].
# Examples: 'done.' and 'done!"' match; 'done' does not.
_SENTENCE_END_PATTERN = re.compile(r"[.!?][\"')\]]*$")


@dataclass(frozen=True, slots=True)
class _Heading:
    """Heading level and title parsed from Markdown."""

    level: int
    text: str


@dataclass(frozen=True, slots=True)
class _MarkdownBlock:
    """A Markdown content block and its original line range."""

    text: str
    start_line: int
    end_line: int
    is_code: bool = False


@dataclass(frozen=True, slots=True)
class _MarkdownSection:
    """Blocks grouped under a shared heading hierarchy."""

    headings: tuple[_Heading, ...]
    blocks: tuple[_MarkdownBlock, ...]


# ---------------------------------------------------------------------------
# Public chunking workflow
# ---------------------------------------------------------------------------
# The entry point makes the parsing, section grouping, and packing stages explicit.


def chunk_markdown(
    text: str,
    chunk_size: int,
    *,
    group_adjacent: bool = True,
    pages: tuple[ExtractedPage, ...] = (),
) -> list[ChunkInput]:
    """Split Markdown into heading-aware chunks while preserving source provenance.

    Args:
        text: Input text to process.
        chunk_size: Soft target number of words per chunk.
        group_adjacent: Whether adjacent blocks may be packed together.
        pages: Optional extracted-page metadata for provenance.

    Returns:
        Chunks containing text and provenance metadata.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if pages and text != "\n\n".join(page.text for page in pages):
        raise ValueError("Page provenance does not match extracted text")

    blocks = _parse_blocks(text)
    sections = _group_sections(blocks)
    chunks: list[ChunkInput] = []
    for section in sections:
        chunks.extend(_pack_section(section, chunk_size, group_adjacent=group_adjacent))
    if pages:
        page_lines = []
        start_line = 1
        for page in pages:
            end_line = start_line + page.text.count("\n")
            if page.text.strip():
                page_lines.append((page.number, start_line, end_line))
            start_line = end_line + 2
        annotated = []
        for chunk in chunks:
            numbers = [
                number
                for number, start, end in page_lines
                if start <= chunk.metadata["end_line"]
                and end >= chunk.metadata["start_line"]
            ]
            if not numbers:
                raise ValueError("Chunk body has no matching source page")
            annotated.append(
                replace(
                    chunk,
                    page_number=numbers[0]
                    if pages[0].kind == "page" and numbers[0] == numbers[-1]
                    else None,
                    metadata={
                        **chunk.metadata,
                        "source_pages": {
                            "kind": pages[0].kind,
                            "start": numbers[0],
                            "end": numbers[-1],
                            "scope": "body",
                        },
                    },
                )
            )
        return annotated
    return chunks


# ---------------------------------------------------------------------------
# Block parsing
# ---------------------------------------------------------------------------
# Blank lines and headings delimit text blocks; fenced code stays in one block.


def _parse_blocks(text: str) -> list[_MarkdownBlock]:
    """Parse Markdown into headings, prose blocks, and fenced code blocks.

    Args:
        text: Input text to process.

    Returns:
        Ordered Markdown blocks with source line ranges.
    """
    blocks: list[_MarkdownBlock] = []
    lines: list[str] = []
    start_line: int | None = None
    fence_marker: str | None = None
    fence_lines: list[str] = []
    fence_start_line: int | None = None

    def flush_text_block(end_line: int) -> None:
        """Append pending prose lines as a Markdown block.

        Args:
            end_line: Last source line of the pending block.
        """
        nonlocal lines, start_line
        if lines and start_line is not None:
            blocks.append(_MarkdownBlock("\n".join(lines), start_line, end_line))
        lines = []
        start_line = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        if fence_marker is not None:
            fence_lines.append(line)
            if line.lstrip().startswith(fence_marker):
                assert fence_start_line is not None
                blocks.append(
                    _MarkdownBlock(
                        "\n".join(fence_lines),
                        fence_start_line,
                        line_number,
                        is_code=True,
                    )
                )
                fence_marker = None
                fence_lines = []
                fence_start_line = None
            continue

        fence = _FENCE_PATTERN.match(line)
        if fence is not None:
            flush_text_block(line_number - 1)
            fence_marker = fence.group(1)
            fence_lines = [line]
            fence_start_line = line_number
            continue

        if _HEADING_PATTERN.match(line) is not None:
            flush_text_block(line_number - 1)
            blocks.append(_MarkdownBlock(line, line_number, line_number))
            continue

        if not line.strip():
            flush_text_block(line_number - 1)
            continue

        if start_line is None:
            start_line = line_number
        lines.append(line)

    if fence_marker is not None:
        assert fence_start_line is not None
        blocks.append(
            _MarkdownBlock(
                "\n".join(fence_lines),
                fence_start_line,
                len(text.splitlines()),
                is_code=True,
            )
        )
    else:
        flush_text_block(len(text.splitlines()))
    return blocks


# ---------------------------------------------------------------------------
# Heading section grouping
# ---------------------------------------------------------------------------
# Each heading updates the parent stack and starts a distinct section.


def _group_sections(blocks: list[_MarkdownBlock]) -> list[_MarkdownSection]:
    """Assign blocks to sections based on the active heading stack.

    Args:
        blocks: Parsed Markdown blocks.

    Returns:
        Ordered heading sections.
    """
    sections: list[_MarkdownSection] = []
    headings: list[_Heading] = []
    current_blocks: list[_MarkdownBlock] = []

    for block in blocks:
        heading = _parse_heading(block)
        if heading is None:
            current_blocks.append(block)
            continue

        if current_blocks:
            sections.append(_MarkdownSection(tuple(headings), tuple(current_blocks)))
            current_blocks = []

        headings = [current for current in headings if current.level < heading.level]
        headings.append(heading)

    if current_blocks:
        sections.append(_MarkdownSection(tuple(headings), tuple(current_blocks)))
    return sections


def _parse_heading(block: _MarkdownBlock) -> _Heading | None:
    """Extract the heading level and normalized title from a block.

    Args:
        block: Markdown block to inspect.

    Returns:
        Parsed heading, or ``None`` when the block is not a heading.
    """
    match = _HEADING_PATTERN.match(block.text)
    if match is None:
        return None
    # Strip optional closing hashes preceded by whitespace.
    # Examples: "Setup ###" becomes "Setup"; "C#" stays "C#".
    title = re.sub(r"\s+#+\s*$", "", match.group(2)).strip()
    return _Heading(level=len(match.group(1)), text=title)


# ---------------------------------------------------------------------------
# Chunk packing
# ---------------------------------------------------------------------------
# Split oversized blocks as needed, then combine pieces with heading and line metadata.


def _pack_section(
    section: _MarkdownSection,
    chunk_size: int,
    *,
    group_adjacent: bool = True,
) -> list[ChunkInput]:
    """Pack a section into word-limited chunks with heading metadata.

    Args:
        section: Heading section to pack.
        chunk_size: Soft target number of words per chunk.
        group_adjacent: Whether adjacent blocks may be packed together.

    Returns:
        Chunks packed from the section.
    """
    heading_text = "\n".join(
        f"{'#' * heading.level} {heading.text}" for heading in section.headings
    )
    body_limit = max(1, chunk_size - _word_count(heading_text))
    chunks: list[ChunkInput] = []
    current_blocks: list[_MarkdownBlock] = []
    current_word_count = 0

    def flush_chunk() -> None:
        """Finalize the accumulated blocks as one source chunk."""
        nonlocal current_blocks, current_word_count
        if not current_blocks:
            return
        content_parts = [heading_text] if heading_text else []
        content_parts.extend(block.text for block in current_blocks)
        metadata: dict[str, object] = {
            "headings": [heading.text for heading in section.headings],
            "start_line": current_blocks[0].start_line,
            "end_line": current_blocks[-1].end_line,
        }
        if section.headings:
            metadata["heading"] = section.headings[-1].text
        chunks.append(ChunkInput(content="\n\n".join(content_parts), metadata=metadata))
        current_blocks = []
        current_word_count = 0

    for block in section.blocks:
        if not group_adjacent:
            flush_chunk()
        for piece in _split_block(block, body_limit):
            piece_word_count = _word_count(piece.text)
            if current_blocks and current_word_count + piece_word_count > body_limit:
                flush_chunk()
            current_blocks.append(piece)
            current_word_count += piece_word_count
            if current_word_count >= body_limit:
                flush_chunk()

    flush_chunk()
    return chunks


# ---------------------------------------------------------------------------
# Oversized block splitting
# ---------------------------------------------------------------------------
# Prose prefers sentence boundaries; list items, tables, and code retain their structure.


def _split_block(block: _MarkdownBlock, word_limit: int) -> list[_MarkdownBlock]:
    """Split oversized prose or lists while preserving line ranges.

    Args:
        block: Markdown block to inspect.
        word_limit: Maximum number of words for a split block.

    Returns:
        Blocks covering the original content.
    """
    if block.is_code or _word_count(block.text) <= word_limit or _is_table(block.text):
        return [block]

    # Newline matches locate the next line's start for source-offset lookups.
    # Example: "one\ntwo" gives line start offsets [0, 4].
    line_starts = [0, *(match.end() for match in re.finditer(r"\n", block.text))]

    def slice_block(start: int, end: int) -> _MarkdownBlock:
        """Create a sub-block with line offsets inherited from its parent.

        Args:
            start: Start offset in the original block.
            end: Exclusive end offset in the original block.

        Returns:
            Sub-block with adjusted line numbers.
        """
        return _MarkdownBlock(
            text=block.text[start:end],
            start_line=block.start_line + bisect_right(line_starts, start) - 1,
            end_line=block.start_line + bisect_right(line_starts, end - 1) - 1,
        )

    first_item = _LIST_ITEM_PATTERN.match(block.text)
    if first_item is not None:
        item_starts = [
            match.start()
            for match in _LIST_ITEM_PATTERN.finditer(block.text)
            if match.group(1) == first_item.group(1)
        ]
        item_ends = [*item_starts[1:], len(block.text)]
        return [
            slice_block(start, len(block.text[:end].rstrip()))
            for start, end in zip(item_starts, item_ends)
        ]

    # Each non-whitespace run is a word; retain its offsets to preserve source text.
    # Example: "one  two" gives word spans (0, 3) and (5, 8).
    words = list(re.finditer(r"\S+", block.text))
    pieces: list[_MarkdownBlock] = []
    start = 0
    while start < len(words):
        end = min(start + word_limit, len(words))
        if end < len(words):
            end = next(
                (
                    index + 1
                    for index in range(end - 1, start - 1, -1)
                    if _SENTENCE_END_PATTERN.search(words[index].group())
                ),
                end,
            )
        pieces.append(slice_block(words[start].start(), words[end - 1].end()))
        start = end
    return pieces


def _is_table(text: str) -> bool:
    """Identify a Markdown table by its separator row.

    Args:
        text: Input text to process.

    Returns:
        Whether the text begins with a Markdown table.
    """
    lines = text.splitlines()
    if len(lines) < 2 or "|" not in lines[0]:
        return False
    cells = lines[1].strip().strip("|").split("|")
    # Table separator cells contain 3+ dashes, with optional alignment colons.
    # Examples: "---", ":---", "---:", and ":---:" match; "--" does not.
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _word_count(text: str) -> int:
    """Count whitespace-delimited words in text.

    Args:
        text: Input text to process.

    Returns:
        Number of whitespace-delimited words.
    """
    return len(text.split())
