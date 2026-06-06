import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ANALYTICS_LOGGER = logging.getLogger("site_llm_bot.analytics")
ANALYTICS_LOGGER.setLevel(logging.INFO)
if not ANALYTICS_LOGGER.handlers:
    analytics_log_handler = logging.StreamHandler()
    analytics_log_handler.setFormatter(logging.Formatter("%(message)s"))
    ANALYTICS_LOGGER.addHandler(analytics_log_handler)
ANALYTICS_LOGGER.propagate = False


@dataclass(slots=True)
class ChatMessageSentEvent:
    """チャットメッセージ送信イベント。"""

    tenant_id: str
    session_id: str
    origin: str | None
    page_url: str | None
    occurred_at: datetime
    visitor_id: str | None = None


@dataclass(slots=True)
class UserFirstSeenEvent:
    """匿名利用者の初回利用イベント。"""

    tenant_id: str
    visitor_id: str
    origin: str | None
    page_url: str | None
    occurred_at: datetime


class AnalyticsStore:
    """記録処理のインターフェース。"""

    def record_chat_message_sent(self, event: ChatMessageSentEvent) -> None:
        """チャットメッセージ送信イベントを記録する。"""
        raise NotImplementedError

    def record_user_first_seen(self, event: UserFirstSeenEvent) -> None:
        """匿名利用者の初回利用イベントを記録する。"""
        raise NotImplementedError


class LoggingAnalyticsStore(AnalyticsStore):
    """構造化JSONを標準エラーへ出力し、Cloud Runログへ記録する実装。"""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or ANALYTICS_LOGGER

    def record_chat_message_sent(self, event: ChatMessageSentEvent) -> None:
        """チャットメッセージ送信イベントをCloud Runログへ記録する。"""
        payload = build_chat_message_sent_payload(event)
        payload["message"] = "chat_message_sent"
        payload["severity"] = "INFO"
        self._logger.info(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )

    def record_user_first_seen(self, event: UserFirstSeenEvent) -> None:
        """匿名利用者の初回利用イベントをCloud Runログへ記録する。"""
        payload = build_user_first_seen_payload(event)
        payload["message"] = "user_first_seen"
        payload["severity"] = "INFO"
        self._logger.info(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )


class JsonAnalyticsStore(AnalyticsStore):
    """JSONファイルに記録する実装。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()

    def record_chat_message_sent(self, event: ChatMessageSentEvent) -> None:
        """チャットメッセージ送信イベントを記録する。"""
        event_json = build_chat_message_sent_payload(event)
        self._append_event(event_json)

    def record_user_first_seen(self, event: UserFirstSeenEvent) -> None:
        """匿名利用者の初回利用イベントを記録する。"""
        event_json = build_user_first_seen_payload(event)
        self._append_event(event_json)

    def _append_event(self, event_json: dict[str, str | None]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                json.dump(event_json, f, ensure_ascii=False)
                f.write("\n")


def build_chat_message_sent_payload(event: ChatMessageSentEvent) -> dict[str, str | None]:
    """チャット送信イベントを保存・ログ出力用の辞書へ変換する。"""
    return {
        "event_type": "chat_message_sent",
        "tenant_id": event.tenant_id,
        "session_id": event.session_id,
        "visitor_id": event.visitor_id,
        "origin": event.origin,
        "page_url": event.page_url,
        "occurred_at": event.occurred_at.isoformat(),
    }


def build_user_first_seen_payload(event: UserFirstSeenEvent) -> dict[str, str | None]:
    """初回利用イベントを保存・ログ出力用の辞書へ変換する。"""
    return {
        "event_type": "user_first_seen",
        "tenant_id": event.tenant_id,
        "visitor_id": event.visitor_id,
        "origin": event.origin,
        "page_url": event.page_url,
        "occurred_at": event.occurred_at.isoformat(),
    }
