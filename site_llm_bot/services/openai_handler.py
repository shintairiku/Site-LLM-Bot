from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from site_llm_bot.services.session_store import ChatMessage

MAX_RELATED_LINKS = 3
SAFETY_MESSAGE = (
    "ご質問に関して、現在は対象サイト内で確認できた情報のみを案内する設定です。"
    " 許可ドメインから取得できる情報では確認できなかったため、正確な案内のためにお問い合わせください。"
)


@dataclass(frozen=True, slots=True)
class RelatedLink:
    """回答末尾に表示する関連リンク。"""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class SourceInspection:
    """web_search の実行状況と参照元ドメイン検証結果。"""

    used_web_search: bool
    related_links: list[RelatedLink]
    has_disallowed_sources: bool


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
            " 関連リンクはシステム側で追加するため、回答本文には含めないでください。"
            " 質問内容が簡単なものであってもweb searchによる徹底的な情報収集を行ってください。"
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
                    "search_context_size": "high",

                }
            ],
            "tool_choice": "required",
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
        inspection = self._inspect_response_sources(data)
        related_links = inspection.related_links
        used_allowed_sources = self._is_source_inspection_allowed(inspection)
        answer = data.get("output_text")
        if isinstance(answer, str) and answer.strip():
            return ChatGenerationResult(
                answer=self._finalize_answer(answer.strip(), used_allowed_sources, related_links),
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
            answer=self._finalize_answer(merged, used_allowed_sources, related_links),
            used_allowed_sources=used_allowed_sources,
        )

    # 参照元に許可ドメインが含まれない場合は、通常回答をそのまま返さず安全側へ倒す。
    def _finalize_answer(
        self,
        answer: str,
        used_allowed_sources: bool,
        related_links: list[RelatedLink] | None = None,
    ) -> str:
        if not self._search_allowed_domains:
            return self._sanitize_answer(answer)
        if used_allowed_sources:
            return self._append_related_links(self._sanitize_answer(answer), related_links or [])
        return SAFETY_MESSAGE

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

    def _append_related_links(self, answer: str, related_links: list[RelatedLink]) -> str:
        if not related_links:
            return answer

        body = re.sub(r"\n*関連リンク[:：]\s*$", "", answer).strip()
        links = "\n".join(
            f"【{link.title}】\n- {link.url}" for link in related_links[:MAX_RELATED_LINKS]
        )
        return f"{body}\n\n関連リンク:\n{links}"

    # OpenAIのweb_search結果に含まれる source URL から、許可ドメインのリンクだけを抽出する。
    def _extract_allowed_source_links(self, data: dict[str, Any]) -> list[RelatedLink]:
        return self._inspect_response_sources(data).related_links

    def _inspect_response_sources(self, data: dict[str, Any]) -> SourceInspection:
        allowed = [domain.lower() for domain in self._search_allowed_domains]
        links: list[RelatedLink] = []
        seen_urls: set[str] = set()
        has_disallowed_sources = False
        used_web_search = any(
            item.get("type") == "web_search_call" for item in data.get("output", [])
        )

        for candidate in self._iter_source_candidates(data):
            url = self._normalize_allowed_source_url(candidate.get("url", ""), allowed)
            if not url:
                if allowed:
                    has_disallowed_sources = True
                continue
            if url in seen_urls:
                continue

            title = self._normalize_link_title(candidate.get("title"), url)
            links.append(RelatedLink(title=title, url=url))
            seen_urls.add(url)
        return SourceInspection(
            used_web_search=used_web_search,
            related_links=links[:MAX_RELATED_LINKS],
            has_disallowed_sources=has_disallowed_sources,
        )

    def _is_source_inspection_allowed(self, inspection: SourceInspection) -> bool:
        if not self._search_allowed_domains:
            return True
        return (
            inspection.used_web_search
            and bool(inspection.related_links)
            and not inspection.has_disallowed_sources
        )

    def _iter_source_candidates(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []

        for item in data.get("output", []):
            for content in item.get("content", []):
                for annotation in content.get("annotations", []):
                    if annotation.get("type") == "url_citation":
                        candidates.append(annotation)

        for item in data.get("output", []):
            action = item.get("action") or {}
            candidates.extend(
                source
                for source in action.get("sources", [])
                if isinstance(source, dict)
            )

        return candidates

    def _normalize_allowed_source_url(self, url: Any, allowed_domains: list[str]) -> str | None:
        if not isinstance(url, str) or not url:
            return None

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None

        host = (parsed.hostname or "").lower()
        if not host:
            return None
        if allowed_domains and not any(
            host == domain or host.endswith(f".{domain}") for domain in allowed_domains
        ):
            return None

        return parsed._replace(fragment="").geturl()

    def _normalize_link_title(self, title: Any, url: str) -> str:
        if isinstance(title, str):
            normalized = title.strip()
            normalized = re.sub(r"\[(.*?)\]\((https?://.*?)\)", r"\1", normalized)
            normalized = re.sub(r"https?://[^\s)]+", "", normalized)
            normalized = re.sub(r"\s+", " ", normalized).strip(" -_|｜")
            if normalized:
                for separator in ("｜", "|", " - ", " – ", " — "):
                    if separator in normalized:
                        normalized = normalized.split(separator, 1)[0].strip()
                        break
                return normalized[:40]

        return self._fallback_link_title(url)

    def _fallback_link_title(self, url: str) -> str:
        parsed = urlparse(url)
        segments = [
            segment.removesuffix(".html").removesuffix(".htm").lower()
            for segment in parsed.path.strip("/").split("/")
            if segment
        ]

        segment_titles = {
            "blog": "ブログ",
            "case": "施工事例",
            "company": "会社情報",
            "contact": "お問い合わせ",
            "corporate": "コーポレート",
            "event": "イベント",
            "faq": "よくある質問",
            "news": "お知らせ",
            "pa-service": "内覧同行サービス",
            "reform": "リフォーム",
            "service": "サービス",
            "works": "施工事例",
        }

        for segment in segments:
            if segment in segment_titles:
                return segment_titles[segment]
        return "関連ページ"
