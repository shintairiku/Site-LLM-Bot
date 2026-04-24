from __future__ import annotations

from typing import Any

import httpx

from site_llm_bot.services.session_store import ChatMessage


class OpenAIChatHandler:
    """OpenAI Responses API を叩く最小ハンドラ。"""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def generate_answer(
        self,
        message: str,
        page_url: str | None = None,
        history: list[ChatMessage] | None = None,
    ) -> str:
        """ユーザー入力と履歴を OpenAI に渡し、最終テキストだけを返す。"""
        if not self._api_key:
            return (
                "現在はデモモードです。"
                f" 受信した質問: {message}"
                + (f" / 閲覧ページ: {page_url}" if page_url else "")
            )

        payload = self._build_payload(message=message, page_url=page_url, history=history or [])
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await self._request_answer(client, headers, payload)

        return await self._request_answer(self._client, headers, payload)

    def _build_payload(
        self,
        *,
        message: str,
        page_url: str | None,
        history: list[ChatMessage],
    ) -> dict[str, Any]:
        """Responses API へ渡す payload を組み立てる。"""
        user_text = message if not page_url else f"閲覧ページ: {page_url}\n質問: {message}"
        input_messages: list[dict[str, Any]] = [
            {
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "あなたは住宅・リフォーム業向けサイト用のAIチャットボットです。"
                            " 丁寧な日本語で簡潔に回答してください。"
                            " 不明なことは推測せず、確認が必要だと伝えてください。"
                        ),
                    }
                ],
            }
        ]

        for item in history:
            input_messages.append(
                {
                    "role": item.role,
                    "content": [{"type": "input_text", "text": item.content}],
                }
            )

        input_messages.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            }
        )

        return {
            "model": self._model,
            "input": input_messages,
        }

    async def _request_answer(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> str:
        """OpenAI 応答から output_text を抽出する。"""
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        answer = data.get("output_text")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()

        # output_text が無いケースでは output 配列の text をなめて結合する。
        texts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    texts.append(text)
        return "\n".join(texts).strip() or "回答を生成できませんでした。"
