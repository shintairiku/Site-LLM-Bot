from __future__ import annotations

from html import escape
import json
import logging
from pathlib import Path
import re
import time

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from site_llm_bot.config import Settings, TenantConfig
from site_llm_bot.services.openai_handler import OpenAIChatHandler
from site_llm_bot.services.session_store import InMemorySessionStore, TenantSessionMismatch

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "static"
ACCESS_LOGGER = logging.getLogger("site_llm_bot.access")
ACCESS_LOGGER.setLevel(logging.INFO)
if not ACCESS_LOGGER.handlers:
    access_log_handler = logging.StreamHandler()
    access_log_handler.setFormatter(logging.Formatter("%(message)s"))
    ACCESS_LOGGER.addHandler(access_log_handler)


class ChatRequest(BaseModel):
    """ウィジェットから受け取る最小入力。"""

    tenant_id: str | None = None
    message: str = Field(..., min_length=1)
    page_url: str | None = None
    session_id: str | None = None


class ChatResponse(BaseModel):
    """ウィジェットへ返す最小出力。"""

    answer: str
    source: str
    session_id: str


class WidgetConfigResponse(BaseModel):
    """ウィジェット初期化に必要な公開テキスト設定。"""

    tenant_id: str
    display_name: str
    greeting: str
    suggested_questions: list[str]


class ChatSessionResponse(BaseModel):
    """チャットセッション開始レスポンス。"""

    session_id: str
    expires_in: int


class ChatMessageMetadata(BaseModel):
    """チャット発話に付随するメタデータ。"""

    page_url: str | None = None


class ChatMessageRequest(BaseModel):
    """本番系チャットメッセージAPIの入力。"""

    session_id: str | None = None
    message: str = Field(..., min_length=1)
    metadata: ChatMessageMetadata = Field(default_factory=ChatMessageMetadata)


