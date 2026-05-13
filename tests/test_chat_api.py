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
from site_llm_bot.config import Settings, TenantConfig, load_tenant_settings
from site_llm_bot.services.session_store import ChatMessage
from site_llm_bot.services.openai_handler import OpenAIChatHandler


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def build_settings(
    api_key: str | None = "test-key",
    widget_api_base: str = "",
) -> Settings:
    tenant1 = TenantConfig(
        tenant_id="sample-shintairiku",
        display_name="サンプル工務店",
        primary_color="#155e75",
        greeting="こんにちは。",
        suggested_questions=["施工エリアを教えてください"],
        allowed_domains=["shintairiku.jp"],
        allowed_origins=["https://tenant-one.example.com", "http://localhost:8000"],
        public_token="public_sample_shintairiku",
    )
    tenant2 = TenantConfig(
        tenant_id="tenant-two",
        display_name="サンプルリフォーム店",
        primary_color="#8a5a14",
        greeting="こんにちは。",
        suggested_questions=["会社について教えてください"],
        allowed_domains=["d.example.com", "e.example.com"],
        allowed_origins=["https://tenant-two.example.com"],
        allowed_origin_patterns=[r"https://tenant-two-[a-z0-9]+\.example\.com"],
        public_token="public_tenant_two",
    )
    return Settings(
        openai_api_key=api_key,
        openai_model="gpt-5.4-mini",
        app_host="127.0.0.1",
        app_port=8000,
        openai_timeout_seconds=30.0,
        session_ttl_seconds=1800,
        max_history_messages=6,
        tenant_config_path="config/tenants.json",
        widget_api_base=widget_api_base,
        default_tenant_id=tenant1.tenant_id,
        tenants={tenant1.tenant_id: tenant1, tenant2.tenant_id: tenant2},
    )


def widget_headers(
    tenant_id: str = "sample-shintairiku",
    token: str = "public_sample_shintairiku",
    origin: str = "https://tenant-one.example.com",
) -> dict[str, str]:
    return {
        "Origin": origin,
        "X-Tenant-Id": tenant_id,
        "X-Widget-Token": token,
    }


def test_default_tenant_uses_configured_allowed_domains() -> None:
    tenant_settings = load_tenant_settings("config/tenants.json")
    tenant = tenant_settings.tenants[tenant_settings.default_tenant_id]

    assert tenant.allowed_domains == ["shintairiku.jp"]
    assert tenant.public_token == "public_sample_shintairiku"


def test_demo_tenants_use_single_allowed_domain() -> None:
    tenant_settings = load_tenant_settings("config/tenants.json")

    assert tenant_settings.tenants["sample-shintairiku"].allowed_domains == ["shintairiku.jp"]
    assert tenant_settings.tenants["reform-tamao"].allowed_domains == ["reform-tamao.com"]
    assert tenant_settings.tenants["more-living"].allowed_domains == ["moreliving.co.jp"]
    for tenant in tenant_settings.tenants.values():
        assert "https://site-llm-bot-dev.vercel.app" in tenant.allowed_origins
        assert (
            "https://site-llm-bot-dev-742231208085.asia-northeast1.run.app"
            in tenant.allowed_origins
        )


