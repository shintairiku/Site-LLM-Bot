from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from site_llm_bot.services.session_store import ChatMessage


@dataclass(slots=True)
class ChatGenerationResult:
    """LLM応答と、その応答が許可ドメインで裏取りできたかをまとめて返す。"""

    answer: str
    used_allowed_sources: bool


class OpenAIChatHandler:
    """OpenAI Responses API を叩く最小ハンドラ。"""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        search_allowed_domains: list[str] | None = None,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._search_allowed_domains = search_allowed_domains or []
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def generate_answer(
        self,
        message: str,
        page_url: str | None = None,
        history: list[ChatMessage] | None = None,
    ) -> ChatGenerationResult:
        """ユーザー入力と履歴を OpenAI に渡し、裏取り状態付きで結果を返す。"""
        if not self._api_key:
            return ChatGenerationResult(
                answer=(
                    "現在はデモモードです。"
                    f" 受信した質問: {message}"
                    + (f" / 閲覧ページ: {page_url}" if page_url else "")
                ),
                used_allowed_sources=True,
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
                    "content": [self._build_history_content(item.role, item.content)],
                }
            )

        input_messages.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            }
        )

        developer_instruction = (
            "あなたは住宅・リフォーム業向けサイト用のAIチャットボットです。"
            " 丁寧な日本語で簡潔に回答してください。"
            " 不明なことは推測せず、確認が必要だと伝えてください。"
            " Markdown記法の強調（**や__）は使わないでください。"
            " 回答本文にURLや参照元ドメイン名、括弧付きの出典表記は含めないでください。"
        )
        if self._search_allowed_domains:
            developer_instruction += (
                " 回答前にWeb検索ツールで対象サイトを確認し、"
                f" 次のドメインのみを根拠にしてください: {', '.join(self._search_allowed_domains)}"
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "input": input_messages,
            "tools": [
                {
                    "type": "web_search",
                    "filters": {
                        "allowed_domains": self._search_allowed_domains,
                    },
                    "search_context_size": "medium",
                }
            ],
            "tool_choice": "auto",
            "include": ["web_search_call.action.sources"],
        }
        input_messages[0]["content"][0]["text"] = developer_instruction
        return payload

    def _build_history_content(self, role: str, content: str) -> dict[str, str]:
        """Responses API の role ごとの content 形式に合わせて履歴を整形する。"""
        if role == "assistant":
            return {"type": "output_text", "text": content}
        return {"type": "input_text", "text": content}

    async def _request_answer(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> ChatGenerationResult:
        """OpenAI 応答から本文と参照元ドメインを抽出し、安全側で結果を返す。"""
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        used_allowed_sources = self._has_allowed_domain_sources(data)
        answer = data.get("output_text")
        if isinstance(answer, str) and answer.strip():
            return ChatGenerationResult(
                answer=self._finalize_answer(answer.strip(), used_allowed_sources),
                used_allowed_sources=used_allowed_sources,
            )

        # output_text が無いケースでは output 配列の text をなめて結合する。
        texts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    texts.append(text)
        merged = "\n".join(texts).strip() or "回答を生成できませんでした。"
        return ChatGenerationResult(
            answer=self._finalize_answer(merged, used_allowed_sources),
            used_allowed_sources=used_allowed_sources,
        )

    # 参照元に許可ドメインが含まれない場合は、通常回答をそのまま返さず安全側へ倒す。
    def _finalize_answer(self, answer: str, used_allowed_sources: bool) -> str:
        if not self._search_allowed_domains:
            return self._sanitize_answer(answer)
        if used_allowed_sources:
            return self._sanitize_answer(answer)
        return (
            "ご質問に関して、現在は対象サイト内で確認できた情報のみを案内する設定です。"
            " この内容はサイト内で裏取りできなかったため、正確な案内のためにお問い合わせください。"
        )

    # UI側で読みやすいよう、Markdown強調やURL・出典表記を落としてプレーンテキストへ寄せる。
    def _sanitize_answer(self, answer: str) -> str:
        sanitized = answer
        sanitized = re.sub(r"\*\*(.*?)\*\*", r"\1", sanitized)
        sanitized = re.sub(r"__(.*?)__", r"\1", sanitized)
        sanitized = re.sub(r"\[(.*?)\]\((https?://.*?)\)", r"\1", sanitized)
        sanitized = re.sub(r"\(?https?://[^\s)]+\)?", "", sanitized)
        sanitized = re.sub(r"\(\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\)]*\)", "", sanitized)
        sanitized = re.sub(r"[ \t]+", " ", sanitized)
        sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
        return sanitized.strip()

    # OpenAIのweb_search結果に含まれる source URL を見て、許可ドメインの情報が使われたか判定する。
    def _has_allowed_domain_sources(self, data: dict[str, Any]) -> bool:
        allowed = [domain.lower() for domain in self._search_allowed_domains]
        if not allowed:
            return True

        for item in data.get("output", []):
            action = item.get("action") or {}
            for source in action.get("sources", []):
                url = source.get("url", "")
                host = urlparse(url).netloc.lower()
                if any(host == domain or host.endswith(f".{domain}") for domain in allowed):
                    return True
        return False
