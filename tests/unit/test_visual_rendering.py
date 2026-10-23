from __future__ import annotations

import asyncio
import shutil
import struct
from unittest.mock import AsyncMock, Mock

import pytest

from app.extraction import visual


@pytest.mark.skipif(not shutil.which("pdftoppm") or not shutil.which("pdfinfo"), reason="Poppler is required")
async def test_real_pdf_pages_render_in_order_with_bounded_images(tmp_path, pdf_document):
    source = tmp_path / "source.pdf"
    source.write_bytes(pdf_document(("First page", "", "Third page")))

    assert await visual._page_count(source) == 3
    images = [await visual._render_page(source, number, tmp_path) for number in range(1, 4)]

    assert len(set(images)) == 3
    for image in images:
        width, height = struct.unpack(">II", image[16:24])
        assert 0 < width <= visual.IMAGE_DIMENSION
        assert 0 < height <= visual.IMAGE_DIMENSION
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize("metadata", [b"Pages: 0\n", b"Pages: 51\n", b"Unknown\n"])
async def test_invalid_pdf_page_count_fails_before_rendering(monkeypatch, tmp_path, metadata):
    monkeypatch.setattr(visual, "_run_tool", AsyncMock(return_value=metadata))
    with pytest.raises(ValueError):
        await visual._page_count(tmp_path / "source.pdf")


async def test_failed_render_removes_partial_image(monkeypatch, tmp_path):
    async def fail(*arguments):
        (tmp_path / "page.png").write_bytes(b"partial image")
        raise ValueError("render failed")

    monkeypatch.setattr(visual, "_run_tool", fail)
    with pytest.raises(ValueError, match="render failed"):
        await visual._render_page(tmp_path / "source.pdf", 1, tmp_path)
    assert not list(tmp_path.iterdir())


async def test_missing_poppler_has_an_explicit_error(monkeypatch):
    monkeypatch.setattr(visual.asyncio, "create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError))
    with pytest.raises(ValueError, match="install Poppler"):
        await visual._run_tool("pdfinfo", "source.pdf")


@pytest.mark.parametrize("failure", [TimeoutError, asyncio.CancelledError])
async def test_interrupted_tool_is_killed_and_reaped(monkeypatch, failure):
    process = Mock(returncode=None)
    process.communicate = AsyncMock(side_effect=[failure(), (b"", b"")])
    monkeypatch.setattr(visual.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    with pytest.raises(failure):
        await visual._run_tool("pdftoppm", "source.pdf")
    process.kill.assert_called_once()
    assert process.communicate.await_count == 2
