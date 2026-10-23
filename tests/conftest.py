from __future__ import annotations
from io import BytesIO
import json
import shutil
from zipfile import ZipFile
from anthropic import AsyncAnthropic
from httpx import AsyncClient, MockTransport, Response
from httpx2 import AsyncClient as AnthropicHTTPClient, MockTransport as AnthropicTransport, Response as AnthropicResponse
from openai import AsyncOpenAI
import pytest
from app import llm
from app.extraction import visual


@pytest.fixture(scope="session")
def openai_response():
    def build(content, *, model="test-model", finish="stop", tokens=32, usage=True, refusal=None):
        return {
            "id": "response", "object": "response", "created_at": 0, "model": model,
            "status": "completed" if finish == "stop" else "incomplete",
            "error": None,
            "incomplete_details": None if finish == "stop" else {
                "reason": "max_output_tokens" if finish == "length" else "content_filter",
            },
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{
                "id": "message", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "refusal", "refusal": refusal}] if refusal is not None else [
                    {"type": "output_text", "text": content, "annotations": []},
                ],
            }],
            "usage": {
                "input_tokens": 100, "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens": tokens, "output_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 100 + tokens,
            } if usage else None,
        }

    return build


@pytest.fixture
def vision_reply(monkeypatch, tmp_path, openai_response):
    if not shutil.which("pdftoppm") or not shutil.which("pdfinfo"):
        pytest.skip("Poppler is required")
    requests = []
    temporary_root = tmp_path / "visual-temporary"
    temporary_root.mkdir()
    original_temporary_directory = visual.TemporaryDirectory
    monkeypatch.setattr(visual, "TemporaryDirectory", lambda **kwargs: original_temporary_directory(dir=temporary_root, **kwargs))

    def install(pages, *, finish="stop", status=200, tokens=32, usage=True, raw=None, refusal=None):
        def respond(request):
            requests.append(request)
            response_type = AnthropicResponse if request.url.path.endswith("/messages") else Response
            if status != 200:
                return response_type(status, json={"error": {"message": "private provider detail"}})
            page = pages[len(requests) - 1]
            if request.url.path.endswith("/messages"):
                return AnthropicResponse(200, json={
                    "id": "message", "type": "message", "role": "assistant", "model": "vision-model",
                    "content": [{"type": "text", "text": raw if raw is not None else json.dumps(page)}],
                    "stop_reason": "end_turn" if finish == "stop" else finish, "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": tokens},
                })
            if request.url.path.endswith("/responses"):
                return Response(200, json=openai_response(
                    raw if raw is not None else json.dumps(page), model="vision-model",
                    finish=finish, tokens=tokens, usage=usage, refusal=refusal,
                ))
            return Response(200, json={
                "id": "completion", "object": "chat.completion", "created": 0,
                "model": "vision-model", "choices": [{
                    "index": 0, "finish_reason": finish,
                    "message": {
                        "role": "assistant", "content": raw if raw is not None else json.dumps(page),
                        "refusal": refusal,
                    },
                }],
                "usage": {"prompt_tokens": 100, "completion_tokens": tokens, "total_tokens": 100 + tokens} if usage else None,
            })

        def client(**kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["timeout"] == visual.REQUEST_TIMEOUT_SECONDS
            return AsyncOpenAI(**kwargs, http_client=AsyncClient(transport=MockTransport(respond)))

        def anthropic_client(**kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["timeout"] == visual.REQUEST_TIMEOUT_SECONDS
            return AsyncAnthropic(**kwargs, http_client=AnthropicHTTPClient(transport=AnthropicTransport(respond)))

        monkeypatch.setattr(llm, "AsyncOpenAI", client)
        monkeypatch.setattr(llm, "AsyncAnthropic", anthropic_client)
        return requests

    yield install
    assert not list(temporary_root.iterdir()), "Visual extraction must remove temporary PDFs and images"


@pytest.fixture
def pdf_document():
    def build(pages: tuple[str, ...] = ("Native PDF text",)) -> bytes:
        page_ids = [4 + 2 * index for index in range(len(pages))]
        children = " ".join(f"{number} 0 R" for number in page_ids)
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{children}] /Count {len(pages)} >>".encode(),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        for number, text in zip(page_ids, pages, strict=True):
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode() if text else b""
            objects.extend([
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {number + 1} 0 R >>".encode(),
                b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            ])
        document = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(document))
            document.extend(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
        xref_offset = len(document)
        document.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
        for offset in offsets[1:]:
            document.extend(f"{offset:010d} 00000 n \n".encode())
        document.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode())
        return bytes(document)

    return build


@pytest.fixture
def office_document():
    def build(suffix: str) -> bytes:
        package = BytesIO()
        if suffix == ".docx":
            members = {
                "word/styles.xml": '''<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>''',
                "word/document.xml": '''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Native heading</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Material</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Count</w:t></w:r></w:p></w:tc></w:tr>
<w:tr><w:tc><w:p><w:r><w:t>Bricks</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>42</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>''',
            }
        else:
            members = {
                "ppt/presentation.xml": '''<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>''',
                "ppt/_rels/presentation.xml.rels": '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>''',
                "ppt/slides/slide1.xml": '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr>
<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>Native heading</a:t></a:r></a:p></p:txBody></p:sp>
<p:graphicFrame><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table"><a:tbl>
<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Material</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>Count</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
<a:tr><a:tc><a:txBody><a:p><a:r><a:t>Bricks</a:t></a:r></a:p></a:txBody></a:tc><a:tc><a:txBody><a:p><a:r><a:t>42</a:t></a:r></a:p></a:txBody></a:tc></a:tr>
</a:tbl></a:graphicData></a:graphic></p:graphicFrame></p:spTree></p:cSld></p:sld>''',
            }
        main_part = "word/document.xml" if suffix == ".docx" else "ppt/presentation.xml"
        main_type = "wordprocessingml.document" if suffix == ".docx" else "presentationml.presentation"
        members["[Content_Types].xml"] = f'''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/{main_part}" ContentType="application/vnd.openxmlformats-officedocument.{main_type}.main+xml"/></Types>'''
        members["_rels/.rels"] = f'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="{main_part}"/></Relationships>'''
        with ZipFile(package, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return package.getvalue()

    return build
