from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_dotenv(path: str = ".env") -> None:
    """最小限の .env ローダー。依存ライブラリなしでローカル設定を読み込む。"""
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(slots=True)
class Settings:
    """API ハンドラが参照する実行設定。"""

    openai_api_key: str | None
    openai_model: str
    app_host: str
    app_port: int
    openai_timeout_seconds: float
    session_ttl_seconds: int
    max_history_messages: int
    allowed_origins: list[str]
    search_allowed_domains: list[str]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8000")),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "1800")),
            max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "6")),
            allowed_origins=parse_csv_env(
                os.getenv(
                    "ALLOWED_ORIGINS",
                    "http://127.0.0.1:8000,http://localhost:8000,null",
                )
            ),
            search_allowed_domains=parse_csv_env(
                os.getenv("SEARCH_ALLOWED_DOMAINS", "shintairiku.jp")
            ),
        )


def parse_csv_env(value: str) -> list[str]:
    """カンマ区切り環境変数を配列へ変換する。"""
    return [item.strip() for item in value.split(",") if item.strip()]
