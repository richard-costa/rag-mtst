"""Central registration for the HTTP API's feature routers."""

from fastapi import APIRouter

from app.api.routers import answers, conversations, jobs, search, sources

COLLECTION_PREFIX = "/collections/{collection_id}"

api_router = APIRouter()
api_router.include_router(sources.router, prefix=COLLECTION_PREFIX)
api_router.include_router(jobs.router, prefix=COLLECTION_PREFIX)
api_router.include_router(search.router, prefix=COLLECTION_PREFIX)
api_router.include_router(answers.router, prefix=COLLECTION_PREFIX)
api_router.include_router(conversations.router, prefix=COLLECTION_PREFIX)