def create_app(
    settings: Settings | None = None,
    openai_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """工程4向けの最小 FastAPI アプリを生成する。"""
    app_settings = settings or Settings.from_env()
    session_store = InMemorySessionStore(ttl_seconds=app_settings.session_ttl_seconds)

    app = FastAPI(title="Site LLM Bot API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=collect_allowed_origins(app_settings),
        allow_origin_regex=build_allowed_origin_regex(app_settings),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Tenant-Id", "X-Widget-Token"],
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next):
        started_at = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            log_access(request=request, status_code=status_code, latency_ms=latency_ms)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> HTMLResponse:
        return render_demo_page(app_settings)

    @app.get("/demo")
    async def demo_page() -> HTMLResponse:
        return render_demo_page(app_settings)

    @app.get("/v1/widget/config", response_model=WidgetConfigResponse)
    async def widget_config(
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> WidgetConfigResponse:
        """ウィジェット表示に必要な公開設定を返す。"""
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=None,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=http_request.headers.get("origin"),
        )
        http_request.state.tenant_id = tenant.tenant_id
        return WidgetConfigResponse(
            tenant_id=tenant.tenant_id,
            display_name=tenant.display_name,
            greeting=tenant.greeting,
            suggested_questions=tenant.suggested_questions,
        )

    @app.post("/v1/chat/session", response_model=ChatSessionResponse)
    async def create_chat_session(
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> ChatSessionResponse:
        """新規チャットセッションを開始する。"""
        origin = http_request.headers.get("origin")
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=None,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=origin,
        )
        http_request.state.tenant_id = tenant.tenant_id
        session = session_store.get_or_create(
            None,
            tenant_id=tenant.tenant_id,
            origin=origin,
        )
        return ChatSessionResponse(
            session_id=session.session_id,
            expires_in=app_settings.session_ttl_seconds,
        )

    @app.post("/v1/chat/message", response_model=ChatResponse)
    async def chat_message(
        chat_request: ChatMessageRequest,
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> ChatResponse:
        """本番系のメッセージ送信API。検証済みの回答をJSONで返す。"""
        origin = http_request.headers.get("origin")
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=None,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=origin,
        )
        http_request.state.tenant_id = tenant.tenant_id
        return await generate_chat_response(
            settings=app_settings,
            session_store=session_store,
            tenant=tenant,
            openai_client=openai_client,
            session_id=chat_request.session_id,
            message=chat_request.message,
            page_url=chat_request.metadata.page_url,
            origin=origin,
        )

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(
        chat_request: ChatRequest,
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> ChatResponse:
        """ウィジェット -> API -> OpenAI の導線。tenant_id ごとに検索対象を切り替える。"""
        origin = http_request.headers.get("origin")
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=chat_request.tenant_id,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=origin,
        )
        http_request.state.tenant_id = tenant.tenant_id
        if not tenant.allowed_domains:
            raise HTTPException(status_code=403, detail="allowed domains not configured")

        return await generate_chat_response(
            settings=app_settings,
            session_store=session_store,
            tenant=tenant,
            openai_client=openai_client,
            session_id=chat_request.session_id,
            message=chat_request.message,
            page_url=chat_request.page_url,
            origin=origin,
        )

    return app


async def generate_chat_response(
    *,
    settings: Settings,
    session_store: InMemorySessionStore,
    tenant: TenantConfig,
    openai_client: httpx.AsyncClient | None,
    session_id: str | None,
    message: str,
    page_url: str | None,
    origin: str | None,
) -> ChatResponse:
    """認証済みテナントのチャット応答を生成する。"""
    if not tenant.allowed_domains:
        raise HTTPException(status_code=403, detail="allowed domains not configured")

    normalized_message = message.strip()
    if not normalized_message:
        raise HTTPException(status_code=400, detail="message is required")

    try:
        session = session_store.get_or_create(
            session_id,
            tenant_id=tenant.tenant_id,
            origin=origin,
        )
    except TenantSessionMismatch as exc:
        raise HTTPException(status_code=403, detail="session tenant mismatch") from exc

    history = session_store.history(
        session.session_id,
        limit=settings.max_history_messages,
    )
    session_store.append_message(session.session_id, "user", normalized_message)
    chat_handler = OpenAIChatHandler(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        search_allowed_domains=tenant.allowed_domains,
        timeout_seconds=settings.openai_timeout_seconds,
        client=openai_client,
    )

    try:
        result = await chat_handler.generate_answer(
            message=normalized_message,
            page_url=page_url,
            history=history,
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text if exc.response is not None else str(exc)
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {detail}") from exc
    except httpx.TimeoutException as exc:
        detail = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=504, detail=f"OpenAI request timed out: {detail}") from exc
    except httpx.HTTPError as exc:
        detail = str(exc) or exc.__class__.__name__
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {detail}") from exc

    session_store.append_message(session.session_id, "assistant", result.answer)
    source = "openai" if settings.openai_api_key else "demo"
    return ChatResponse(answer=result.answer, source=source, session_id=session.session_id)


def resolve_tenant(settings: Settings, tenant_id: str | None) -> TenantConfig:
    """リクエストに対応するテナント設定を返す。"""
    resolved_tenant_id = tenant_id or settings.default_tenant_id
    tenant = settings.tenants.get(resolved_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant


def authenticate_widget_request(
    *,
    settings: Settings,
    request_tenant_id: str | None,
    header_tenant_id: str | None,
    widget_token: str | None,
    origin: str | None,
) -> TenantConfig:
    """公開ウィジェットからの呼び出しをテナント設定で検証する。"""
    if request_tenant_id and header_tenant_id and request_tenant_id != header_tenant_id:
        raise HTTPException(status_code=403, detail="tenant mismatch")

    tenant = resolve_tenant(settings, header_tenant_id or request_tenant_id)
    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="tenant is inactive")
    if not tenant.public_token or widget_token != tenant.public_token:
        raise HTTPException(status_code=403, detail="invalid widget token")
    if not origin:
        raise HTTPException(status_code=403, detail="origin header is required")
    if not is_origin_allowed(tenant, origin):
        raise HTTPException(status_code=403, detail="origin is not allowed")
    return tenant


def extract_client_ip(request: Request) -> str:
    """プロキシ配下を想定し、転送ヘッダからクライアント IP を取得する。"""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",", 1)[0].strip()
        if client_ip:
            return client_ip

    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def log_access(*, request: Request, status_code: int, latency_ms: float) -> None:
    """運用監視で拾いやすい JSON 形式のアクセスログを出力する。"""
    tenant_id = getattr(request.state, "tenant_id", None) or request.headers.get("x-tenant-id")
    payload = {
        "tenant_id": tenant_id,
        "origin": request.headers.get("origin"),
        "ip": extract_client_ip(request),
        "path": request.url.path,
        "status_code": status_code,
        "latency_ms": latency_ms,
    }
    ACCESS_LOGGER.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def collect_allowed_origins(settings: Settings) -> list[str]:
    """CORS preflight 用に、全テナントの許可 Origin をまとめる。"""
    return sorted(
        {
            origin
            for tenant in settings.tenants.values()
            for origin in tenant.allowed_origins
        }
    )


def build_allowed_origin_regex(settings: Settings) -> str | None:
    """CORS middleware に渡す許可 Origin 正規表現を組み立てる。"""
    patterns = [
        pattern
        for tenant in settings.tenants.values()
        for pattern in tenant.allowed_origin_patterns
    ]
    if not patterns:
        return None
    return "|".join(f"(?:{pattern})" for pattern in sorted(set(patterns)))


def is_origin_allowed(tenant: TenantConfig, origin: str) -> bool:
    """テナントごとの登録 Origin とパターンで実リクエストを検証する。"""
    if origin in tenant.allowed_origins:
        return True
    return any(
        re.fullmatch(pattern, origin) is not None
        for pattern in tenant.allowed_origin_patterns
    )


def render_demo_page(settings: Settings) -> HTMLResponse:
    """環境ごとのバックエンド接続先を埋め込んだデモページを返す。"""
    html = (BASE_DIR / "demo" / "sample_page.html").read_text(encoding="utf-8")
    html = html.replace("__WIDGET_API_BASE__", escape(settings.widget_api_base, quote=True))
    return HTMLResponse(html)
