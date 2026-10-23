"""HTTP application setup and authentication."""

from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.routes import create_router
from app.config import Settings, get_settings
from app.storage.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or get_settings()
    storage = Database(active_settings.database_url)
    configured_key = (active_settings.api_key or "").encode("utf-8")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        api_key = active_settings.api_key
        if not api_key or not api_key.isascii() or any(character.isspace() for character in api_key):
            raise ValueError("RAG_API_KEY must be set to a nonempty ASCII token without whitespace")
        yield

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
    ) -> None:
        if (
            credentials is None
            or not configured_key
            or not compare_digest(credentials.credentials.encode("utf-8"), configured_key)
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing API credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

    application = FastAPI(
        title="rag-mtst", version="0.1.0", lifespan=lifespan,
        dependencies=[Depends(authenticate)],
    )
    application.include_router(create_router(active_settings, storage))
    return application


app = create_app()
