"""HTTP search request and response models."""

from pydantic import BaseModel, Field

from app.retrieval import RetrievalMethod, WindowAssembly


class SearchRequest(BaseModel):
    """Search parameters accepted by the HTTP API."""

    query: str = Field(min_length=1)
    limit: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Maximum matches for cosine, lexical, and hybrid methods. In window mode, "
            "counts seed matches before context expansion; the returned chunk count may exceed this limit. "
            "Null or omitted uses the server-configured limit."
        ),
    )
    method: RetrievalMethod | None = Field(
        default=None,
        description="Retrieval strategy. Null or omitted uses the server-configured method.",
    )
    window: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Number of neighboring chunks on each side of a seed; used only by the window method. "
            "Null or omitted uses the server-configured window."
        ),
    )
    assembly: WindowAssembly = Field(
        default="document",
        description="Window assembly: merged document order (default) or ranked seeds with context.",
    )


class SearchMatchResponse(BaseModel):
    """A retrieved passage and its similarity score."""

    source_id: str
    source_title: str
    chunk_index: int
    content: str
    score: float | None = Field(
        description=(
            "Method-specific ranking score for diagnostics, not a probability; "
            "scores are not comparable across methods. "
            "Null means the chunk was added as window context, not independently scored; "
            "it does not mean zero relevance."
        ),
    )
