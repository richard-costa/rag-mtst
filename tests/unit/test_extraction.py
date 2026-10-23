from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.config import Settings
from app.extraction import extract_source
from app.extraction import parser


@pytest.mark.parametrize("value", [None, ""])
async def test_visual_settings_are_optional_for_parser(monkeypatch, value):
    for name in ("RAG_VISUAL_MODEL", "RAG_VISUAL_BASE_URL"):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("OPENAI_API_KEY", "private-generation-key")
    monkeypatch.setenv("RAG_GENERATION_MODEL", "answer-model")
    settings = Settings.from_environment()

    assert settings.visual_model is None
    assert settings.visual_base_url is None
    extracted = await extract_source(b"parser only", ".txt", settings=settings)
    assert extracted.text == "parser only"


@pytest.mark.parametrize("pages", [
    (parser.ExtractedPage(2, "Second"),),
    (parser.ExtractedPage(1, "First"), parser.ExtractedPage(1, "Duplicate")),
    (parser.ExtractedPage(1, "First"), parser.ExtractedPage(3, "Third")),
    (parser.ExtractedPage(1, "First"), parser.ExtractedPage(2, "Second", "slide")),
])
def test_extraction_pages_reject_missing_repeated_or_mixed_numbering(pages):
    with pytest.raises(ValueError):
        parser.ExtractedContent.from_pages(pages, format="pdf", profile={})


@pytest.mark.parametrize("method", ["Visual", "unknown", "", "Parser"])
async def test_invalid_extraction_selection_fails_before_parser(monkeypatch, method) -> None:
    def reject_parse(*args, **kwargs):
        pytest.fail("Invalid extraction selection must not invoke parsing")

    monkeypatch.setattr(parser, "extract_with_parser", reject_parse)
    with pytest.raises(ValueError, match="Unsupported extraction method"):
        await extract_source(b"content", ".txt", extraction_method=method, settings=Settings())


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
# Plain text uses the lightweight parser path without conversion services.

@pytest.mark.parametrize("suffix", [".txt", ".md", ".markdown", ".MD"])
async def test_plain_text_routes_through_parser(suffix) -> None:
    extracted = await extract_source(b"hello world", suffix, settings=Settings())

    assert extracted.text == "hello world"
    assert extracted.format == suffix.casefold().removeprefix(".")


@pytest.mark.parametrize("has_text", [False, True])
async def test_real_pdf_text_and_ocr_boundary(has_text) -> None:
    stream = b"BT /F1 12 Tf 72 720 Td (Native PDF text) Tj ET" if has_text else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = len(document)
    document.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())

    if has_text:
        extracted = await extract_source(bytes(document), ".pdf", settings=Settings())
        assert "Native PDF text" in extracted.text
        assert extracted.format == "pdf"
    else:
        with pytest.raises(ValueError, match="PDF requires OCR, which is not enabled"):
            await extract_source(bytes(document), ".pdf", settings=Settings())


# ---------------------------------------------------------------------------
# Office extraction
# ---------------------------------------------------------------------------
# Native Office parsing does not need a conversion service.

@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
async def test_native_office_extraction_without_converter(monkeypatch, suffix, office_document) -> None:
    def reject_conversion(*args, **kwargs):
        pytest.fail("Native parsing must not invoke Office conversion")

    monkeypatch.setattr(parser.subprocess, "run", reject_conversion)
    extracted = await extract_source(office_document(suffix), suffix, settings=Settings())

    assert extracted.format == suffix.removeprefix(".")
    assert "# Native heading" in extracted.text
    assert "| Material | Count |" in extracted.text
    assert "| Bricks | 42 |" in extracted.text


@pytest.mark.parametrize("suffix", [".pdf", ".docx", ".pptx"])
async def test_malformed_documents_fail_without_conversion(suffix) -> None:
    with pytest.raises(ValueError, match=f"Could not parse {suffix[1:].upper()}"):
        await extract_source(b"invalid document", suffix, settings=Settings())


@pytest.mark.parametrize("suffix", [".txt", ".md", ".markdown", ".pdf", ".docx", ".pptx"])
async def test_empty_extraction_is_rejected(monkeypatch, suffix) -> None:
    monkeypatch.setattr(parser.anydoc, "to_markdown_bytes", lambda *args: " \n ")
    with pytest.raises(ValueError, match="does not contain readable text"):
        await extract_source(b" \n ", suffix, settings=Settings())


async def test_pdf_requiring_ocr_is_rejected(monkeypatch) -> None:
    def needs_ocr(*args):
        raise parser.anydoc.NeedsOcrError("scanned document")

    monkeypatch.setattr(parser.anydoc, "to_markdown_bytes", needs_ocr)
    with pytest.raises(ValueError, match="PDF requires OCR, which is not enabled"):
        await extract_source(b"scanned PDF", ".pdf", settings=Settings())


@pytest.mark.parametrize("suffix", [".xlsx", ".html", ".doc", ""])
async def test_unsupported_formats_remain_rejected(monkeypatch, suffix) -> None:
    def reject_parse(*args):
        pytest.fail("Unsupported formats must not reach AnyDoc")

    monkeypatch.setattr(parser.anydoc, "to_markdown_bytes", reject_parse)
    with pytest.raises(ValueError, match="Unsupported file type"):
        await extract_source(b"content", suffix, settings=Settings())


@pytest.mark.parametrize("converter_path", [None, "/environment/bin/unoconvert"])
@pytest.mark.parametrize("suffix", [".docx", ".pptx"])
def test_explicit_office_conversion(monkeypatch, converter_path, suffix) -> None:
    def find_converter(command, *, path):
        assert command == "unoconvert"
        assert path == str(Path(sys.executable).parent)
        return converter_path

    def create_pdf(command, **kwargs):
        assert command[0] == (converter_path or "unoconvert")
        assert command[1:7] == ["--host", "office", "--port", "2003", "--host-location", "remote"]
        assert ("ExportHiddenSlides=true" in command) is (suffix == ".pptx")
        if suffix == ".pptx":
            assert "ExportNotesPages=false" in command
            assert "ExportOnlyNotesPages=false" in command
        target = Path(command[-1])
        target.write_bytes(b"%PDF-1.4\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(shutil, "which", find_converter)
    monkeypatch.setattr(parser.subprocess, "run", create_pdf)
    converted = parser._convert_office_to_pdf(
        b"fake office", suffix, host="office", port=2003,
    )

    assert converted == b"%PDF-1.4\n"
