"""Source extraction routing."""

from __future__ import annotations

import asyncio

from app.config import Settings, get_settings
from app.extraction import parser, visual


# ---------------------------------------------------------------------------
# Parser contract re-exports
# ---------------------------------------------------------------------------
# Callers use these shared types without depending on the parser implementation module.

ExtractedContent = parser.ExtractedContent
ExtractedPage = parser.ExtractedPage
SUPPORTED_SUFFIXES = parser.SUPPORTED_SUFFIXES


def validate_extraction_method(method: str) -> None:
    """Reject unsupported document extraction strategies.

    Args:
        method: Optional retrieval algorithm override.
    """
    if method not in {"parser", "visual"}:
        raise ValueError(f"Unsupported extraction method {method!r}; choose parser or visual")


def get_extraction_profile(
    suffix: str, *, extraction_method: str = "parser", settings: Settings | None = None,
) -> dict[str, object]:
    """Describe the extractor and configuration used for a source format.

    Args:
        suffix: Filename extension identifying the source format.
        extraction_method: Selected extraction strategy (parser or visual).
        settings: Runtime settings for extraction, storage, or models.

    Returns:
        Reproducible extractor configuration metadata.
    """
    validate_extraction_method(extraction_method)
    if extraction_method == "visual":
        return visual.get_extraction_profile(suffix, settings or get_settings())
    return parser.get_extraction_profile(suffix)


# ---------------------------------------------------------------------------
# Async extraction facade
# ---------------------------------------------------------------------------
# Parser work runs in a thread so async API and ingestion code do not block.

async def extract_source(
    content: bytes,
    suffix: str,
    *,
    settings: Settings | None = None,
    extraction_method: str = "parser",
) -> ExtractedContent:
    """Extract text and page provenance using the requested strategy.

    Args:
        content: Original document bytes to extract or index.
        suffix: Filename extension identifying the source format.
        settings: Runtime settings for extraction, storage, or models.
        extraction_method: Selected extraction strategy (parser or visual).

    Returns:
        Extracted text with page or slide metadata.
    """
    validate_extraction_method(extraction_method)
    active_settings = settings or get_settings()
    if extraction_method == "visual":
        return await visual.extract_with_visual(content, suffix, settings=active_settings)
    return await asyncio.to_thread(
        parser.extract_with_parser,
        content,
        suffix,
        office_host=active_settings.office_host,
        office_port=active_settings.office_port,
    )
