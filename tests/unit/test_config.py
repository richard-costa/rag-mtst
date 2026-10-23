from __future__ import annotations

import pytest

from app.config import Settings, get_settings


def test_environment_uses_settings_defaults(monkeypatch) -> None:
    monkeypatch.setattr("app.config.os.environ", {})

    assert get_settings() == Settings()


def test_generation_defaults_use_token_limits() -> None:
    settings = Settings()

    assert settings.generation_input_tokens == 8000
    assert settings.generation_max_tokens == 4000


def test_connection_settings_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("RAG_DATA_DIR", "~/sources")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example/rag")
    monkeypatch.setenv("RAG_TENANT_ID", "tenant-a")
    monkeypatch.setenv("RAG_OFFICE_HOST", "office")
    monkeypatch.setenv("RAG_OFFICE_PORT", "2004")

    settings = get_settings()

    assert settings.data_dir == tmp_path / "sources"
    assert settings.source_dir == tmp_path / "sources" / "sources"
    assert settings.database_url == "postgresql://example/rag"
    assert settings.tenant_id == "tenant-a"
    assert settings.office_host == "office"
    assert settings.office_port == 2004


@pytest.mark.parametrize("port", ["0", "-1", "invalid"])
def test_invalid_office_port_is_rejected(monkeypatch, port) -> None:
    monkeypatch.setenv("RAG_OFFICE_PORT", port)

    with pytest.raises(ValueError):
        get_settings()


def test_model_settings_are_independent_and_secrets_are_hidden(monkeypatch) -> None:
    environment = {
        "RAG_EMBEDDING_PROVIDER": "local",
        "RAG_EMBEDDING_MODEL": "embedding-model",
        "OPENAI_API_KEY": "openai-private-key",
        "OPENAI_BASE_URL": "https://embeddings.example/v1",
        "RAG_GENERATION_PROVIDER": "deepseek",
        "RAG_GENERATION_MODEL": "answer-model",
        "RAG_GENERATION_BASE_URL": "https://generation.example/v1",
        "DEEPSEEK_API_KEY": "deepseek-private-key",
        "RAG_VISUAL_PROVIDER": "anthropic",
        "RAG_VISUAL_MODEL": "vision-model",
        "RAG_VISUAL_BASE_URL": "https://visual.example/v1",
        "ANTHROPIC_API_KEY": "anthropic-private-key",
        "RAG_API_KEY": "api-private-key",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    settings = get_settings()

    assert settings.embedding_provider == "local"
    assert settings.embedding_model_name == "embedding-model"
    assert settings.openai_base_url == "https://embeddings.example/v1"
    assert settings.generation_provider == "deepseek"
    assert settings.generation_model == "answer-model"
    assert settings.generation_base_url == "https://generation.example/v1"
    assert settings.visual_provider == "anthropic"
    assert settings.visual_model == "vision-model"
    assert settings.visual_base_url == "https://visual.example/v1"
    for field_name, variable_name in (
        ("api_key", "RAG_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("deepseek_api_key", "DEEPSEEK_API_KEY"),
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
    ):
        secret = getattr(settings, field_name)
        assert secret == environment[variable_name]
        assert secret not in repr(settings)