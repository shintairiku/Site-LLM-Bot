from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from site_llm_bot.services.session_store import ChatMessage
from site_llm_bot.services.web_retrieval import (
    PageCandidate,
    RankedChunk,
    fetch_and_rank_context,
)

MAX_RELATED_LINKS = 3
MAX_SEARCH_SOURCE_LINKS = 12
MAX_RETRIEVAL_CONTEXT_CHARS = 12_000
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
        page_fetch_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._search_allowed_domains = search_allowed_domains or []
        self._timeout_seconds = timeout_seconds
        self._client = client
        self._page_fetch_client = page_fetch_client

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

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        normalized_history = history or []

        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await self._generate_with_client(
                    client=client,
                    headers=headers,
                    message=message,
                    page_url=page_url,
                    history=normalized_history,
                )

        return await self._generate_with_client(
            client=self._client,
            headers=headers,
            message=message,
            page_url=page_url,
            history=normalized_history,
        )

    async def _generate_with_client(
        self,
        *,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        message: str,
        page_url: str | None,
        history: list[ChatMessage],
    ) -> ChatGenerationResult:
        direct_payload = self._build_payload(message=message, page_url=page_url, history=history)
        if not self._should_use_augmented_retrieval():
            return await self._request_answer(client, headers, direct_payload)

        result = await self._request_answer_with_retrieval(
            client=client,
            headers=headers,
            message=message,
            page_url=page_url,
            history=history,
            fallback_payload=direct_payload,
        )
        return result

    def _should_use_augmented_retrieval(self) -> bool:
        if not self._search_allowed_domains:
            return False
        # テスト用などで OpenAI client だけが注入されている場合は、外部ページ取得を行わず従来経路にする。
        return self._client is None or self._page_fetch_client is not None

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

    def _build_search_payload(
        self,
        *,
        message: str,
        page_url: str | None,
        history: list[ChatMessage],
    ) -> dict[str, Any]:
        """URL 発見だけを目的に web_search を使う payload を組み立てる。"""
        user_text = message if not page_url else f"閲覧ページ: {page_url}\n質問: {message}"
        query_hints = "\n".join(f"- {query}" for query in self._build_search_query_hints(message))
        input_messages = self._build_base_messages(
            developer_instruction=(
                "あなたはサイト内検索のURL発見担当です。"
                " 最終回答は作らず、質問に答える根拠になりそうなページをWeb検索で探してください。"
                " 一覧ページ、詳細ページ、FAQ、会社情報などを必要に応じて複数検索してください。"
                " 次の検索クエリ候補を優先して使ってください。"
                f"\n{query_hints}"
                " 許可ドメイン外は使わないでください。"
                f" 許可ドメイン: {', '.join(self._search_allowed_domains)}"
            ),
            history=history,
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

    def _build_grounded_payload(
        self,
        *,
        message: str,
        page_url: str | None,
        history: list[ChatMessage],
        chunks: list[RankedChunk],
    ) -> dict[str, Any]:
        """取得済みチャンクだけを根拠に回答させる payload を組み立てる。"""
        developer_instruction = (
            "あなたは住宅・リフォーム業向けサイト用のAIチャットボットです。"
            " 丁寧な日本語で簡潔に回答してください。"
            " サイト内検索で取得した根拠抜粋だけを根拠にしてください。"
            " 根拠抜粋にない情報は推測せず、確認が必要だと伝えてください。"
            " Markdown記法の強調（**や__）は使わないでください。"
            " 回答本文にURL、参照元ドメイン名、括弧付きの出典表記、抜粋番号は含めないでください。"
            " 関連リンクはシステム側で追加するため、回答本文には含めないでください。"
        )
        input_messages = self._build_base_messages(
            developer_instruction=developer_instruction,
            history=history,
        )
        input_messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": self._build_grounded_user_text(
                            message=message,
                            page_url=page_url,
                            chunks=chunks,
                        ),
                    }
                ],
            }
        )
        return {
            "model": self._model,
            "input": input_messages,
        }

    def _build_base_messages(
        self,
        *,
        developer_instruction: str,
        history: list[ChatMessage],
    ) -> list[dict[str, Any]]:
        input_messages: list[dict[str, Any]] = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": developer_instruction}],
            }
        ]
        for item in history:
            input_messages.append(
                {
                    "role": item.role,
                    "content": [self._build_history_content(item.role, item.content)],
                }
            )
        return input_messages

    def _build_grounded_user_text(
        self,
        *,
        message: str,
        page_url: str | None,
        chunks: list[RankedChunk],
    ) -> str:
        context_blocks: list[str] = []
        total_chars = 0
        for index, chunk in enumerate(chunks, start=1):
            block = (
                f"[{index}] {chunk.title}\n"
                f"URL: {chunk.url}\n"
                f"本文抜粋:\n{chunk.text.strip()}"
            )
            if total_chars + len(block) > MAX_RETRIEVAL_CONTEXT_CHARS:
                break
            context_blocks.append(block)
            total_chars += len(block)

        user_text = message if not page_url else f"閲覧ページ: {page_url}\n質問: {message}"
        return (
            "サイト内検索で取得した根拠抜粋（許可ドメインのみ）:\n\n"
            + "\n\n---\n\n".join(context_blocks)
            + "\n\n質問:\n"
            + user_text
        )

    def _build_search_query_hints(self, message: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", message).strip()
        hints: list[str] = []
        for domain in self._search_allowed_domains:
            hints.append(f"site:{domain} {normalized}")
            if any(word in normalized for word in ("施工事例", "事例", "実績", "最新", "新着")):
                hints.append(f"site:{domain} 施工事例 最新")
                hints.append(f"site:{domain}/works 施工事例")
            if any(word in normalized for word in ("費用", "価格", "料金", "金額", "いくら")):
                hints.append(f"site:{domain} 費用 価格 料金")
            if any(word in normalized for word in ("エリア", "地域", "対応", "施工エリア")):
                hints.append(f"site:{domain} 施工エリア 対応エリア")
            if any(word in normalized for word in ("会社", "店舗", "住所", "所在地")):
                hints.append(f"site:{domain} 会社概要 店舗情報")

        deduped: list[str] = []
        seen: set[str] = set()
        for hint in hints:
            if hint in seen:
                continue
            deduped.append(hint)
            seen.add(hint)
        return deduped[:10]

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
        answer = self._extract_response_text(data)
        if answer:
            return ChatGenerationResult(
                answer=self._finalize_answer(answer, used_allowed_sources, related_links),
                used_allowed_sources=used_allowed_sources,
            )

        return ChatGenerationResult(
            answer=self._finalize_answer(
                "回答を生成できませんでした。",
                used_allowed_sources,
                related_links,
            ),
            used_allowed_sources=used_allowed_sources,
        )

    async def _request_answer_with_retrieval(
        self,
        *,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        message: str,
        page_url: str | None,
        history: list[ChatMessage],
        fallback_payload: dict[str, Any],
    ) -> ChatGenerationResult:
        """web_search の URL 候補を fetch + BM25 で絞り込んでから最終回答する。"""
        search_payload = self._build_search_payload(
            message=message,
            page_url=page_url,
            history=history,
        )
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=search_payload,
        )
        response.raise_for_status()
        search_data = response.json()
        inspection = self._inspect_response_sources(search_data)
        if inspection.has_disallowed_sources:
            return ChatGenerationResult(answer=SAFETY_MESSAGE, used_allowed_sources=False)

        candidates = self._build_retrieval_candidates(page_url, inspection.related_links)
        if not candidates:
            return await self._request_answer(client, headers, fallback_payload)

        fetch_client = self._page_fetch_client or client
        chunks = await fetch_and_rank_context(
            fetch_client,
            question=message,
            candidates=candidates,
            allowed_domains=self._search_allowed_domains,
        )
        if not chunks:
            return await self._request_answer(client, headers, fallback_payload)

        grounded_payload = self._build_grounded_payload(
            message=message,
            page_url=page_url,
            history=history,
            chunks=chunks,
        )
        return await self._request_grounded_answer(
            client=client,
            headers=headers,
            payload=grounded_payload,
            chunks=chunks,
        )

    async def _request_grounded_answer(
        self,
        *,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        payload: dict[str, Any],
        chunks: list[RankedChunk],
    ) -> ChatGenerationResult:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        answer = self._extract_response_text(data) or "回答を生成できませんでした。"
        related_links = self._related_links_from_chunks(chunks)
        return ChatGenerationResult(
            answer=self._finalize_answer(answer, True, related_links),
            used_allowed_sources=True,
        )

    def _extract_response_text(self, data: dict[str, Any]) -> str:
        answer = data.get("output_text")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()

        texts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    texts.append(text)
        return "\n".join(texts).strip()

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

    def _build_retrieval_candidates(
        self,
        page_url: str | None,
        related_links: list[RelatedLink],
    ) -> list[PageCandidate]:
        candidates: list[PageCandidate] = []
        allowed = [domain.lower() for domain in self._search_allowed_domains]
        if page_url:
            normalized = self._normalize_allowed_source_url(page_url, allowed)
            if normalized:
                candidates.append(PageCandidate(title="閲覧ページ", url=normalized))
        candidates.extend(
            PageCandidate(title=link.title, url=link.url)
            for link in related_links
        )
        return candidates

    def _related_links_from_chunks(self, chunks: list[RankedChunk]) -> list[RelatedLink]:
        links: list[RelatedLink] = []
        seen_urls: set[str] = set()
        for chunk in chunks:
            if chunk.url in seen_urls:
                continue
            links.append(
                RelatedLink(
                    title=self._normalize_link_title(chunk.title, chunk.url),
                    url=chunk.url,
                )
            )
            seen_urls.add(chunk.url)
            if len(links) >= MAX_RELATED_LINKS:
                break
        return links

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
            related_links=links[:MAX_SEARCH_SOURCE_LINKS],
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
