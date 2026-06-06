from __future__ import annotations

from threading import Lock


class InMemoryUniqueUserStore:
    """プロセス内で初回利用 visitor_id を判定する簡易ストア。"""

    def __init__(self) -> None:
        self._seen_keys: set[tuple[str, str]] = set()
        self._lock = Lock()

    def mark_seen(self, tenant_id: str, visitor_id: str) -> bool:
        """初めて見る tenant_id + visitor_id なら True を返す。"""
        key = (tenant_id, visitor_id)
        with self._lock:
            if key in self._seen_keys:
                return False
            self._seen_keys.add(key)
            return True
