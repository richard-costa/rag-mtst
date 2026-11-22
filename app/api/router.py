"""Central registration for the HTTP API's feature routers."""

from fastapi import APIRouter

from app.api.routers import answers, conversations, jobs, search, sources

api_router = APIRouter()
api_router.include_router(sources.router)
api_router.include_router(jobs.router)
api_router.include_router(search.router)
api_router.include_router(answers.router)
api_router.include_router(conversations.router)
