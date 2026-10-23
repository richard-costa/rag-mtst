"""Native parser extraction and optional Office-to-PDF conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Literal, Self

import anydoc


# ---------------------------------------------------------------------------
# Supported source types
# ---------------------------------------------------------------------------
# Text is decoded directly; PDF and Office formats use native AnyDoc parsing.

TEXT_SUFFIXES = frozenset({".md", ".markdown", ".txt"})
OFFICE_SUFFIXES = frozenset({".docx", ".pptx"})
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | OFFICE_SUFFIXES | {".pdf"}


# ---------------------------------------------------------------------------
# Extraction result
# ---------------------------------------------------------------------------
# All parser strategies return normalized text with the originating file format.

@dataclass(frozen=True, slots=True)
class ExtractedPage:
    number: int
    text: str
    kind: Literal["page", "slide"] = "page"

    def __post_init__(self) -> None:
        if self.number < 1 or self.kind not in {"page", "slide"}:
            raise ValueError("Extraction pages need a positive number and a page or slide kind")


@dataclass(frozen=True, slots=True)
class ExtractedContent:
    text: str
    format: str
    profile: dict[str, object] = field(default_factory=dict)
    pages: tuple[ExtractedPage, ...] = ()

    def __post_init__(self) -> None:
        if self.pages:
            if [page.number for page in self.pages] != list(range(1, len(self.pages) + 1)):
                raise ValueError("Extraction pages must be ordered and contiguous, including blank pages")
            if any(page.kind != self.pages[0].kind for page in self.pages):
                raise ValueError("Extraction cannot mix page and slide numbering")
            if self.text != "\n\n".join(page.text for page in self.pages):
                raise ValueError("Page provenance does not match extracted text")

    @classmethod
    def from_pages(
        cls, pages: tuple[ExtractedPage, ...], *, format: str, profile: dict[str, object],
    ) -> Self:
        if not pages:
            raise ValueError("At least one extraction page is required")
        return cls(text="\n\n".join(page.text for page in pages), format=format, profile=profile, pages=pages)


def get_extraction_profile(suffix: str) -> dict[str, object]:
    normalized_suffix = suffix.casefold()
    if normalized_suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(
            f"Unsupported file type {suffix or '<none>'}; supported types: {supported}"
        )
    profile: dict[str, object] = {
        "method": "parser", "format": normalized_suffix.removeprefix("."),
    }
    if normalized_suffix in TEXT_SUFFIXES:
        return {**profile, "engine": "utf-8", "errors": "replace"}
    return {**profile, "engine": "anydoc", "engine_version": version("firecrawl-anydoc")}


# ---------------------------------------------------------------------------
# Parser-based extraction
# ---------------------------------------------------------------------------
# This selects the appropriate text, PDF, or office-document strategy by suffix.

def extract_with_parser(
    content: bytes,
    suffix: str,
    *,
    office_host: str,
    office_port: int,
) -> ExtractedContent:
    normalized_suffix = suffix.casefold()
    profile = get_extraction_profile(normalized_suffix)

    if normalized_suffix in TEXT_SUFFIXES:
        text = content.decode("utf-8", errors="replace").strip()
        if not text:
            raise ValueError("The source does not contain readable text")
        return ExtractedContent(text=text, format=normalized_suffix.removeprefix("."), profile=profile)

    if normalized_suffix in OFFICE_SUFFIXES | {".pdf"}:
        source_format = normalized_suffix.removeprefix(".")
        return ExtractedContent(
            text=_extract_document(content, source_format),
            format=source_format,
            profile=profile,
        )

    supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
    raise ValueError(
        f"Unsupported file type {suffix or '<none>'}; supported types: {supported}"
    )


# ---------------------------------------------------------------------------
# Native document extraction
# ---------------------------------------------------------------------------
# AnyDoc returns Markdown-like text and surfaces format-specific failures.

def _extract_document(content: bytes, source_format: str) -> str:
    try:
        text = anydoc.to_markdown_bytes(content, source_format).strip()
    except anydoc.NeedsOcrError as error:
        raise ValueError(f"The {source_format.upper()} requires OCR, which is not enabled") from error
    except anydoc.ConvertError as error:
        raise ValueError(f"Could not parse {source_format.upper()}: {error}") from error

    if not text:
        raise ValueError("The source does not contain readable text")
    return text


# ---------------------------------------------------------------------------
# Office conversion
# ---------------------------------------------------------------------------
# This optional converter is separate from native parsing and never used as a fallback.

def _convert_office_to_pdf(
    content: bytes,
    suffix: str,
    *,
    host: str,
    port: int,
) -> bytes:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        source = directory / f"source{suffix}"
        target = directory / "output.pdf"
        source.write_bytes(content)

        converter = shutil.which("unoconvert", path=str(Path(sys.executable).parent)) or "unoconvert"
        filter_options = []
        if suffix.casefold() == ".pptx":
            filter_options = [
                "--filter-option", "ExportHiddenSlides=true",
                "--filter-option", "ExportNotesPages=false",
                "--filter-option", "ExportOnlyNotesPages=false",
            ]
        try:
            subprocess.run(
                [
                    converter,
                    "--host",
                    host,
                    "--port",
                    str(port),
                    "--host-location",
                    "remote",
                    "--convert-to",
                    "pdf",
                    *filter_options,
                    str(source),
                    str(target),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except FileNotFoundError as error:
            raise ValueError(
                "Office conversion client is unavailable; install the unoserver package"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise ValueError("Office conversion timed out") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip()
            message = f"Office conversion failed: {detail}" if detail else "Office conversion failed"
            raise ValueError(message) from error

        if not target.is_file():
            raise ValueError("Office conversion did not produce a PDF")

        return target.read_bytes()
