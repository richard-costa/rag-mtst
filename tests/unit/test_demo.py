import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from demo.server import create_demo_app


@pytest.mark.parametrize(
    "asset,content_type",
    [
        ("", "text/html"),
        ("app.js", "javascript"),
        ("style.css", "text/css"),
    ],
)
def test_local_demo_serves_only_public_assets(asset, content_type) -> None:
    with TestClient(create_demo_app(Settings(api_key="private-test-key"))) as client:
        response = client.get(f"/demo/{asset}")
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert "private-test-key" not in response.text
        for private_asset in ("server.py", "README.md", ".env"):
            assert client.get(f"/demo/{private_asset}").status_code == 404
        assert client.post("/ask", json={"query": "question"}).status_code == 401


def test_demo_exposes_retrieval_comparison_controls() -> None:
    with TestClient(create_demo_app(Settings(api_key="private-test-key"))) as client:
        html = client.get("/demo/").text
        script = client.get("/demo/app.js").text
        for control in ("search-method", "search-limit", "search-window"):
            assert f'id="{control}"' in html
            assert f'element("{control}")' in script
        assert "payload.method = method" in script
        assert "payload.limit = Number(limit)" in script
        assert "payload.window = Number(windowSize)" in script
