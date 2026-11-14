from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_api_settings, get_storage
from app.api.main import create_app
from app.config import Settings
from app.generation import Answer
from app.storage.conversations import ConversationBusy, ConversationNotFound
from app.storage.database import Database
from app.storage.documents import SourceBusy, SourceNotFound
from app.storage.records import SourceSummary

_UUID = "00000000-0000-0000-0000-000000000001"
# API routes intentionally reachable without a token, as (method, path template).
_PUBLIC_ROUTES: set[tuple[str, str]] = set()
# Discovered from OpenAPI; a route hidden from the schema needs its own test.
_OPENAPI = create_app(Settings(api_key="test-key")).openapi()
_PROTECTED_OPERATIONS = [
    (method.upper(), path, operation)
    for path, operations in _OPENAPI["paths"].items()
    for method, operation in operations.items()
    if (method.upper(), path) not in _PUBLIC_ROUTES
]


def _api_operations() -> list[tuple[str, str]]:
    return sorted(
        (method, re.sub(r"\{[^}]+\}", _UUID, path))
        for method, path, _operation in _PROTECTED_OPERATIONS
    )


@pytest.mark.parametrize(
    "api_key", [None, "", " ", "token with spaces", "non-ascii-\u00e9"]
)
def test_api_refuses_startup_without_a_valid_key(api_key) -> None:
    with (
        pytest.raises(ValueError, match="RAG_API_KEY"),
        TestClient(create_app(Settings(api_key=api_key))),
    ):
        pytest.fail("API startup must reject invalid authentication configuration")


@pytest.mark.parametrize("method,path", _api_operations())
@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong-key", "Basic test-key", "Bearer"]
)
def test_every_api_route_rejects_unauthenticated_requests(
    monkeypatch, tmp_path, method, path, authorization
) -> None:
    def unexpected(*args, **kwargs):
        pytest.fail("Unauthenticated requests must not reach storage")

    monkeypatch.setattr(Database, "connection", unexpected)
    monkeypatch.setattr(
        "app.api.services.answer",
        AsyncMock(side_effect=AssertionError("Generation must not execute")),
    )
    settings = Settings(api_key="test-key", data_dir=tmp_path / "data")
    headers = {"Authorization": authorization} if authorization else {}
    with TestClient(create_app(settings)) as client:
        response = client.request(
            method, path, headers=headers, json={"query": "question"}
        )
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or missing API credentials"}
    assert not settings.data_dir.exists()


def test_api_accepts_valid_key_and_keeps_server_configured_tenant(monkeypatch) -> None:
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.routers.search.search", search)
    settings = Settings(api_key="test-key", tenant_id="server-tenant")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/search",
            json={"query": "question"},
            headers={"Authorization": "Bearer test-key", "X-Tenant-ID": "other-tenant"},
        )
    assert response.status_code == 200
    assert response.json() == []
    assert search.call_args.kwargs["settings"].tenant_id == "server-tenant"


def test_api_dependencies_remain_isolated_between_applications(monkeypatch) -> None:
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.routers.search.search", search)
    first_settings = Settings(api_key="first-key", tenant_id="first-tenant")
    second_settings = Settings(api_key="second-key", tenant_id="second-tenant")
    first_app = create_app(first_settings)
    second_app = create_app(second_settings)
    with TestClient(first_app) as first, TestClient(second_app) as second:
        for client, settings, application in (
            (first, first_settings, first_app),
            (second, second_settings, second_app),
            (first, first_settings, first_app),
        ):
            response = client.post(
                "/search",
                json={"query": "question"},
                headers={"Authorization": f"Bearer {settings.api_key}"},
            )
            assert response.status_code == 200
            assert search.call_args.kwargs["settings"] is settings
            assert search.call_args.kwargs["storage"] is application.state.storage
        assert (
            first.post(
                "/search",
                json={"query": "question"},
                headers={"Authorization": "Bearer second-key"},
            ).status_code
            == 401
        )
    assert first_app.state.storage is not second_app.state.storage
    assert search.await_count == 3


def test_api_resource_dependencies_can_be_overridden(monkeypatch) -> None:
    search = AsyncMock(return_value=[])
    monkeypatch.setattr("app.api.routers.search.search", search)
    application = create_app(Settings(api_key="configured-key"))
    settings = Settings(api_key="override-key", tenant_id="override-tenant")
    storage = Database(settings.database_url)
    application.dependency_overrides[get_api_settings] = lambda: settings
    application.dependency_overrides[get_storage] = lambda: storage
    with TestClient(application) as client:
        response = client.post(
            "/search",
            json={"query": "question"},
            headers={"Authorization": "Bearer override-key"},
        )
    assert response.status_code == 200
    assert search.call_args.kwargs["settings"] is settings
    assert search.call_args.kwargs["storage"] is storage


