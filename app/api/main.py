"""FastAPI application setup and authentication."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.dependencies import authenticate
from app.api.router import api_router
from app.config import Settings, get_settings
from app.storage.database import Database


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Validate the API token before the application starts serving requests.

    Args:
        application: FastAPI application managed by the lifespan.

    Yields:
        None after successful token validation.

    Raises:
        ValueError: The configured token is missing, non-ASCII, or contains whitespace.
    """

    api_key = application.state.settings.api_key
    if (
        not api_key
        or not api_key.isascii()
        or any(character.isspace() for character in api_key)
    ):
        raise ValueError(
            "RAG_API_KEY must be set to a nonempty ASCII token without whitespace"
        )

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the authenticated FastAPI application with the configured database.

    Args:
        settings: Server configuration; reads the environment when omitted.

    Returns:
        Application with isolated settings, storage, and authenticated routers.
    """

    active_settings = settings if settings is not None else get_settings()
    application = FastAPI(
        title="rag-mtst",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
    )

    application.state.settings = active_settings
    application.state.storage = Database(active_settings.database_url)
    application.include_router(api_router)

    return application


app = create_app()
