from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from site_llm_bot.api.app import create_app
from site_llm_bot.config import Settings, TenantConfig


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_settings(api_key: str | None = "test-key") -> Settings:
    tenant = TenantConfig(
        tenant_id="sample-shintairiku",
        display_name="サンプル工務店",
        primary_color="#155e75",
        greeting="こんにちは。",
        suggested_questions=["施工エリアを教えてください"],
        allowed_origins=["http://localhost:8000"],
        allowed_origin_patterns=[r"https://site-llm-[a-z0-9]+-marketing-automation\.vercel\.app"],
        allowed_domains=["shintairiku.jp"],
    )
    return Settings(
        openai_api_key=api_key,
        openai_model="gpt-4o-mini",
        app_host="127.0.0.1",
        app_port=8000,
        openai_timeout_seconds=30.0,
        session_ttl_seconds=1800,
        max_history_messages=6,
        tenant_config_path="config/tenants.json",
        default_tenant_id=tenant.tenant_id,
        tenants={tenant.tenant_id: tenant},
        allowed_origins=["http://localhost:8000"],
        allowed_origin_regex=r"(?:https://site-llm-[a-z0-9]+-marketing-automation\.vercel\.app)",
    )


@pytest.mark.anyio
async def test_chat_api_with_mock_openai() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["tools"][0]["type"] == "web_search"
        assert payload["tools"][0]["filters"]["allowed_domains"] == ["shintairiku.jp"]
        assert payload["include"] == ["web_search_call.action.sources"]
        return httpx.Response(
            200,
            json={
                "output_text": "施工エリアは東京都内を中心に対応しています。",
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [
                                {
                                    "url": "https://shintairiku.jp/company/",
                                }
                            ]
                        },
                    }
                ],
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
                "tenant_id": "sample-shintairiku",
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
async def test_chat_api_returns_safe_message_when_allowed_domain_source_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output_text": "他社サイト由来の情報が混ざる可能性のある回答",
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [
                                {
                                    "url": "https://example.com/article",
                                }
                            ]
                        },
                    }
                ],
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
            json={"message": "会社の強みを教えてください"},
        )

    assert response.status_code == 200
    assert "対象サイト内で確認できた情報のみ" in response.json()["answer"]
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


@pytest.mark.anyio
async def test_chat_api_allows_origin_by_pattern() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "https://site-llm-foqkxam12-marketing-automation.vercel.app"},
            json={"message": "相談したいです"},
        )

    assert response.status_code == 200


@pytest.mark.anyio
async def test_chat_api_preflight_allows_origin_by_pattern() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/chat",
            headers={
                "Origin": "https://site-llm-foqkxam12-marketing-automation.vercel.app",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://site-llm-foqkxam12-marketing-automation.vercel.app"
    )


@pytest.mark.anyio
async def test_chat_api_rejects_unknown_tenant() -> None:
    app = create_app(settings=build_settings())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            headers={"Origin": "http://localhost:8000"},
            json={"tenant_id": "unknown-tenant", "message": "相談したいです"},
        )

    assert response.status_code == 404


def test_demo_and_static_routes_exist() -> None:
    app = create_app(settings=build_settings(api_key=None))
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/demo" in paths
    assert "/static" in paths
