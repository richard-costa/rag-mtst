"""HTTP application setup and authentication."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from app.api.dependencies import authenticate
from app.api.routers import answers, conversations, jobs, search, sources
from app.config import Settings, get_settings
from app.storage.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the authenticated FastAPI application with the configured database.

    Args:
        settings: Server configuration; reads the environment when omitted.

    Returns:
        Application with isolated settings, storage, and authenticated routers.
    """
    active_settings = settings or get_settings()
    storage = Database(active_settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        """Validate the API token before the application starts serving requests.

        Args:
            application: FastAPI application managed by the lifespan.

        Yields:
            None after successful token validation.

        Raises:
            ValueError: The configured token is missing, non-ASCII, or contains whitespace.
        """
        api_key = active_settings.api_key
        if (
            not api_key
            or not api_key.isascii()
            or any(character.isspace() for character in api_key)
        ):
            raise ValueError(
                "RAG_API_KEY must be set to a nonempty ASCII token without whitespace"
            )
        yield

    application = FastAPI(
        title="rag-mtst",
        version="0.1.0",
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
    )
    application.state.settings = active_settings
    application.state.storage = storage
    application.include_router(sources.router)
    application.include_router(jobs.router)
    application.include_router(search.router)
    application.include_router(answers.router)
    application.include_router(conversations.router)
    return application


app = create_app()
