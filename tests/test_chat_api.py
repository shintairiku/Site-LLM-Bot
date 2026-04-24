from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from site_llm_bot.api.app import create_app
from site_llm_bot.config import Settings


def build_settings(api_key: str | None = "test-key") -> Settings:
    return Settings(
        openai_api_key=api_key,
        openai_model="gpt-4o-mini",
        app_host="127.0.0.1",
        app_port=8000,
        openai_timeout_seconds=30.0,
        session_ttl_seconds=1800,
        max_history_messages=6,
        allowed_origins=["http://localhost:8000"],
    )


@pytest.mark.anyio
async def test_chat_api_with_mock_openai() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output_text": "施工エリアは東京都内を中心に対応しています。",
            },
        )

    openai_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app(settings=build_settings(), openai_client=openai_client)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "http://localhost:8000"},
            json={
                "message": "施工エリアを教えてください",
                "page_url": "http://localhost/demo",
            },
        )

    assert response.status_code == 200
    assert response.json()["source"] == "openai"
    assert "施工エリア" in response.json()["answer"]
    assert response.json()["session_id"]
    await openai_client.aclose()


@pytest.mark.anyio
async def test_chat_api_demo_fallback_without_api_key() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "http://localhost:8000"},
            json={"message": "相談の流れを知りたいです"},
        )

    assert response.status_code == 200
    assert response.json()["source"] == "demo"
    assert "デモモード" in response.json()["answer"]
    assert response.json()["session_id"]


@pytest.mark.anyio
async def test_chat_api_rejects_invalid_origin() -> None:
    app = create_app(settings=build_settings())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "http://invalid.example.com"},
            json={"message": "相談したいです"},
        )

    assert response.status_code == 403
