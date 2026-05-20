from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_QUESTION = "会社について教えてください。"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "OpenAI Responses API の web_search が返した source URL と"
            " サブドメイン込みのドメインを確認する一時デバッグ用スクリプト。"
        )
    )
    parser.add_argument(
        "--tenant-id",
        help="config/tenants.json の tenant_id。未指定時は default_tenant_id を使用します。",
    )
    parser.add_argument(
        "--tenant-config",
        default=os.getenv("TENANT_CONFIG_PATH", "config/tenants.json"),
        help="テナント設定JSONのパス。",
    )
    parser.add_argument(
        "--allowed-domain",
        action="append",
        default=[],
        help="検索許可ドメイン。複数回指定可能。指定時は tenant 設定より優先します。",
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help="OpenAIへ投げる質問文。",
    )
    parser.add_argument(
        "--page-url",
        help="質問に付与する閲覧ページURL。",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        help="OpenAI model。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "60")),
        help="OpenAI API timeout seconds。",
    )
    parser.add_argument(
        "--raw-output",
        help="OpenAIの生レスポンスJSONを書き出すパス。",
    )
    parser.add_argument(
        "--from-raw",
        help="保存済みのOpenAIレスポンスJSONを読み込み、APIを呼ばずに解析します。",
    )
    parser.add_argument(
        "--show-answer",
        action="store_true",
        help="回答本文も表示します。",
    )
    args = parser.parse_args()

    allowed_domains = args.allowed_domain or load_allowed_domains(
        Path(args.tenant_config),
        args.tenant_id,
    )
    if not allowed_domains:
        raise SystemExit("allowed_domains が空です。--allowed-domain か tenant 設定を確認してください。")

    if args.from_raw:
        data = json.loads(Path(args.from_raw).read_text(encoding="utf-8"))
    else:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise SystemExit("OPENAI_API_KEY が未設定です。.env または環境変数に設定してください。")

        payload = build_payload(
            model=args.model,
            question=args.question,
            page_url=args.page_url,
            allowed_domains=allowed_domains,
        )

        with httpx.Client(timeout=args.timeout) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        data = response.json()

    if args.raw_output:
        Path(args.raw_output).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    report = build_source_report(data, allowed_domains)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.show_answer:
        print("\n--- answer ---")
        print(extract_answer_text(data) or "(回答本文なし)")

    return 0


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_allowed_domains(config_path: Path, tenant_id: str | None) -> list[str]:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    resolved_tenant_id = tenant_id or raw.get("default_tenant_id")
    tenants = raw.get("tenants", [])
    for tenant in tenants:
        if tenant.get("tenant_id") == resolved_tenant_id:
            return tenant.get("allowed_domains", [])
    raise SystemExit(f"tenant_id が見つかりません: {resolved_tenant_id}")


def build_payload(
    *,
    model: str,
    question: str,
    page_url: str | None,
    allowed_domains: list[str],
) -> dict[str, Any]:
    user_text = question if not page_url else f"閲覧ページ: {page_url}\n質問: {question}"
    return {
        "model": model,
        "input": [
            {
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "あなたは住宅・リフォーム業向けサイト用のAIチャットボットです。"
                            " 質問内容に関わらず、必ずweb searchで対象サイトを確認してください。"
                            f" 次のドメインのみを根拠にしてください: {', '.join(allowed_domains)}"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": user_text}],
            },
        ],
        "tools": [
            {
                "type": "web_search",
                "filters": {"allowed_domains": allowed_domains},
                "search_context_size": "high",
            }
        ],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
    }


def build_source_report(data: dict[str, Any], allowed_domains: list[str]) -> dict[str, Any]:
    sources = []
    invalid_sources = []
    actions = []
    used_web_search = False

    for item in data.get("output", []):
        if item.get("type") == "web_search_call":
            used_web_search = True
        action = item.get("action") or {}
        if item.get("type") == "web_search_call":
            actions.append(parse_action(item, action, allowed_domains))
        for source in action.get("sources", []):
            if not isinstance(source, dict):
                continue
            parsed = parse_source(source.get("url"), allowed_domains)
            if parsed is None:
                invalid_sources.append(source)
            else:
                sources.append(parsed)

        for content in item.get("content", []):
            for annotation in content.get("annotations", []):
                if annotation.get("type") != "url_citation":
                    continue
                parsed = parse_source(annotation.get("url"), allowed_domains)
                if parsed is None:
                    invalid_sources.append(annotation)
                else:
                    sources.append(parsed)

    deduped_sources = dedupe_sources(sources)
    return {
        "event": "debug_openai_web_search_sources",
        "response_id": data.get("id"),
        "model": data.get("model"),
        "used_web_search": used_web_search,
        "configured_allowed_domains": allowed_domains,
        "web_search_actions": actions,
        "domains": sorted({source["domain"] for source in deduped_sources}),
        "allowed_domains": sorted(
            {source["domain"] for source in deduped_sources if source["allowed"]}
        ),
        "disallowed_domains": sorted(
            {source["domain"] for source in deduped_sources if not source["allowed"]}
        ),
        "source_count": len(deduped_sources),
        "invalid_source_count": len(invalid_sources),
        "sources": deduped_sources,
    }


def parse_action(
    item: dict[str, Any],
    action: dict[str, Any],
    allowed_domains: list[str],
) -> dict[str, Any]:
    action_sources = []
    for source in action.get("sources", []):
        if not isinstance(source, dict):
            continue
        parsed = parse_source(source.get("url"), allowed_domains)
        if parsed is not None:
            action_sources.append(parsed)

    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "type": action.get("type"),
        "query": action.get("query"),
        "queries": action.get("queries", []),
        "url": action.get("url"),
        "pattern": action.get("pattern"),
        "source_count": len(action_sources),
        "sources": dedupe_sources(action_sources),
    }


def parse_source(url: Any, allowed_domains: list[str]) -> dict[str, Any] | None:
    if not isinstance(url, str) or not url:
        return None

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None

    domain = parsed.hostname.lower()
    normalized_url = parsed._replace(fragment="").geturl()
    return {
        "url": normalized_url,
        "domain": domain,
        "allowed": is_allowed_domain(domain, allowed_domains),
    }


def is_allowed_domain(domain: str, allowed_domains: list[str]) -> bool:
    normalized_allowed = [item.lower() for item in allowed_domains]
    return any(
        domain == allowed_domain or domain.endswith(f".{allowed_domain}")
        for allowed_domain in normalized_allowed
    )


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for source in sources:
        if source["url"] in seen:
            continue
        seen.add(source["url"])
        deduped.append(source)
    return deduped


def extract_answer_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    texts = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts)


if __name__ == "__main__":
    raise SystemExit(main())
