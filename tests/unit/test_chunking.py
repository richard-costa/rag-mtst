from __future__ import annotations

import pytest

from app.chunking import chunk_markdown
from app.extraction import ExtractedContent, ExtractedPage


@pytest.mark.parametrize("group_adjacent", [False, True])
@pytest.mark.parametrize("kind", ["page", "slide"])
def test_source_page_ranges_include_blank_pages_without_fabricating_text(
    group_adjacent, kind
):
    extracted = ExtractedContent.from_pages(
        (
            ExtractedPage(1, "# Shared title\n\nFirst body.", kind),
            ExtractedPage(2, "", kind),
            ExtractedPage(3, "Second body.", kind),
        ),
        format="pdf",
        profile={"method": "test"},
    )
    chunks = chunk_markdown(
        extracted.text, 100, group_adjacent=group_adjacent, pages=extracted.pages
    )

    assert len(chunks) == (1 if group_adjacent else 2)
    assert all(chunk.metadata["headings"] == ["Shared title"] for chunk in chunks)
    assert all("page 2" not in chunk.content.casefold() for chunk in chunks)
    assert chunks[0].metadata["source_pages"] == {
        "kind": kind,
        "start": 1,
        "end": 3 if group_adjacent else 1,
        "scope": "body",
    }
    if not group_adjacent:
        assert chunks[1].metadata["source_pages"] == {
            "kind": kind,
            "start": 3,
            "end": 3,
            "scope": "body",
        }
        assert chunks[1].content == "# Shared title\n\nSecond body."
        assert chunks[1].page_number == (3 if kind == "page" else None)


def test_page_provenance_rejects_text_mismatch():
    with pytest.raises(ValueError, match="does not match extracted text"):
        chunk_markdown("Different text", 10, pages=(ExtractedPage(1, "Source text"),))


# ---------------------------------------------------------------------------
# Markdown provenance
# ---------------------------------------------------------------------------
# Heading hierarchy and source line ranges must travel with each chunk.


def test_markdown_chunks_include_heading_context_and_provenance() -> None:
    chunks = chunk_markdown(
        "# Setup\n\nInstall the package.\n\n## Authentication\n\nUse an access token.",
        chunk_size=10,
    )

    assert [chunk.content for chunk in chunks] == [
        "# Setup\n\nInstall the package.",
        "# Setup\n## Authentication\n\nUse an access token.",
    ]
    assert chunks[0].metadata == {
        "headings": ["Setup"],
        "heading": "Setup",
        "start_line": 3,
        "end_line": 3,
    }
    assert chunks[1].metadata == {
        "headings": ["Setup", "Authentication"],
        "heading": "Authentication",
        "start_line": 7,
        "end_line": 7,
    }


# ---------------------------------------------------------------------------
# Markdown boundaries
# ---------------------------------------------------------------------------
# Sections remain separate and fenced code blocks stay intact even when oversized.


def test_markdown_chunks_do_not_cross_sections_or_split_code_fences() -> None:
    chunks = chunk_markdown(
        "# First\n\nOne two three.\n\n# Second\n\n```python\nalpha beta gamma delta\n```",
        chunk_size=5,
    )

    assert [chunk.metadata["heading"] for chunk in chunks] == ["First", "Second"]
    assert "# First" in chunks[0].content
    assert "# Second" not in chunks[0].content
    assert chunks[1].content.endswith("```python\nalpha beta gamma delta\n```")


def test_oversized_prose_keeps_sentences_that_fit_together() -> None:
    chunks = chunk_markdown("One two three. Four five six. Seven eight.", chunk_size=5)

    assert [chunk.content for chunk in chunks] == [
        "One two three.",
        "Four five six. Seven eight.",
    ]


def test_long_sentence_splits_at_words_with_actual_line_ranges() -> None:
    chunks = chunk_markdown("one two\nthree four\nfive six", chunk_size=2)

    assert [chunk.content for chunk in chunks] == ["one two", "three four", "five six"]
    assert [
        (chunk.metadata["start_line"], chunk.metadata["end_line"]) for chunk in chunks
    ] == [(1, 1), (2, 2), (3, 3)]


def test_split_prose_preserves_whitespace_and_tracks_multiline_sentences() -> None:
    chunks = chunk_markdown(
        "First  sentence\nends here.\nNext sentence ends.", chunk_size=4
    )

    assert [chunk.content for chunk in chunks] == [
        "First  sentence\nends here.",
        "Next sentence ends.",
    ]
    assert [
        (chunk.metadata["start_line"], chunk.metadata["end_line"]) for chunk in chunks
    ] == [(1, 2), (3, 3)]


