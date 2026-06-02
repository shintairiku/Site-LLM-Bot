import json
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class ChatMessageSentEvent:
    """チャットメッセージ送信イベント。"""

    tenant_id: str
    session_id: str
    origin: str | None
    page_url: str | None
    occurred_at: datetime


class AnalyticsStore:
    """記録処理のインターフェース。"""

    def record_chat_message_sent(self, event: ChatMessageSentEvent) -> None:
        """チャットメッセージ送信イベントを記録する。"""
        raise NotImplementedError


class JsonAnalyticsStore(AnalyticsStore):
    """JSONファイルに記録する実装。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record_chat_message_sent(self, event: ChatMessageSentEvent) -> None:
        """チャットメッセージ送信イベントを記録する。"""
        event_json = {
            "event_type": "chat_message_sent",
            "tenant_id": event.tenant_id,
            "session_id": event.session_id,
            "origin": event.origin,
            "page_url": event.page_url,
            "occurred_at": event.occurred_at.isoformat(),
        }

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                json.dump(event_json, f, ensure_ascii=False)
                f.write("\n")
