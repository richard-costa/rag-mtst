"""Application settings."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path


def _positive_integer(name: str, default: int) -> int:
    """Read and validate a positive integer environment setting.

    Args:
        name: Environment variable name.
        default: Fallback value when the environment variable is unset.

    Returns:
        Computed count or status code.
    """
    value = int(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration for storage, models, search, and local execution.
    """
    data_dir: Path = Path(".rag-data")
    database_url: str = "postgresql://rag:rag@127.0.0.1:5432/rag"
    tenant_id: str = "default"
    chunk_size: int = 180
    retrieval_limit: int = 10
    office_host: str = "127.0.0.1"
    office_port: int = 2003
    chunk_group_adjacent: bool = True
    embedding_provider: str = "openai"
    embedding_model: str | None = None
    openai_api_key: str | None = field(default=None, repr=False)
    openai_base_url: str | None = None
    retrieval_method: str = "window"
    retrieval_window: int = 2
    generation_provider: str = "openai"
    generation_model: str | None = None
    generation_base_url: str | None = None
    generation_input_tokens: int = 8000
    generation_max_tokens: int = 4000
    generation_timeout_seconds: int = 180
    visual_provider: str = "openai"
    visual_model: str | None = None
    visual_base_url: str | None = None
    deepseek_api_key: str | None = field(default=None, repr=False)
    anthropic_api_key: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)

    @property
    def source_dir(self) -> Path:
        """Return the directory used to stage uploaded source files.

        Returns:
            Result of the operation.
        """
        return self.data_dir / "sources"

    @property
    def embedding_model_name(self) -> str:
        """Resolve the effective model identifier for the embedding provider.

        Returns:
            Resolved text value.
        """
        if self.embedding_model:
            return self.embedding_model
        if self.embedding_provider == "local":
            return "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        return "text-embedding-3-small"

    @classmethod
    def from_environment(cls) -> "Settings":
        """Construct settings from environment variables and defaults.

        Returns:
            Validated runtime settings.
        """
        defaults = cls()
        return cls(
            data_dir=Path(os.getenv("RAG_DATA_DIR", str(defaults.data_dir))).expanduser(),
            database_url=os.getenv("DATABASE_URL", defaults.database_url),
            tenant_id=os.getenv("RAG_TENANT_ID", defaults.tenant_id),
            api_key=os.getenv("RAG_API_KEY"),
            office_host=os.getenv("RAG_OFFICE_HOST", defaults.office_host),
            office_port=_positive_integer("RAG_OFFICE_PORT", defaults.office_port),
            embedding_provider=os.getenv("RAG_EMBEDDING_PROVIDER", defaults.embedding_provider),
            embedding_model=os.getenv("RAG_EMBEDDING_MODEL"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
            generation_provider=os.getenv("RAG_GENERATION_PROVIDER", defaults.generation_provider),
            generation_model=os.getenv("RAG_GENERATION_MODEL") or None,
            generation_base_url=os.getenv("RAG_GENERATION_BASE_URL") or None,
            visual_provider=os.getenv("RAG_VISUAL_PROVIDER", defaults.visual_provider),
            visual_model=os.getenv("RAG_VISUAL_MODEL") or None,
            visual_base_url=os.getenv("RAG_VISUAL_BASE_URL") or None,
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        )


def get_settings() -> Settings:
    """Load runtime settings from the current environment.

    Returns:
        Settings loaded from the environment.
    """
    return Settings.from_environment()
