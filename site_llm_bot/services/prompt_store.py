from __future__ import annotations

import logging

import httpx

_LOGGER = logging.getLogger("site_llm_bot.prompt_store")


class SupabasePromptStore:
    """Supabase の public.prompts テーブルから最新プロンプトを取得する。

    テナントごとに created_at 降順の先頭レコードを「現在のプロンプト」とみなす。
    取得に失敗した場合は None を返し、呼び出し元がデフォルト値にフォールバックする。
    """

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = f"{supabase_url.rstrip('/')}/rest/v1/prompts"
        self._service_role_key = service_role_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def fetch(self, tenant_id: str) -> str | None:
        """テナントの最新プロンプトを取得する。存在しない場合は None を返す。"""
        params = {
            "select": "content",
            "tenant_id": f"eq.{tenant_id}",
            "order": "created_at.desc",
            "limit": "1",
        }
        headers = self._build_headers()
        try:
            if self._client is not None:
                response = await self._client.get(self._url, headers=headers, params=params)
                response.raise_for_status()
                return _extract_content(response.json())

            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(self._url, headers=headers, params=params)
                response.raise_for_status()
                return _extract_content(response.json())
        except Exception:
            _LOGGER.warning("failed to fetch prompt for tenant %s", tenant_id, exc_info=True)
            return None

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "apikey": self._service_role_key,
            "Content-Type": "application/json",
        }
        if not self._service_role_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self._service_role_key}"
        return headers


def _extract_content(data: object) -> str | None:
    if isinstance(data, list) and data:
        content = data[0].get("content") if isinstance(data[0], dict) else None
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None