def test_api_rejects_non_ascii_credentials_without_server_error() -> None:
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        response = client.post(
            "/search",
            json={"query": "question"},
            headers={b"Authorization": "Bearer non-ascii-\u00e9".encode("utf-8")},
        )
    assert response.status_code == 401


def test_api_docs_are_public_and_operations_declare_bearer_auth() -> None:
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 200
    assert _OPENAPI["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    for method, path, operation in _PROTECTED_OPERATIONS:
        assert operation["security"] == [{"HTTPBearer": []}], (method, path)


def test_every_operation_has_consumer_facing_documentation() -> None:
    """Check documentation structure in Swagger, not its wording."""
    summaries = []
    for method, path, operation in _PROTECTED_OPERATIONS:
        description = operation.get("description", "")
        assert operation.get("summary", "").strip(), (method, path)
        assert "### Responses" in description, (method, path)
        # Google-style docstring sections are for developers, not API consumers.
        assert not re.search(
            r"^\s*(Args|Returns|Raises):", description, re.MULTILINE
        ), (method, path)
        summaries.append(operation["summary"])
    assert len(summaries) == len(set(summaries))


@pytest.mark.parametrize(
    "model,field",
    [
        ("SearchRequest", "limit"),
        ("SearchRequest", "method"),
        ("SearchRequest", "window"),
        ("AskRequest", "history"),
        ("SearchMatchResponse", "score"),
        ("CitationResponse", "source_reference"),
    ],
)
def test_fields_with_non_obvious_semantics_are_documented(model, field) -> None:
    properties = _OPENAPI["components"]["schemas"][model]["properties"]
    assert properties[field].get("description", "").strip()


def test_match_score_is_always_present_but_nullable() -> None:
    match_schema = _OPENAPI["components"]["schemas"]["SearchMatchResponse"]
    score_schema = match_schema["properties"]["score"]
    assert "score" in match_schema["required"]
    assert {option["type"] for option in score_schema["anyOf"]} == {"number", "null"}


@pytest.mark.parametrize(
    "target,error,status",
    [
        ("sources", None, 204),
        ("sources", SourceNotFound("Source not found"), 404),
        ("sources", SourceBusy("busy"), 409),
        ("conversations", None, 204),
        ("conversations", ConversationNotFound("Conversation not found"), 404),
        ("conversations", ConversationBusy("busy"), 409),
    ],
)
def test_delete_endpoints_map_storage_outcomes(
    monkeypatch, target, error, status
) -> None:
    delete = AsyncMock(side_effect=error)
    if target == "sources":
        monkeypatch.setattr("app.api.routers.sources.documents.delete_source", delete)
        monkeypatch.setattr(
            "app.api.routers.sources.cleanup_ingestion_inputs", AsyncMock()
        )
    else:
        monkeypatch.setattr(
            "app.api.routers.conversations.conversations.delete_conversation", delete
        )
    settings = Settings(api_key="test-key", tenant_id="server-tenant")
    resource_id = "00000000-0000-0000-0000-000000000001"
    with TestClient(create_app(settings)) as client:
        response = client.delete(
            f"/{target}/{resource_id}",
            headers={"Authorization": "Bearer test-key"},
        )
    assert response.status_code == status
    assert delete.call_args.args[1:] == ("server-tenant", UUID(resource_id))


def test_source_details_expose_metadata_without_content_hash(
    monkeypatch, api_client
) -> None:
    now = datetime.now(UTC)
    source = SourceSummary(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        tenant_id="server-tenant",
        source_type="file",
        reference="folder/report.pdf",
        mime_type="application/pdf",
        content_hash="private-hash",
        created_at=now,
        updated_at=now,
        chunk_count=3,
    )
    monkeypatch.setattr(
        "app.api.routers.sources.documents.list_sources",
        AsyncMock(return_value=[source]),
    )
    monkeypatch.setattr(
        "app.api.routers.sources.documents.get_source",
        AsyncMock(side_effect=[source, None]),
    )
    listed = api_client.get("/sources?limit=10&offset=5")
    found = api_client.get(f"/sources/{source.id}")
    missing = api_client.get(f"/sources/{source.id}")
    invalid = api_client.get("/sources?limit=0")
    assert listed.status_code == 200
    [item] = listed.json()
    assert item["title"] == "report.pdf"
    assert item["chunk_count"] == 3
    assert "content_hash" not in item and "tenant_id" not in item
    assert found.status_code == 200 and found.json() == item
    assert missing.status_code == 404
    assert invalid.status_code == 422


@pytest.mark.parametrize(
    "path", ["/demo/", "/demo/index.html", "/demo/app.js", "/demo/style.css"]
)
def test_backend_does_not_serve_demo(path, api_client) -> None:
    assert api_client.get(path).status_code == 404


def test_api_key_is_loaded_from_environment_but_not_displayed(monkeypatch) -> None:
    monkeypatch.setenv("RAG_API_KEY", "private-test-key")
    settings = Settings.from_environment()
    assert settings.api_key == "private-test-key"
    assert "private-test-key" not in repr(settings)


@pytest.mark.parametrize(
    "selection,provider,model,endpoint",
    [
        ({}, "openai", "configured-model", "https://configured.example/v1"),
        (
            {"generation_model": " another-model "},
            "openai",
            "another-model",
            "https://configured.example/v1",
        ),
        (
            {"generation_provider": "openai", "generation_model": "another-model"},
            "openai",
            "another-model",
            "https://configured.example/v1",
        ),
        (
            {"generation_provider": "deepseek", "generation_model": "deepseek-flash"},
            "deepseek",
            "deepseek-flash",
            None,
        ),
        (
            {"generation_provider": "ollama", "generation_model": "local-model"},
            "ollama",
            "local-model",
            None,
        ),
        (
            {"generation_provider": "anthropic", "generation_model": "available-model"},
            "anthropic",
            "available-model",
            None,
        ),
    ],
)
def test_answer_model_selection_is_request_scoped(
    monkeypatch, selection, provider, model, endpoint
) -> None:
    generate = AsyncMock(return_value=Answer("Answer", [], []))
    monkeypatch.setattr("app.api.services.answer", generate)
    settings = Settings(
        api_key="test-key",
        generation_model="configured-model",
        generation_base_url="https://configured.example/v1",
        tenant_id="server-tenant",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/ask",
            json={"query": "question", **selection},
            headers={"Authorization": "Bearer test-key"},
        )
    assert response.status_code == 200
    selected = generate.call_args.kwargs["settings"]
    assert (
        selected.generation_provider,
        selected.generation_model,
        selected.generation_base_url,
    ) == (provider, model, endpoint)
    assert selected.tenant_id == "server-tenant"
    assert settings.generation_model == "configured-model"
    assert settings.generation_provider == "openai"
    assert settings.generation_base_url == "https://configured.example/v1"


@pytest.mark.parametrize(
    "selection",
    [
        {"generation_provider": "unknown", "generation_model": "model"},
        {"generation_provider": "deepseek"},
        {"generation_model": ""},
        {"generation_model": "   "},
    ],
)
def test_invalid_answer_model_selection_does_not_call_provider(
    monkeypatch, api_client, selection
) -> None:
    generate = AsyncMock(side_effect=AssertionError("Generation must not execute"))
    monkeypatch.setattr("app.api.services.answer", generate)
    response = api_client.post("/ask", json={"query": "question", **selection})
    assert response.status_code == 422
    generate.assert_not_called()


def test_ask_forwards_caller_history_to_generation(monkeypatch, api_client) -> None:
    generate = AsyncMock(return_value=Answer("Answer", [], []))
    monkeypatch.setattr("app.api.services.answer", generate)
    history = [
        {"role": "user", "content": "When is the desk open?"},
        {"role": "assistant", "content": "Weekdays."},
    ]
    response = api_client.post(
        "/ask", json={"query": "And on weekends?", "history": history}
    )
    assert response.status_code == 200
    assert generate.call_args.args == ("And on weekends?",)
    forwarded = generate.call_args.kwargs["history"]
    assert [(message.role, message.content) for message in forwarded] == [
        ("user", "When is the desk open?"),
        ("assistant", "Weekdays."),
    ]


@pytest.mark.parametrize(
    "history",
    [
        [{"role": "user", "content": "Unanswered"}],
        [
            {"role": "assistant", "content": "Answer"},
            {"role": "user", "content": "Question"},
        ],
        [{"role": "system", "content": "Instruction"}],
        [
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": "Answer"},
        ],
        [
            {"role": "user", "content": "Question", "citations": []},
            {"role": "assistant", "content": "Answer"},
        ],
        [
            {"role": role, "content": "text"}
            for _ in range(11)
            for role in ("user", "assistant")
        ],
    ],
)
def test_invalid_ask_history_does_not_call_provider(
    monkeypatch, api_client, history
) -> None:
    generate = AsyncMock(side_effect=AssertionError("Generation must not execute"))
    monkeypatch.setattr("app.api.services.answer", generate)
    response = api_client.post("/ask", json={"query": "question", "history": history})
    assert response.status_code == 422
    generate.assert_not_called()


def test_conversation_turn_rejects_caller_history(monkeypatch, api_client) -> None:
    generate = AsyncMock(side_effect=AssertionError("Generation must not execute"))
    monkeypatch.setattr("app.api.services.answer", generate)
    response = api_client.post(
        f"/conversations/{_UUID}/messages",
        json={
            "query": "question",
            "history": [
                {"role": "user", "content": "Question"},
                {"role": "assistant", "content": "Answer"},
            ],
        },
    )
    assert response.status_code == 422
    generate.assert_not_called()
