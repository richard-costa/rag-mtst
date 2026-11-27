"""Application-scoped resources and HTTP authentication dependencies."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.collection import MAX_COLLECTION_ID_LENGTH, validate_collection_id
from app.config import Settings
from app.storage.database import Database


async def get_api_settings(request: Request) -> Settings:
    """Resolve the configuration owned by this application.

    Args:
        request: Incoming request identifying the application.

    Returns:
        Server configuration and defaults; it does not select a collection.
    """

    return request.app.state.settings


async def get_storage(request: Request) -> Database:
    """Resolve the database handle owned by this application.

    Args:
        request: Incoming request identifying the application.

    Returns:
        Application database handle; no connection is opened here.
    """

    return request.app.state.storage


async def get_collection_id(
    collection_id: Annotated[
        str,
        Path(
            min_length=1,
            max_length=MAX_COLLECTION_ID_LENGTH,
            description=(
                "Opaque, case-sensitive collection identifier. Selects data only; "
                "callers must authorize collection access before forwarding requests."
            ),
        ),
    ],
) -> str:
    """Validate the collection that scopes the request.

    Args:
        collection_id: Collection identifier from the request path.

    Returns:
        The unchanged collection identifier.

    Raises:
        HTTPException: A 422 response for an unusable identifier.
    """

    try:
        return validate_collection_id(collection_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


SettingsDependency = Annotated[Settings, Depends(get_api_settings)]
StorageDependency = Annotated[Database, Depends(get_storage)]
CollectionDependency = Annotated[str, Depends(get_collection_id)]


async def authenticate(
    settings: SettingsDependency,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> None:
    """Validate the shared bearer token using constant-time comparison.

    Args:
        settings: Configuration containing the server's API token.
        credentials: Parsed bearer credentials, or None when absent or malformed.

    Raises:
        HTTPException: A 401 response for missing or invalid credentials.
    """

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
