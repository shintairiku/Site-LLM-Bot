from __future__ import annotations

from datetime import UTC, datetime
from html import escape
import json
import logging
from pathlib import Path
import re
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from site_llm_bot.config import Settings, TenantConfig
from site_llm_bot.services.analytics_store import (
    AnalyticsStore,
    ChatMessageSentStore,
    ChatMessageSentEvent,
    LoggingAnalyticsStore,
    RelatedLinkClickEvent,
    RelatedLinkClickStore,
    SessionFeedbackEvent,
    SessionFeedbackStore,
    SupabaseChatMessageSentStore,
    SupabaseRelatedLinkClickStore,
    SupabaseSessionFeedbackStore,
    UserFirstSeenEvent,
    mask_pii,
)
from site_llm_bot.services.openai_handler import OpenAIChatHandler
from site_llm_bot.services.prompt_store import SupabasePromptStore
from site_llm_bot.services.session_store import InMemorySessionStore, TenantSessionMismatch
from site_llm_bot.services.unique_user_store import (
    InMemoryUniqueUserStore,
    SupabaseUniqueUserStore,
    UniqueUserStore,
)

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
    visitor_id: str | None = None


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
    visitor_id: str | None = None


class ChatMessageRequest(BaseModel):
    """本番系チャットメッセージAPIの入力。"""

    session_id: str | None = None
    message: str = Field(..., min_length=1)
    metadata: ChatMessageMetadata = Field(default_factory=ChatMessageMetadata)


class RelatedLinkClickMetadata(BaseModel):
    """関連リンククリックに付随するメタデータ。"""

    page_url: str | None = None
    visitor_id: str | None = None
    session_id: str | None = None


class RelatedLinkClickRequest(BaseModel):
    """関連リンククリック記録APIの入力。"""

    link_url: str = Field(..., min_length=1, max_length=2048)
    metadata: RelatedLinkClickMetadata = Field(
        default_factory=RelatedLinkClickMetadata
    )


class SessionFeedbackMetadata(BaseModel):
    """セッションフィードバックに付随するメタデータ。"""

    page_url: str | None = None
    visitor_id: str | None = None
    session_id: str | None = None


class SessionFeedbackRequest(BaseModel):
    """セッションフィードバック記録APIの入力。"""

    resolved: bool
    metadata: SessionFeedbackMetadata = Field(default_factory=SessionFeedbackMetadata)


def create_app(
    settings: Settings | None = None,
    openai_client: httpx.AsyncClient | None = None,
    analytics_store: AnalyticsStore | None = None,
    chat_message_sent_store: ChatMessageSentStore | None = None,
    related_link_click_store: RelatedLinkClickStore | None = None,
    session_feedback_store: SessionFeedbackStore | None = None,
    unique_user_store: UniqueUserStore | None = None,
    prompt_store: SupabasePromptStore | None = None,
) -> FastAPI:
    """工程4向けの最小 FastAPI アプリを生成する。"""
    app_settings = settings or Settings.from_env()
    session_store = InMemorySessionStore(ttl_seconds=app_settings.session_ttl_seconds)
    chat_message_sent_store = (
        chat_message_sent_store or create_chat_message_sent_store(app_settings)
    )
    related_link_click_store = (
        related_link_click_store or create_related_link_click_store(app_settings)
    )
    session_feedback_store = (
        session_feedback_store or create_session_feedback_store(app_settings)
    )
    unique_user_store = unique_user_store or create_unique_user_store(app_settings)
    prompt_store = prompt_store or create_prompt_store(app_settings)
    if analytics_store is None and app_settings.analytics_enabled:
        analytics_store = LoggingAnalyticsStore()

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
            analytics_store=analytics_store,
            chat_message_sent_store=chat_message_sent_store,
            unique_user_store=unique_user_store,
            prompt_store=prompt_store,
            session_id=chat_request.session_id,
            message=chat_request.message,
            page_url=chat_request.metadata.page_url,
            visitor_id=chat_request.metadata.visitor_id,
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
            analytics_store=analytics_store,
            chat_message_sent_store=chat_message_sent_store,
            unique_user_store=unique_user_store,
            prompt_store=prompt_store,
            session_id=chat_request.session_id,
            message=chat_request.message,
            page_url=chat_request.page_url,
            visitor_id=chat_request.visitor_id,
            origin=origin,
        )

    @app.post("/v1/analytics/related-link-click", status_code=204)
    async def related_link_click(
        click_request: RelatedLinkClickRequest,
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> Response:
        """関連リンククリックを記録する。"""
        origin = http_request.headers.get("origin")
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=None,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=origin,
        )
        http_request.state.tenant_id = tenant.tenant_id
        link_url = normalize_related_link_url(
            click_request.link_url,
            allowed_domains=tenant.allowed_domains,
        )
        if link_url is None:
            raise HTTPException(status_code=403, detail="link url is not allowed")

        await record_related_link_click(
            related_link_click_store=related_link_click_store,
            event=RelatedLinkClickEvent(
                tenant_id=tenant.tenant_id,
                link_url=link_url,
                visitor_id=normalize_visitor_id(click_request.metadata.visitor_id),
                session_id=normalize_session_id(click_request.metadata.session_id),
                origin=origin,
                page_url=click_request.metadata.page_url,
                clicked_at=datetime.now(UTC),
            ),
        )
        return Response(status_code=204)

    @app.post("/v1/analytics/session-feedback", status_code=204)
    async def session_feedback(
        feedback_request: SessionFeedbackRequest,
        http_request: Request,
        x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
        x_widget_token: str | None = Header(default=None, alias="X-Widget-Token"),
    ) -> Response:
        """セッションフィードバック（解決/未解決）を記録する。"""
        origin = http_request.headers.get("origin")
        tenant = authenticate_widget_request(
            settings=app_settings,
            request_tenant_id=None,
            header_tenant_id=x_tenant_id,
            widget_token=x_widget_token,
            origin=origin,
        )
        http_request.state.tenant_id = tenant.tenant_id
        session_id = normalize_session_id(feedback_request.metadata.session_id)
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")

        await record_session_feedback(
            session_feedback_store=session_feedback_store,
            event=SessionFeedbackEvent(
                tenant_id=tenant.tenant_id,
                session_id=session_id,
                resolved=feedback_request.resolved,
                visitor_id=normalize_visitor_id(feedback_request.metadata.visitor_id),
                origin=origin,
                page_url=feedback_request.metadata.page_url,
                occurred_at=datetime.now(UTC),
            ),
        )
        return Response(status_code=204)

    return app