def test_settings_reads_widget_api_base_from_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    tenant_config = tmp_path / "tenants.json"
    tenant_config.write_text(
        json.dumps(
            {
                "default_tenant_id": "sample-shintairiku",
                "tenants": [
                    {
                        "tenant_id": "sample-shintairiku",
                        "display_name": "新大陸",
                        "primary_color": "#155e75",
                        "greeting": "こんにちは。",
                        "suggested_questions": [],
                        "allowed_domains": ["shintairiku.jp"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TENANT_CONFIG_PATH", str(tenant_config))
    monkeypatch.setenv("WIDGET_API_BASE", "https://dev-backend.example.com/")

    settings = Settings.from_env()

    assert settings.widget_api_base == "https://dev-backend.example.com"


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
            json={
                "tenant_id": "sample-shintairiku",
                "message": "施工エリアを教えてください",
                "page_url": "http://localhost/demo",
            },
            headers=widget_headers(),
        )

    assert response.status_code == 200
    assert response.json()["source"] == "openai"
    assert "施工エリア" in response.json()["answer"]
    assert "関連リンク:" in response.json()["answer"]
    assert "【会社情報】" in response.json()["answer"]
    assert "https://shintairiku.jp/company/" in response.json()["answer"]
    assert response.json()["session_id"]
    await openai_client.aclose()


@pytest.mark.anyio
async def test_chat_api_switches_allowed_domains_by_tenant() -> None:
    seen_allowed_domains: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        seen_allowed_domains.append(payload["tools"][0]["filters"]["allowed_domains"])
        return httpx.Response(
            200,
            json={
                "output_text": "回答です。",
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {
                            "sources": [
                                {"url": "https://b.example.com/page"},
                                {"url": "https://d.example.com/page"},
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
        await client.post(
            "/api/chat",
            json={"tenant_id": "sample-shintairiku", "message": "質問1"},
            headers=widget_headers(),
        )
        await client.post(
            "/api/chat",
            json={"tenant_id": "tenant-two", "message": "質問2"},
            headers=widget_headers(
                tenant_id="tenant-two",
                token="public_tenant_two",
                origin="https://tenant-two.example.com",
            ),
        )

    assert seen_allowed_domains[0] == ["shintairiku.jp"]
    assert seen_allowed_domains[1] == ["d.example.com", "e.example.com"]
    await openai_client.aclose()


def test_openai_handler_formats_assistant_history_as_output_text() -> None:
    handler = OpenAIChatHandler(
        api_key="test-key",
        model="gpt-5.4-mini",
        search_allowed_domains=["shintairiku.jp"],
    )

    payload = handler._build_payload(
        message="次の質問です",
        page_url=None,
        history=[
            ChatMessage(role="user", content="最初の質問です"),
            ChatMessage(role="assistant", content="最初の回答です"),
        ],
    )

    assert payload["input"][1]["content"][0]["type"] == "input_text"
    assert payload["input"][2]["content"][0]["type"] == "output_text"


def test_openai_handler_sanitizes_markdown_and_source_links() -> None:
    handler = OpenAIChatHandler(
        api_key="test-key",
        model="gpt-5.4-mini",
        search_allowed_domains=["shintairiku.jp"],
    )

    answer = (
        "株式会社新大陸は、**SNS・ホームページ・Web広告**を組み合わせた支援会社です。 "
        "([shintairiku.jp](https://shintairiku.jp/company/?utm_source=openai))"
    )

    sanitized = handler._sanitize_answer(answer)

    assert "**" not in sanitized
    assert "https://shintairiku.jp" not in sanitized
    assert "shintairiku.jp" not in sanitized
    assert "SNS・ホームページ・Web広告" in sanitized


def test_openai_handler_appends_related_links_with_titles_from_citations() -> None:
    handler = OpenAIChatHandler(
        api_key="test-key",
        model="gpt-5.4-mini",
        search_allowed_domains=["shintairiku.jp"],
    )

    data = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "イベント情報をご案内します。",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "イベント情報 | サンプル工務店",
                                "url": "https://www.shintairiku.jp/event/#detail",
                            }
                        ],
                    }
                ],
            },
            {
                "type": "web_search_call",
                "action": {
                    "sources": [
                        {"title": "外部記事", "url": "https://example.com/article"},
                        {"title": "重複イベント", "url": "https://www.shintairiku.jp/event/"},
                    ]
                },
            }
        ],
    }

    related_links = handler._extract_allowed_source_links(data)
    answer = handler._finalize_answer("イベント情報をご案内します。", True, related_links)

    assert len(related_links) == 1
    assert related_links[0].title == "イベント情報"
    assert related_links[0].url == "https://www.shintairiku.jp/event/"
    assert answer.endswith("関連リンク:\n【イベント情報】\n- https://www.shintairiku.jp/event/")
    assert "https://example.com/article" not in answer


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
            json={"message": "会社の強みを教えてください"},
            headers=widget_headers(),
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
            json={"message": "相談の流れを知りたいです"},
            headers=widget_headers(),
        )

    assert response.status_code == 200
    assert response.json()["source"] == "demo"
    assert "デモモード" in response.json()["answer"]
    assert response.json()["session_id"]


@pytest.mark.anyio
async def test_v1_widget_config_returns_tenant_public_settings() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/v1/widget/config",
            headers=widget_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "sample-shintairiku",
        "display_name": "サンプル工務店",
        "primary_color": "#155e75",
        "greeting": "こんにちは。",
        "suggested_questions": ["施工エリアを教えてください"],
    }


