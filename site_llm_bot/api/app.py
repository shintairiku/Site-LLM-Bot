from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from site_llm_bot.config import Settings
from site_llm_bot.services.openai_handler import OpenAIChatHandler

BASE_DIR = Path(__file__).resolve().parents[2]


class ChatRequest(BaseModel):
    """ウィジェットから受け取る最小入力。"""

    message: str = Field(..., min_length=1)
    page_url: str | None = None


class ChatResponse(BaseModel):
    """ウィジェットへ返す最小出力。"""

    answer: str
    source: str


def create_app(
    settings: Settings | None = None,
    openai_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """工程3用の最小 FastAPI アプリを生成する。"""
    app_settings = settings or Settings.from_env()
    chat_handler = OpenAIChatHandler(
        api_key=app_settings.openai_api_key,
        model=app_settings.openai_model,
        client=openai_client,
    )

    app = FastAPI(title="Site LLM Bot API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/demo")
    async def demo_page() -> FileResponse:
        return FileResponse(BASE_DIR / "demo" / "sample_page.html")

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest) -> ChatResponse:
        """ウィジェット -> API -> OpenAI の最小導線。"""
        try:
            answer = await chat_handler.generate_answer(
                message=request.message.strip(),
                page_url=request.page_url,
            )
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise HTTPException(status_code=502, detail=f"OpenAI API error: {detail}") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc

        source = "openai" if app_settings.openai_api_key else "demo"
        return ChatResponse(answer=answer, source=source)

    return app
