from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from demo.server import create_demo_app


@pytest.mark.parametrize("asset,content_type", [
    ("", "text/html"), ("app.js", "javascript"), ("style.css", "text/css"),
])
def test_local_demo_serves_only_public_assets(asset, content_type) -> None:
    with TestClient(create_demo_app(Settings(api_key="private-test-key"))) as client:
        response = client.get(f"/demo/{asset}")
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert "private-test-key" not in response.text
        for private_asset in ("server.py", "README.md", ".env"):
            assert client.get(f"/demo/{private_asset}").status_code == 404
        assert client.post("/ask", json={"query": "question"}).status_code == 401
