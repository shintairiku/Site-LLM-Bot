from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from site_llm_bot.config import Settings
from site_llm_bot.services.openai_handler import OpenAIChatHandler
from site_llm_bot.services.session_store import InMemorySessionStore

BASE_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = BASE_DIR / "static"


class ChatRequest(BaseModel):
    """ウィジェットから受け取る最小入力。"""

    message: str = Field(..., min_length=1)
    page_url: str | None = None
    session_id: str | None = None


class ChatResponse(BaseModel):
    """ウィジェットへ返す最小出力。"""

    answer: str
    source: str
    session_id: str


def create_app(
    settings: Settings | None = None,
    openai_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """工程4向けの最小 FastAPI アプリを生成する。"""
    app_settings = settings or Settings.from_env()
    session_store = InMemorySessionStore(ttl_seconds=app_settings.session_ttl_seconds)
    chat_handler = OpenAIChatHandler(
        api_key=app_settings.openai_api_key,
        model=app_settings.openai_model,
        search_allowed_domains=app_settings.search_allowed_domains,
        timeout_seconds=app_settings.openai_timeout_seconds,
        client=openai_client,
    )

    app = FastAPI(title="Site LLM Bot API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(BASE_DIR / "demo" / "sample_page.html")

    @app.get("/demo")
    async def demo_page() -> FileResponse:
        return FileResponse(BASE_DIR / "demo" / "sample_page.html")

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(
        request: ChatRequest,
        origin: str | None = Header(default=None, alias="Origin"),
    ) -> ChatResponse:
        """ウィジェット -> API -> OpenAI の導線に、履歴と検証を追加した版。"""
        if origin and origin not in app_settings.allowed_origins:
            raise HTTPException(status_code=403, detail="origin not allowed")

        message = request.message.strip()
        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        session = session_store.get_or_create(request.session_id)
        history = session_store.history(
            session.session_id,
            limit=app_settings.max_history_messages,
        )
        session_store.append_message(session.session_id, "user", message)

        try:
            answer = await chat_handler.generate_answer(
                message=message,
                page_url=request.page_url,
                history=history,
            )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise HTTPException(status_code=502, detail=f"OpenAI API error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc

        session_store.append_message(session.session_id, "assistant", answer)
        source = "openai" if app_settings.openai_api_key else "demo"
        return ChatResponse(answer=answer, source=source, session_id=session.session_id)

    return app