def test_adjacent_paragraphs_share_a_chunk_but_repeated_sections_do_not() -> None:
    chunks = chunk_markdown(
        "# Setup\n\nFirst paragraph.\n\nSecond paragraph.\n\n# Setup\n\nSeparate section.",
        chunk_size=20,
    )

    assert [chunk.content for chunk in chunks] == [
        "# Setup\n\nFirst paragraph.\n\nSecond paragraph.",
        "# Setup\n\nSeparate section.",
    ]


@pytest.mark.parametrize("group_adjacent", [True, False])
def test_adjacent_grouping_can_be_enabled_or_disabled(group_adjacent: bool) -> None:
    chunks = chunk_markdown(
        "# Setup\n\nFirst paragraph.\n\nSecond paragraph.",
        chunk_size=20,
        group_adjacent=group_adjacent,
    )

    if group_adjacent:
        assert [chunk.content for chunk in chunks] == [
            "# Setup\n\nFirst paragraph.\n\nSecond paragraph.",
        ]
        assert chunks[0].metadata["start_line"] == 3
        assert chunks[0].metadata["end_line"] == 5
    else:
        assert [chunk.content for chunk in chunks] == [
            "# Setup\n\nFirst paragraph.",
            "# Setup\n\nSecond paragraph.",
        ]
        assert [
            (chunk.metadata["start_line"], chunk.metadata["end_line"])
            for chunk in chunks
        ] == [(3, 3), (5, 5)]


def test_list_splits_between_items_without_losing_nested_indentation() -> None:
    chunks = chunk_markdown(
        "- first item\n  - nested detail\n- second item",
        chunk_size=3,
    )

    assert [chunk.content for chunk in chunks] == [
        "- first item\n  - nested detail",
        "- second item",
    ]
    assert [
        (chunk.metadata["start_line"], chunk.metadata["end_line"]) for chunk in chunks
    ] == [(1, 2), (3, 3)]


def test_oversized_table_retains_header_separator_and_rows() -> None:
    table = "| Name | Value |\n| --- | ---: |\n| First | One |\n| Second | Two |"

    chunks = chunk_markdown(table, chunk_size=3)

    assert len(chunks) == 1
    assert chunks[0].content == table
    assert chunks[0].metadata["start_line"] == 1
    assert chunks[0].metadata["end_line"] == 4


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_chunk_size_must_be_positive(chunk_size: int) -> None:
    with pytest.raises(ValueError, match="chunk_size must be greater than zero"):
        chunk_markdown("Some text.", chunk_size=chunk_size)


# ---------------------------------------------------------------------------
# Documented regex examples
# ---------------------------------------------------------------------------
# Public chunker results verify the syntax examples beside the patterns.


@pytest.mark.parametrize(
    "heading, title, rendered_heading",
    [
        ("  ## Setup", "Setup", "## Setup"),
        ("## Setup ###", "Setup", "## Setup"),
        ("# C#", "C#", "# C#"),
    ],
)
def test_heading_examples(heading: str, title: str, rendered_heading: str) -> None:
    chunks = chunk_markdown(f"{heading}\n\nBody.", chunk_size=20)

    assert len(chunks) == 1
    assert chunks[0].content == f"{rendered_heading}\n\nBody."
    assert chunks[0].metadata["headings"] == [title]


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_fence_examples_preserve_code_headings(fence: str) -> None:
    code = f"  {fence}python\n# not a section\n  {fence}"

    chunks = chunk_markdown(f"# Setup\n\n{code}", chunk_size=3)

    assert len(chunks) == 1
    assert chunks[0].content == f"# Setup\n\n{code}"
    assert chunks[0].metadata["headings"] == ["Setup"]


@pytest.mark.parametrize("marker", ["-", "+", "*", "1.", "1)"])
def test_list_marker_examples(marker: str) -> None:
    first_item = f"  {marker} first item"
    second_item = f"  {marker} second item"

    chunks = chunk_markdown(f"{first_item}\n{second_item}", chunk_size=1)

    assert [chunk.content for chunk in chunks] == [first_item, second_item]


def test_quoted_sentence_ending_example() -> None:
    chunks = chunk_markdown('Say "all done!" Then go home.', chunk_size=4)

    assert [chunk.content for chunk in chunks] == ['Say "all done!"', "Then go home."]
