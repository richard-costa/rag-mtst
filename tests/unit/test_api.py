from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_api_settings, get_storage
from app.api.main import create_app
from app.config import Settings
from app.generation import Answer
from app.storage.database import Database


@pytest.mark.parametrize(
    "api_key", [None, "", " ", "token with spaces", "non-ascii-\u00e9"]
)
def test_api_refuses_startup_without_a_valid_key(api_key) -> None:
    with (
        pytest.raises(ValueError, match="RAG_API_KEY"),
        TestClient(create_app(Settings(api_key=api_key))),
    ):
        pytest.fail("API startup must reject invalid authentication configuration")


@pytest.mark.parametrize("path", ["/sources/file", "/search", "/ask"])
@pytest.mark.parametrize(
    "authorization", [None, "Bearer wrong-key", "Basic test-key", "Bearer"]
)
def test_api_rejects_unauthenticated_requests_before_feature_calls(
    monkeypatch, path, authorization
) -> None:
    features = [
        AsyncMock(side_effect=AssertionError("Feature must not execute"))
        for _ in range(3)
    ]
    for path_to_feature, feature in zip(
        (
            "app.api.routers.sources.enqueue_bytes",
            "app.api.routers.search.search",
            "app.api.services.answer",
        ),
        features,
    ):
        monkeypatch.setattr(path_to_feature, feature)
    headers = {"Authorization": authorization} if authorization else {}
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        if path == "/sources/file":
            response = client.post(
                path, headers=headers, files={"file": ("test.md", b"Private text")}
            )
        else:
            response = client.post(path, headers=headers, json={"query": "question"})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"detail": "Invalid or missing API credentials"}
    for feature in features:
        feature.assert_not_called()


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


def test_api_schema_is_public_and_documents_bearer_authentication() -> None:
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200
        response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"] == {
        "type": "http",
        "scheme": "bearer",
    }
    for path in ("/sources/file", "/search", "/ask"):
        assert schema["paths"][path]["post"]["security"] == [{"HTTPBearer": []}]
    assert schema["paths"]["/jobs/{job_id}"]["get"]["security"] == [{"HTTPBearer": []}]


def test_api_schema_documents_search_semantics() -> None:
    schema = create_app(Settings(api_key="test-key")).openapi()
    models = schema["components"]["schemas"]
    for model_name in ("SearchRequest", "AskRequest", "ConversationTurnRequest"):
        properties = models[model_name]["properties"]
        assert (
            "counts seed matches before context expansion"
            in properties["limit"]["description"]
        )
        assert "server-configured method" in properties["method"]["description"]
        assert "used only by the window method" in properties["window"]["description"]

    match_schema = models["SearchMatchResponse"]
    score_schema = match_schema["properties"]["score"]
    assert "score" in match_schema["required"]
    assert {option["type"] for option in score_schema["anyOf"]} == {"number", "null"}
    assert "not comparable across methods" in score_schema["description"]
    assert "added as window context" in score_schema["description"]
    assert "not a probability" in score_schema["description"]

    citation_schema = models["CitationResponse"]
    assert "source_reference" in citation_schema["required"]
    assert "source_locator" not in citation_schema["properties"]
    assert (
        "Not necessarily unique or accessible"
        in citation_schema["properties"]["source_reference"]["description"]
    )

    search_schema = schema["paths"]["/search"]["post"]
    assert "groups are ranked by their best seed" in search_schema["description"]
    assert (
        "Chunks within each group follow document order" in search_schema["description"]
    )
    assert (
        "rather than sorting individual chunks by score" in search_schema["description"]
    )
    assert (
        search_schema["responses"]["200"]["content"]["application/json"]["schema"][
            "type"
        ]
        == "array"
    )


def test_job_status_requires_authentication_before_database_access(monkeypatch) -> None:
    lookup = AsyncMock(side_effect=AssertionError("Status lookup must not execute"))
    monkeypatch.setattr("app.api.routers.jobs.jobs.get_ingestion_job", lookup)
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        response = client.get("/jobs/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 401
    lookup.assert_not_called()


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/conversations"),
        ("GET", "/conversations/00000000-0000-0000-0000-000000000001/messages"),
        ("POST", "/conversations/00000000-0000-0000-0000-000000000001/messages"),
    ],
)
def test_conversations_require_authentication_before_database_access(
    monkeypatch, method, path
):
    def unexpected(*args, **kwargs):
        pytest.fail("Unauthenticated requests must not access conversations")

    for name in ("create_conversation", "list_messages", "conversation_turn"):
        monkeypatch.setattr(
            f"app.api.routers.conversations.conversations.{name}", unexpected
        )
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        response = client.request(method, path, json={"query": "question"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "path", ["/demo/", "/demo/index.html", "/demo/app.js", "/demo/style.css"]
)
def test_backend_does_not_serve_demo(path) -> None:
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        assert client.get(path).status_code == 404


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
    monkeypatch, selection
) -> None:
    generate = AsyncMock(side_effect=AssertionError("Generation must not execute"))
    monkeypatch.setattr("app.api.services.answer", generate)
    with TestClient(create_app(Settings(api_key="test-key"))) as client:
        response = client.post(
            "/ask",
            json={"query": "question", **selection},
            headers={"Authorization": "Bearer test-key"},
        )
    assert response.status_code == 422
    generate.assert_not_called()
