from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
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
    tenant_config_path: str
    default_tenant_id: str
    tenants: dict[str, "TenantConfig"] = field(default_factory=dict)
    allowed_origins: list[str] = field(default_factory=list)
    allowed_origin_regex: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        tenant_config_path = os.getenv("TENANT_CONFIG_PATH", "config/tenants.json")
        tenant_settings = load_tenant_settings(tenant_config_path)
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
            app_host=os.getenv("APP_HOST", "127.0.0.1"),
            app_port=int(os.getenv("APP_PORT", "8000")),
            openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "30")),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "1800")),
            max_history_messages=int(os.getenv("MAX_HISTORY_MESSAGES", "6")),
            tenant_config_path=tenant_config_path,
            default_tenant_id=tenant_settings.default_tenant_id,
            tenants=tenant_settings.tenants,
            allowed_origins=collect_allowed_origins(tenant_settings.tenants),
            allowed_origin_regex=build_allowed_origin_regex(tenant_settings.tenants),
        )


@dataclass(slots=True)
class TenantConfig:
    """テナントごとの表示設定と検索・埋め込み許可設定。"""

    tenant_id: str
    display_name: str
    primary_color: str
    greeting: str
    suggested_questions: list[str]
    allowed_origins: list[str]
    allowed_origin_patterns: list[str]
    allowed_domains: list[str]

    def is_origin_allowed(self, origin: str) -> bool:
        """固定 Origin または正規表現パターンで許可判定する。"""
        if origin in self.allowed_origins:
            return True
        return any(re.fullmatch(pattern, origin) for pattern in self.allowed_origin_patterns)


@dataclass(slots=True)
class TenantSettings:
    """外部ファイルから読み込んだテナント設定一式。"""

    default_tenant_id: str
    tenants: dict[str, TenantConfig]


def parse_csv_env(value: str) -> list[str]:
    """カンマ区切り環境変数を配列へ変換する。"""
    return [item.strip() for item in value.split(",") if item.strip()]


def load_tenant_settings(path: str) -> TenantSettings:
    """JSON ファイルからテナント設定を読み込む。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tenants: dict[str, TenantConfig] = {}
    for item in raw.get("tenants", []):
        tenant = TenantConfig(
            tenant_id=item["tenant_id"],
            display_name=item["display_name"],
            primary_color=item["primary_color"],
            greeting=item["greeting"],
            suggested_questions=item.get("suggested_questions", []),
            allowed_origins=item.get("allowed_origins", []),
            allowed_origin_patterns=item.get("allowed_origin_patterns", []),
            allowed_domains=item.get("allowed_domains", []),
        )
        tenants[tenant.tenant_id] = tenant
    default_tenant_id = raw.get("default_tenant_id", next(iter(tenants)))
    return TenantSettings(default_tenant_id=default_tenant_id, tenants=tenants)


def collect_allowed_origins(tenants: dict[str, TenantConfig]) -> list[str]:
    """CORS 用に全テナントの許可 Origin を収集する。"""
    origins: list[str] = []
    for tenant in tenants.values():
        for origin in tenant.allowed_origins:
            if origin not in origins:
                origins.append(origin)
    return origins


def build_allowed_origin_regex(tenants: dict[str, TenantConfig]) -> str | None:
    """CORS ミドルウェア用に全テナントの Origin regex を結合する。"""
    patterns: list[str] = []
    for tenant in tenants.values():
        for pattern in tenant.allowed_origin_patterns:
            if pattern not in patterns:
                patterns.append(pattern)
    if not patterns:
        return None
    return "|".join(f"(?:{pattern})" for pattern in patterns)
