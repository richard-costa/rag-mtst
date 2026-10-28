"""Application-scoped resources and HTTP authentication dependencies."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings
from app.storage.database import Database


async def get_api_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_storage(request: Request) -> Database:
    return request.app.state.storage


SettingsDependency = Annotated[Settings, Depends(get_api_settings)]
StorageDependency = Annotated[Database, Depends(get_storage)]


async def authenticate(
    settings: SettingsDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> None:
    configured_key = (settings.api_key or "").encode("utf-8")
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
