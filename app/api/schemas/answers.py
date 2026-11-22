"""HTTP answer-generation request and response models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas.search import SearchMatchResponse, SearchRequest


class GenerationRequest(SearchRequest):
    """Search parameters and optional generation-provider overrides."""

    generation_provider: Literal["openai", "deepseek", "ollama", "anthropic"] | None = (
        None
    )
    generation_model: str | None = Field(default=None, min_length=1, pattern=r"\S")


class HistoryMessage(BaseModel):
    """A prior question or answer supplied by the caller."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, pattern=r"\S")


class AskRequest(GenerationRequest):
    """Stateless answer request with optional caller-supplied history."""

    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Prior turns, oldest first, as complete user/assistant pairs. "
            "Used only as untrusted generation context: retrieval searches only the query, "
            "and history is never cited or stored. Older turns are dropped when they exceed "
            "the history share of the prompt budget."
        ),
    )

    @field_validator("history")
    @classmethod
    def _require_complete_turns(
        cls, history: list[HistoryMessage]
    ) -> list[HistoryMessage]:
        """Reject history that is not ordered user/assistant pairs.

        Args:
            history: Caller-supplied prior messages.

        Returns:
            The unchanged history.
        """
        roles = [message.role for message in history]
        if roles != ["user", "assistant"] * (len(roles) // 2):
            raise ValueError("history must contain complete user/assistant turns")
        return history


class CitationResponse(BaseModel):
    """A numbered citation to a retrieved source passage."""

    id: int
    source_id: str
    source_title: str
    source_reference: str = Field(
        description=(
            "Descriptive reference to the source's origin, such as a filename, URL, or external record identifier. "
            "Not necessarily unique or accessible; not used to fetch the source. "
            "File ingestion currently stores the filename."
        ),
    )
    chunk_index: int
    content: str
    truncated: bool


class AskResponse(BaseModel):
    """Generated answer with supporting matches and citations."""

    answer: str
    matches: list[SearchMatchResponse]
    citations: list[CitationResponse]