async def generate_chat_response(
    *,
    settings: Settings,
    session_store: InMemorySessionStore,
    tenant: TenantConfig,
    openai_client: httpx.AsyncClient | None,
    analytics_store: AnalyticsStore | None,
    chat_message_sent_store: ChatMessageSentStore | None,
    unique_user_store: UniqueUserStore,
    prompt_store: SupabasePromptStore | None,
    session_id: str | None,
    message: str,
    page_url: str | None,
    visitor_id: str | None,
    origin: str | None,
) -> ChatResponse:
    """認証済みテナントのチャット応答を生成する。"""
    if not tenant.allowed_domains:
        raise HTTPException(status_code=403, detail="allowed domains not configured")

    normalized_message = message.strip()
    if not normalized_message:
        raise HTTPException(status_code=400, detail="message is required")
    normalized_visitor_id = normalize_visitor_id(visitor_id)

    try:
        session = session_store.get_or_create(
            session_id,
            tenant_id=tenant.tenant_id,
            origin=origin,
        )
    except TenantSessionMismatch as exc:
        raise HTTPException(status_code=403, detail="session tenant mismatch") from exc

    occurred_at = datetime.now(UTC)
    is_user_first_seen = await mark_unique_user_seen(
        unique_user_store=unique_user_store,
        tenant_id=tenant.tenant_id,
        visitor_id=normalized_visitor_id,
        origin=origin,
        page_url=page_url,
    )

    chat_message_sent_event = ChatMessageSentEvent(
        tenant_id=tenant.tenant_id,
        session_id=session.session_id,
        origin=origin,
        page_url=page_url,
        occurred_at=occurred_at,
        visitor_id=normalized_visitor_id,
        question_text=mask_pii(normalized_message),
    )
    await record_chat_message_sent(
        chat_message_sent_store=chat_message_sent_store,
        event=chat_message_sent_event,
    )

    if analytics_store is not None:
        analytics_store.record_chat_message_sent(chat_message_sent_event)
        if is_user_first_seen and normalized_visitor_id:
            analytics_store.record_user_first_seen(
                UserFirstSeenEvent(
                    tenant_id=tenant.tenant_id,
                    visitor_id=normalized_visitor_id,
                    origin=origin,
                    page_url=page_url,
                    occurred_at=occurred_at,
                )
            )

    history = session_store.history(
        session.session_id,
        limit=settings.max_history_messages,
    )
    session_store.append_message(session.session_id, "user", normalized_message)

    system_prompt: str | None = None
    if prompt_store is not None:
        system_prompt = await prompt_store.fetch(tenant.tenant_id)

    chat_handler = OpenAIChatHandler(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        search_allowed_domains=tenant.allowed_domains,
        system_prompt=system_prompt,
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


def create_chat_message_sent_store(settings: Settings) -> ChatMessageSentStore | None:
    """Supabase設定があればチャット送信イベントをDBへ記録する。"""
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseChatMessageSentStore(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return None


def create_session_feedback_store(settings: Settings) -> SessionFeedbackStore | None:
    """Supabase設定があればセッションフィードバックイベントをDBへ記録する。"""
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseSessionFeedbackStore(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return None


def create_related_link_click_store(settings: Settings) -> RelatedLinkClickStore | None:
    """Supabase設定があれば関連リンククリックイベントをDBへ記録する。"""
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseRelatedLinkClickStore(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return None


def create_prompt_store(settings: Settings) -> SupabasePromptStore | None:
    """Supabase設定があればプロンプトをDBから取得する。"""
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabasePromptStore(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return None


def create_unique_user_store(settings: Settings) -> UniqueUserStore:
    """Supabase設定があればDB連携、なければプロセス内判定を使う。"""
    if settings.supabase_url and settings.supabase_service_role_key:
        return SupabaseUniqueUserStore(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            timeout_seconds=settings.supabase_timeout_seconds,
        )
    return InMemoryUniqueUserStore()


async def record_chat_message_sent(
    *,
    chat_message_sent_store: ChatMessageSentStore | None,
    event: ChatMessageSentEvent,
) -> None:
    """チャット送信イベントをDBへ記録する。失敗してもチャット処理は止めない。"""
    if chat_message_sent_store is None:
        return
    try:
        await chat_message_sent_store.record(event)
    except Exception:
        logging.getLogger("site_llm_bot.analytics").exception(
            "failed to record chat message sent"
        )


async def record_session_feedback(
    *,
    session_feedback_store: SessionFeedbackStore | None,
    event: SessionFeedbackEvent,
) -> None:
    """セッションフィードバックイベントをDBへ記録する。失敗してもフィードバック導線は止めない。"""
    if session_feedback_store is None:
        return
    try:
        await session_feedback_store.record(event)
    except Exception:
        logging.getLogger("site_llm_bot.analytics").exception(
            "failed to record session feedback"
        )


async def record_related_link_click(
    *,
    related_link_click_store: RelatedLinkClickStore | None,
    event: RelatedLinkClickEvent,
) -> None:
    """関連リンククリックイベントをDBへ記録する。失敗してもクリック導線は止めない。"""
    if related_link_click_store is None:
        return
    try:
        await related_link_click_store.record(event)
    except Exception:
        logging.getLogger("site_llm_bot.analytics").exception(
            "failed to record related link click"
        )


async def mark_unique_user_seen(
    *,
    unique_user_store: UniqueUserStore,
    tenant_id: str,
    visitor_id: str | None,
    origin: str | None,
    page_url: str | None,
) -> bool:
    """匿名利用者の初回利用を記録する。失敗してもチャット処理は止めない。"""
    if not visitor_id:
        return False
    try:
        return await unique_user_store.mark_seen(
            tenant_id,
            visitor_id,
            origin=origin,
            page_url=page_url,
        )
    except Exception:
        logging.getLogger("site_llm_bot.analytics").exception(
            "failed to record unique user"
        )
        return False


def resolve_tenant(settings: Settings, tenant_id: str | None) -> TenantConfig:
    """リクエストに対応するテナント設定を返す。"""
    resolved_tenant_id = tenant_id or settings.default_tenant_id
    tenant = settings.tenants.get(resolved_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant


def normalize_visitor_id(visitor_id: str | None) -> str | None:
    """ウィジェットが発行した匿名 visitor_id をログ保存用に正規化する。"""
    if visitor_id is None:
        return None
    normalized = visitor_id.strip()
    if not normalized or len(normalized) > 128:
        return None
    if re.fullmatch(r"[A-Za-z0-9._:-]+", normalized) is None:
        return None
    return normalized


def normalize_session_id(session_id: str | None) -> str | None:
    """セッションIDをログ保存用に正規化する。"""
    if session_id is None:
        return None
    normalized = session_id.strip()
    if not normalized or len(normalized) > 128:
        return None
    if re.fullmatch(r"[A-Za-z0-9._:-]+", normalized) is None:
        return None
    return normalized


def normalize_related_link_url(
    link_url: str,
    *,
    allowed_domains: list[str],
) -> str | None:
    """関連リンクURLを集計用に正規化し、テナントの許可ドメイン内に制限する。"""
    normalized = link_url.strip()
    if not normalized or len(normalized) > 2048:
        return None

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    host = (parsed.hostname or "").lower()
    allowed = [domain.lower() for domain in allowed_domains]
    if not host or not any(
        host == domain or host.endswith(f".{domain}") for domain in allowed
    ):
        return None

    return parsed._replace(fragment="").geturl()


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
