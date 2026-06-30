from __future__ import annotations

from threading import Lock
from typing import Protocol

import httpx


class UniqueUserStore(Protocol):
    """匿名利用者の初回利用を判定・記録するストア。"""

    async def mark_seen(
        self,
        tenant_id: str,
        visitor_id: str,
        *,
        origin: str | None = None,
        page_url: str | None = None,
    ) -> bool:
        """初めて見る tenant_id + visitor_id なら True を返す。"""


class InMemoryUniqueUserStore:
    """プロセス内で初回利用 visitor_id を判定する簡易ストア。"""

    def __init__(self) -> None:
        self._seen_keys: set[tuple[str, str]] = set()
        self._lock = Lock()

    async def mark_seen(
        self,
        tenant_id: str,
        visitor_id: str,
        *,
        origin: str | None = None,
        page_url: str | None = None,
    ) -> bool:
        """初めて見る tenant_id + visitor_id なら True を返す。"""
        key = (tenant_id, visitor_id)
        with self._lock:
            if key in self._seen_keys:
                return False
            self._seen_keys.add(key)
            return True


class SupabaseUniqueUserStore:
    """Supabase RPC で匿名利用者の初回利用を記録するストア。"""

    def __init__(
        self,
        *,
        supabase_url: str,
        service_role_key: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._rpc_url = (
            f"{supabase_url.rstrip('/')}/rest/v1/rpc/record_unique_user"
        )
        self._service_role_key = service_role_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def mark_seen(
        self,
        tenant_id: str,
        visitor_id: str,
        *,
        origin: str | None = None,
        page_url: str | None = None,
    ) -> bool:
        """Supabaseに初回利用を記録し、新規挿入なら True を返す。"""
        payload = {
            "p_tenant_id": tenant_id,
            "p_visitor_id": visitor_id,
            "p_origin": origin,
            "p_page_url": page_url,
        }
        headers = {
            "apikey": self._service_role_key,
            "Content-Type": "application/json",
        }
        if not self._service_role_key.startswith("sb_secret_"):
            headers["Authorization"] = f"Bearer {self._service_role_key}"

        if self._client is not None:
            response = await self._client.post(
                self._rpc_url,
                headers=headers,
                json=payload,
            )
            return self._parse_response(response)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                self._rpc_url,
                headers=headers,
                json=payload,
            )
            return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> bool:
        response.raise_for_status()
        data = response.json()
        if isinstance(data, bool):
            return data
        raise ValueError("unexpected Supabase record_unique_user response")
