from __future__ import annotations

from dataclasses import dataclass
import logging

import httpx

_LOGGER = logging.getLogger("site_llm_bot.rag_retriever")

_OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """類似度検索でヒットした登録ナレッジのチャンク。"""

    content: str
    similarity: float


class SupabaseRagRetriever:
    """質問文を embedding 化し、Supabase pgvector の類似度検索で関連チャンクを取得する。

    取り込み（プラットフォーム側）と同じ embedding モデルを使う必要がある。
    検索は public.match_data_chunks RPC を service_role で呼び出し、
    テナント越境しないよう match_tenant でフィルタする。
    取得失敗時は空リストを返し、呼び出し側は通常のweb検索のみで応答する。
    """

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        openai_api_key: str | None,
        embedding_model: str = "text-embedding-3-small",
        match_count: int = 5,
        min_similarity: float = 0.35,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._rpc_url = f"{supabase_url.rstrip('/')}/rest/v1/rpc/match_data_chunks"
        self._service_role_key = service_role_key
        self._openai_api_key = openai_api_key
        self._embedding_model = embedding_model
        self._match_count = match_count
        self._min_similarity = min_similarity
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def retrieve(self, tenant_id: str, query: str) -> list[RetrievedChunk]:
        """テナントの登録ナレッジから query に関連するチャンクを返す。"""
        if not self._openai_api_key:
            return []
        normalized_query = query.strip()
        if not normalized_query:
            return []

        try:
            if self._client is not None:
                return await self._retrieve_with(self._client, tenant_id, normalized_query)
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                return await self._retrieve_with(client, tenant_id, normalized_query)
        except Exception:
            _LOGGER.warning(
                "failed to retrieve knowledge chunks for tenant %s", tenant_id, exc_info=True
            )
            return []

    async def _retrieve_with(
        self, client: httpx.AsyncClient, tenant_id: str, query: str
    ) -> list[RetrievedChunk]:
        embedding = await self._embed(client, query)
        if embedding is None:
            return []
        rows = await self._match(client, tenant_id, embedding)
        chunks = [
            RetrievedChunk(content=row["content"], similarity=float(row.get("similarity", 0.0)))
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("content"), str)
        ]
        return [c for c in chunks if c.similarity >= self._min_similarity]

    async def _embed(self, client: httpx.AsyncClient, query: str) -> list[float] | None:
        response = await client.post(
            _OPENAI_EMBEDDINGS_URL,
            headers={
                "Authorization": f"Bearer {self._openai_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self._embedding_model, "input": query},
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("data")
        if isinstance(items, list) and items:
            embedding = items[0].get("embedding")
            if isinstance(embedding, list):
                return embedding
        return None

    async def _match(
        self, client: httpx.AsyncClient, tenant_id: str, embedding: list[float]
    ) -> list[dict]:
        response = await client.post(
            self._rpc_url,
            headers=self._build_headers(),
            json={
                "query_embedding": _to_vector_literal(embedding),
                "match_tenant": tenant_id,
                "match_count": self._match_count,
            },
        )
        response.raise_for_status()
        result = response.json()
        return result if isinstance(result, list) else []

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "apikey": self._service_role_key,
            "Content-Type": "application/json",
        }
        if not self._service_role_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self._service_role_key}"
        return headers


def _to_vector_literal(embedding: list[float]) -> str:
    """list[float] を pgvector のテキストリテラル '[0.1,0.2,...]' へ変換する。"""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"
