from __future__ import annotations

import asyncio
import importlib
import json
import os
from dataclasses import replace
from time import perf_counter

import pytest
from httpx import ASGITransport, AsyncClient

from app import embeddings, ingestion, retrieval, worker
from app.api.main import create_app
from app.cli import main
from app.retrieval import search
from app.storage import documents
from app.storage.records import ChunkInput


@pytest.mark.skipif(
    os.getenv("RAG_RUN_HOSTED_GENERATION_SMOKE") != "1",
    reason="Opt-in hosted smoke: requires credentials and makes billable generation calls",
)
@pytest.mark.parametrize(("provider", "model_name", "endpoint", "key_name"), [
    ("openai", "gpt-6-luna", "https://api.openai.com/v1", "OPENAI_API_KEY"),
    ("deepseek", "deepseek-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
])
async def test_hosted_generation_workflow(
    provider, model_name, endpoint, key_name, settings, storage, monkeypatch,
):
    if not os.getenv(key_name):
        pytest.fail(f"Set {key_name} before running the hosted smoke test", pytrace=False)
    settings = replace(
        settings, generation_provider=provider,
        generation_model=os.getenv(f"RAG_{provider.upper()}_SMOKE_MODEL", model_name),
        generation_base_url=endpoint, generation_max_tokens=2048,
        openai_api_key=os.getenv("OPENAI_API_KEY"), deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
    )
    source = await documents.insert_source_with_chunks(storage,
        tenant_id=settings.tenant_id, source_type="file", locator="/synthetic/hosted-smoke.md",
        mime_type="text/markdown", content_hash="hosted-smoke",
        chunks=[ChunkInput(
            "Documents / Documentos: Bring an identity document and proof of address. "
            "Leve um documento de identidade e um comprovante de endere\u00e7o.", {},
        )],
    )
    report = {"provider": provider, "model": settings.generation_model, "answers": []}
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        for question in [
            "Quais documentos devo levar? Responda em uma frase.",
            "Which documents should I bring? Answer in one sentence.",
        ]:
            started = perf_counter()
            response = await client.post("/ask", json={"query": question, "method": "lexical", "limit": 1})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["answer"].strip()
            assert len(result["matches"]) == 1
            assert result["matches"][0]["source_id"] == str(source.id)
            assert all(citation["source_id"] == str(source.id) for citation in result["citations"])
            report["answers"].append({
                "question": question, "answer": result["answer"],
                "mapped_citations": len(result["citations"]),
                "seconds": round(perf_counter() - started, 2),
            })
    print("Hosted generation smoke:\n" + json.dumps(report, ensure_ascii=False, indent=2))


@pytest.mark.usefixtures("inline_worker")
@pytest.mark.skipif(
    os.getenv("RAG_RUN_OLLAMA_SMOKE") != "1",
    reason="Opt-in smoke: requires local embeddings and a running Ollama model",
)
async def test_ollama_local_workflow(settings, storage, monkeypatch, capsys):
    local_module = importlib.import_module("sentence_transformers")
    settings = replace(
        settings, embedding_provider="local", chunk_size=180,
        generation_provider="ollama",
        generation_model=os.getenv("RAG_OLLAMA_SMOKE_MODEL", "qwen2.5:1.5b"),
        generation_base_url=os.getenv("RAG_OLLAMA_SMOKE_BASE_URL", "http://127.0.0.1:11434/v1"),
        generation_max_tokens=256,
    )
    model = local_module.SentenceTransformer(
        settings.embedding_model_name, device="cpu", trust_remote_code=False,
        local_files_only=True, revision="e8f8c211226b894fcb81acc59f3b34ba3efd5f42",
    )
    monkeypatch.setattr(embeddings, "_load_local_model", lambda name: model)
    monkeypatch.setattr(ingestion, "embed_texts", embeddings.embed_texts)
    monkeypatch.setattr(retrieval, "embed_texts", embeddings.embed_texts)
    document = (
        "# Housing support / Atendimento habitacional\n\n"
        "## Documents / Documentos\n\n"
        "Bring an identity document and proof of address. "
        "Leve um documento de identidade e um comprovante de endere\u00e7o.\n\n"
        "## Booking / Agendamento\n\n"
        "Book by telephone. Appointments are on Wednesdays at 10 am. "
        "Agende por telefone. O atendimento acontece nas quartas-feiras \u00e0s 10 horas.\n\n"
        "## Arrival / Chegada\n\n"
        "Arrive fifteen minutes before your appointment. "
        "Chegue quinze minutos antes do hor\u00e1rio marcado."
    )
    report = {"model": settings.generation_model, "answers": []}
    async with AsyncClient(
        transport=ASGITransport(app=create_app(settings)), base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        files = {"file": ("ollama-smoke.md", document.encode("utf-8"), "text/markdown")}
        uploaded = await client.post("/sources/file", files=files)
        assert uploaded.status_code == 202, uploaded.text
        assert await worker.run_once(settings=settings, storage=storage)
        source_id = uploaded.json()["id"]
        duplicate = await client.post("/sources/file", files=files)
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "unchanged"
        reindexed = await client.post("/sources/file?reindex=true", files=files)
        assert reindexed.status_code == 202
        assert await worker.run_once(settings=settings, storage=storage)
        assert reindexed.json()["id"] == source_id
        assert (await client.get(reindexed.json()["status_url"])).json()["status"] == "completed"

        async with storage.connection() as connection:
            cursor = await connection.execute(
                "SELECT vector_dims(embedding) AS dimensions FROM chunks WHERE tenant_id = %s",
                (settings.tenant_id,),
            )
            dimensions = await cursor.fetchall()
        assert dimensions and all(row["dimensions"] == 384 for row in dimensions)
        for method in ["cosine", "window", "lexical", "hybrid"]:
            result = await client.post("/search", json={"query": "documentos", "method": method, "limit": 1})
            assert result.status_code == 200, result.text
            assert result.json()
            assert all(match["source_id"] == source_id for match in result.json())

        for question, window in [
            ("Quais documentos devo levar? Responda em uma frase.", 0),
            ("How can I book an appointment? Answer in one sentence.", 0),
            ("How can I book an appointment? Answer in one sentence.", 2),
        ]:
            started = perf_counter()
            response = await client.post("/ask", json={"query": question, "limit": 1, "window": window})
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["answer"] and result["matches"]
            for citation in result["citations"]:
                assert citation["source_id"] == source_id
                assert citation["content"]
                assert f'[{citation["id"]}]' in result["answer"]
                assert any(
                    match["source_id"] == citation["source_id"]
                    and match["chunk_index"] == citation["chunk_index"]
                    and match["content"].startswith(citation["content"])
                    for match in result["matches"]
                )
            report["answers"].append({
                "question": question, "answer": result["answer"],
                "window": window,
                "mapped_citations": len(result["citations"]),
                "seconds": round(perf_counter() - started, 2),
            })

    empty_app = create_app(replace(settings, tenant_id="empty-ollama-smoke"))
    async with AsyncClient(
        transport=ASGITransport(app=empty_app), base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        empty = await client.post("/ask", json={"query": "Any sources?"})
        assert empty.status_code == 200
        assert empty.json()["matches"] == empty.json()["citations"] == []
    missing_app = create_app(replace(settings, generation_model="rag-mtst-smoke-missing-model"))
    async with AsyncClient(
        transport=ASGITransport(app=missing_app), base_url="http://test",
        headers={"Authorization": f"Bearer {settings.api_key}"},
    ) as client:
        missing = await client.post("/ask", json={"query": "documents", "limit": 1, "window": 0})
        assert missing.status_code == 502

    for name, value in {
        "DATABASE_URL": settings.database_url, "RAG_DATA_DIR": str(settings.data_dir),
        "RAG_TENANT_ID": settings.tenant_id, "RAG_EMBEDDING_PROVIDER": "local",
        "RAG_GENERATION_PROVIDER": "ollama", "RAG_GENERATION_MODEL": settings.generation_model,
        "RAG_GENERATION_BASE_URL": settings.generation_base_url, "RAG_GENERATION_MAX_TOKENS": "256",
    }.items():
        monkeypatch.setenv(name, value)
    document_path = settings.data_dir.parent / "ollama-smoke.md"
    document_path.write_text(document, encoding="utf-8")
    capsys.readouterr()
    assert await asyncio.to_thread(main, ["add", str(document_path)]) == 0
    assert "already indexed" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["search", "documentos", "--method", "hybrid", "--limit", "1"]) == 0
    assert "Documents" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["ask", "Which documents should I bring?", "--limit", "1", "--window", "0"]) == 0
    assert capsys.readouterr().out.strip()
    print("Ollama local workflow smoke:\n" + json.dumps(report, ensure_ascii=False, indent=2))


@pytest.mark.skipif(
    os.getenv("RAG_RUN_LOCAL_BASELINE") != "1",
    reason="Opt-in baseline: requires the local extra and a cached model",
)
async def test_portuguese_local_retrieval_baseline(settings, storage, monkeypatch):
    local_module = importlib.import_module("sentence_transformers")
    settings = replace(settings, embedding_provider="local", chunk_size=180, retrieval_window=2)
    revision = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    model = local_module.SentenceTransformer(
        settings.embedding_model_name, device="cpu", trust_remote_code=False, local_files_only=True,
        revision=revision,
    )
    monkeypatch.setattr(embeddings, "_load_local_model", lambda name: model)
    monkeypatch.setattr(ingestion, "embed_texts", embeddings.embed_texts)
    monkeypatch.setattr(retrieval, "embed_texts", embeddings.embed_texts)
    document = (
        "# Atendimento habitacional\n\n"
        "## Inscri\u00e7\u00e3o\n\n"
        "O cadastro para atendimento habitacional pode ser feito por qualquer fam\u00edlia "
        "que precise de orienta\u00e7\u00e3o sobre moradia. A inscri\u00e7\u00e3o \u00e9 gratuita.\n\n"
        "## Documentos\n\n"
        "Para solicitar apoio, apresente um documento de identidade, um comprovante de "
        "endere\u00e7o e os comprovantes de renda das pessoas da fam\u00edlia.\n\n"
        "## Agendamento\n\n"
        "As consultas acontecem nas quartas-feiras. Quem n\u00e3o tem acesso \u00e0 internet "
        "pode reservar um hor\u00e1rio pelo telefone ou presencialmente na secretaria.\n\n"
        "## Chegada\n\n"
        "No dia da consulta, chegue quinze minutos antes do hor\u00e1rio marcado. "
        "A recep\u00e7\u00e3o fica no port\u00e3o principal e confirma a presen\u00e7a de cada fam\u00edlia.\n\n"
        "## Acompanhamento\n\n"
        "Depois do atendimento, guarde o n\u00famero do protocolo. Ele permite consultar "
        "o andamento do pedido e apresentar novas informa\u00e7\u00f5es durante o retorno.\n\n"
        "## Prote\u00e7\u00e3o de dados\n\n"
        "Somente a equipe responsavel pelo atendimento pode consultar os dados pessoais. "
        "As informa\u00e7\u00f5es das fam\u00edlias n\u00e3o s\u00e3o compartilhadas com empresas.\n\n"
        "## Doa\u00e7\u00f5es\n\n"
        "O dep\u00f3sito recebe roupas e cobertores aos s\u00e1bados pela manh\u00e3. "
        "As pe\u00e7as devem estar limpas e em boas condi\u00e7\u00f5es para serem doadas.\n\n"
        "## Cozinha comunit\u00e1ria\n\n"
        "A cozinha comunit\u00e1ria oferece almo\u00e7o gratuito aos domingos, no sal\u00e3o do bairro. "
        "N\u00e3o \u00e9 necess\u00e1rio fazer cadastro para receber uma refei\u00e7\u00e3o."
    )
    cases = [
        ("Q1", "Que pap\u00e9is preciso apresentar para solicitar ajuda?", {"Documentos"}),
        ("Q2", "N\u00e3o tenho acesso \u00e0 internet. Como marco uma conversa?", {"Agendamento"}),
        ("Q3", "Com quanto tempo de anteced\u00eancia devo estar no local?", {"Chegada"}),
        ("Q4", "Quem pode consultar minhas informa\u00e7\u00f5es pessoais?", {"Prote\u00e7\u00e3o de dados"}),
        ("Q5", "Quando posso entregar roupas para doa\u00e7\u00e3o?", {"Doa\u00e7\u00f5es"}),
        ("Q6", "Onde consigo uma refei\u00e7\u00e3o sem pagar no fim de semana?", {"Cozinha comunit\u00e1ria"}),
        ("Q7", "Como reservo uma consulta sem internet e quando devo chegar?", {"Agendamento", "Chegada"}),
    ]
    result = await ingestion.add_bytes(
        document.encode("utf-8"), source_name="atendimento-baseline.md", settings=settings, storage=storage,
    )
    chunks = await documents.list_chunks(storage, settings.tenant_id)
    headings = {chunk.chunk_index: chunk.metadata["heading"] for chunk in chunks}
    report = {
        "model": settings.embedding_model_name,
        "revision": revision,
        "sentence_transformers": local_module.__version__,
        "max_seq_length": model.max_seq_length,
        "chunk_size": settings.chunk_size,
        "chunk_count": result.chunk_count,
        "limit": 1,
        "window": settings.retrieval_window,
        "hybrid_rank_constant": 60,
        "hybrid_candidates_per_branch": 20,
        "cases": [],
    }
    for case_id, query, expected in cases:
        cosine = await search(query, method="cosine", limit=1, settings=settings, storage=storage)
        windows = await search(query, limit=1, settings=settings, storage=storage)
        zero_window = await search(query, window=0, limit=1, settings=settings, storage=storage)
        lexical = await search(query, method="lexical", limit=1, settings=settings, storage=storage)
        hybrid = await search(query, method="hybrid", limit=1, settings=settings, storage=storage)
        assert zero_window == cosine
        assert windows[:len(cosine)] == cosine
        assert all(match.score is None for match in windows[len(cosine):])
        assert len({(match.source_id, match.chunk_index) for match in windows}) == len(windows)
        case_report = {"id": case_id, "query": query, "expected": sorted(expected)}
        for method, matches in [("cosine", cosine), ("window", windows), ("lexical", lexical), ("hybrid", hybrid)]:
            returned = [headings[match.chunk_index] for match in matches]
            case_report[method] = {
                "headings": returned,
                "scores": [round(match.score, 4) if match.score is not None else None for match in matches],
                "all_expected_present": expected.issubset(returned),
            }
        report["cases"].append(case_report)
    print("\nPortuguese local retrieval baseline:\n" + json.dumps(report, ensure_ascii=False, indent=2))
