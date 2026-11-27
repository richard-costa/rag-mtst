"""Central registration for the HTTP API's feature routers."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_collection_id
from app.api.routers import answers, conversations, jobs, search, sources

COLLECTION_PREFIX = "/collections/{collection_id}"

api_router = APIRouter()

# Every data route is collection-scoped; no route searches across collections.
for feature in (sources, jobs, search, answers, conversations):
    api_router.include_router(
        feature.router,
        prefix=COLLECTION_PREFIX,
        dependencies=[Depends(get_collection_id)],
    )
