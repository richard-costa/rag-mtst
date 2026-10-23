"""Local demo entry point; not included in the backend distribution."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app.api.main import create_app
from app.config import Settings


def create_demo_app(settings: Settings | None = None) -> FastAPI:
    application = create_app(settings)
    frontend = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @frontend.get("/")
    @frontend.get("/{asset}")
    async def demo_asset(asset: str = "index.html") -> FileResponse:
        if asset not in {"index.html", "app.js", "style.css"}:
            raise HTTPException(status_code=404)
        return FileResponse(Path(__file__).with_name(asset))

    application.mount("/demo", frontend)
    return application


app = create_demo_app()