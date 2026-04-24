from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4


@dataclass(slots=True)
class ChatMessage:
    """1件分の会話メッセージ。"""

    role: str
    content: str


@dataclass(slots=True)
class ChatSession:
    """オンメモリで持つ会話セッション。"""

    session_id: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatMessage] = field(default_factory=list)


class InMemorySessionStore:
    """工程4向けの最小オンメモリセッション管理。"""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._sessions: dict[str, ChatSession] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str | None) -> ChatSession:
        """既存セッションを返すか、新規セッションを作る。"""
        now = datetime.now(UTC)
        with self._lock:
            self._cleanup_locked(now)
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.updated_at = now
                return session

            session = ChatSession(
                session_id=str(uuid4()),
                created_at=now,
                updated_at=now,
            )
            self._sessions[session.session_id] = session
            return session

    def append_message(self, session_id: str, role: str, content: str) -> None:
        """セッションへメッセージを追記する。"""
        with self._lock:
            session = self._sessions[session_id]
            session.messages.append(ChatMessage(role=role, content=content))
            session.updated_at = datetime.now(UTC)

    def history(self, session_id: str, limit: int) -> list[ChatMessage]:
        """直近 limit 件の会話履歴を返す。"""
        with self._lock:
            session = self._sessions[session_id]
            return session.messages[-limit:]

    def _cleanup_locked(self, now: datetime) -> None:
        expired_session_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.updated_at > self._ttl
        ]
        for session_id in expired_session_ids:
            self._sessions.pop(session_id, None)