@pytest.mark.anyio
async def test_v1_chat_session_returns_session_id_and_expiry() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/v1/chat/session",
            headers=widget_headers(),
        )

    assert response.status_code == 200
    assert response.json()["session_id"]
    assert response.json()["expires_in"] == 1800


@pytest.mark.anyio
async def test_v1_chat_message_with_mock_openai() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["tools"][0]["filters"]["allowed_domains"] == ["shintairiku.jp"]
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
        session_response = await client.post(
            "/v1/chat/session",
            headers=widget_headers(),
        )
        response = await client.post(
            "/v1/chat/message",
            headers=widget_headers(),
            json={
                "session_id": session_response.json()["session_id"],
                "message": "施工エリアを教えてください",
                "metadata": {"page_url": "https://tenant-one.example.com/reform"},
            },
        )

    assert response.status_code == 200
    assert response.json()["source"] == "openai"
    assert response.json()["session_id"] == session_response.json()["session_id"]
    assert "施工エリア" in response.json()["answer"]
    await openai_client.aclose()


@pytest.mark.anyio
async def test_v1_api_rejects_invalid_widget_token() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/v1/widget/config",
            headers=widget_headers(token="wrong-token"),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "invalid widget token"


@pytest.mark.anyio
async def test_chat_api_cors_rejects_unknown_origin() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/chat",
            headers={
                "Origin": "https://unknown.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-tenant-id,x-widget-token",
            },
        )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.anyio
async def test_chat_api_cors_allows_registered_origin() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.options(
            "/api/chat",
            headers={
                "Origin": "https://tenant-one.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-tenant-id,x-widget-token",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://tenant-one.example.com"


@pytest.mark.anyio
async def test_chat_api_rejects_invalid_widget_token() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"tenant_id": "sample-shintairiku", "message": "相談したいです"},
            headers=widget_headers(token="wrong-token"),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "invalid widget token"


@pytest.mark.anyio
async def test_chat_api_rejects_unregistered_origin() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"tenant_id": "sample-shintairiku", "message": "相談したいです"},
            headers=widget_headers(origin="https://unknown.example.com"),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "origin is not allowed"


@pytest.mark.anyio
async def test_chat_api_rejects_body_and_header_tenant_mismatch() -> None:
    app = create_app(settings=build_settings(api_key=None))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"tenant_id": "tenant-two", "message": "相談したいです"},
            headers=widget_headers(),
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "tenant mismatch"


@pytest.mark.anyio
async def test_chat_api_rejects_unknown_tenant() -> None:
    app = create_app(settings=build_settings())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/chat",
            json={"tenant_id": "unknown-tenant", "message": "相談したいです"},
            headers=widget_headers(tenant_id="unknown-tenant"),
        )

    assert response.status_code == 404


def test_demo_and_static_routes_exist() -> None:
    app = create_app(settings=build_settings(api_key=None))
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/demo" in paths
    assert "/static" in paths
    assert "/v1/widget/config" in paths
    assert "/v1/chat/session" in paths
    assert "/v1/chat/message" in paths


@pytest.mark.anyio
async def test_demo_page_injects_widget_api_base() -> None:
    app = create_app(
        settings=build_settings(
            api_key=None,
            widget_api_base="https://dev-backend.example.com",
        )
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/demo")

    assert response.status_code == 200
    assert 'src="/static/mock-widget.js"' in response.text
    assert 'data-api-base="https://dev-backend.example.com"' in response.text
    assert 'data-public-token="public_sample_shintairiku"' in response.text
    assert "site-llm-bot-742231208085.asia-northeast1.run.app/static/mock-widget.js" not in response.text
    assert "__WIDGET_API_BASE__" not in response.text
