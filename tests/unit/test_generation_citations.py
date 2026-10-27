from __future__ import annotations

import pytest

from app import generation


@pytest.mark.parametrize(
    ("text", "citations", "expected_ids"),
    [
        ("No citations", [], []),
        ("Grouped references [1, 2].", [1, 2], [1, 2]),
        ("Reference range [1-2].", [1, 2], [1, 2]),
        ("Repeated reference [2] [2].", [2, 2], [2]),
        ("The passage provides the answer.", [1], [1]),
        ("Sources are returned separately.", [2, 1, 2], [1, 2]),
        ("Prose containing [99] is not citation metadata.", [], []),
        ("Optional inline marker [1].", [], []),
    ],
)
async def test_valid_structured_citations_preserve_source_order(
    text,
    citations,
    expected_ids,
    generation_settings,
    passages,
    completion,
):
    completion(text, citations=citations)
    result = await generation.answer("Question", settings=generation_settings)
    assert result.text == text
    assert result.matches == passages
    assert [citation.id for citation in result.citations] == expected_ids


@pytest.mark.parametrize(
    "text, citations",
    [
        ("Unknown reference [99].", [99]),
        ("Unknown source without an inline marker.", [99]),
        ("Invalid source.", [0]),
        ("Negative source.", [-1]),
    ],
)
async def test_unknown_structured_citations_are_rejected(
    text,
    citations,
    generation_settings,
    passages,
    completion,
):
    completion(text, citations=citations)
    with pytest.raises(generation.GenerationError, match="invalid citations"):
        await generation.answer("Question", settings=generation_settings)
