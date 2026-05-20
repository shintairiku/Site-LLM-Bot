from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import re
import unicodedata
from urllib.parse import urlparse

import httpx


MAX_FETCH_PAGES = 12
MAX_FETCH_BYTES = 1_200_000
MAX_CHUNKS_PER_PAGE = 10
DEFAULT_CHUNK_CHARS = 900
DEFAULT_CHUNK_OVERLAP = 180
DEFAULT_TOP_K = 8

SKIPPED_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "header",
    "footer",
    "nav",
}
BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "main",
    "p",
    "section",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
    "ol",
}
JAPANESE_RE = re.compile(r"[ぁ-んァ-ン一-龯々ー]+")
ASCII_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._/-]*")
DATE_RE = re.compile(
    r"(20\d{2}[./年-]\s?\d{1,2}(?:[./月-]\s?\d{1,2}日?)?|"
    r"\d{1,2}[./月-]\s?\d{1,2}日?)"
)
STOP_LITERALS = {
    "について",
    "教えてください",
    "教えて",
    "ください",
    "ですか",
    "ますか",
    "とは",
    "どこ",
    "なに",
    "何",
}


@dataclass(frozen=True, slots=True)
class PageCandidate:
    """web_search などから得た、取得対象ページの候補。"""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class FetchedPage:
    """HTTP 取得後に本文抽出まで済ませたページ。"""

    title: str
    url: str
    text: str


@dataclass(frozen=True, slots=True)
class RankedChunk:
    """最終回答の根拠候補としてスコア付きで扱う本文チャンク。"""

    title: str
    url: str
    text: str
    score: float


class _ReadableHTMLParser(HTMLParser):
    """HTML から title、description、本文らしいテキストを軽量に抽出するパーサー。"""

    def __init__(self) -> None:
        """HTMLParser の初期化と、本文抽出に使う内部状態を準備する。"""
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_depth = 0
        self._pieces: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """開始タグを処理し、不要領域のスキップやメタ情報の抽出を行う。"""
        normalized = tag.lower()
        if normalized in SKIPPED_TAGS:
            self._skip_depth += 1
            return
        if normalized == "title":
            self._in_title = True
            return
        if normalized == "meta":
            values = {key.lower(): value or "" for key, value in attrs}
            name = values.get("name", "").lower()
            prop = values.get("property", "").lower()
            if name == "description" or prop == "og:description":
                self.description = values.get("content", "").strip()
            return
        if normalized in BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        """終了タグを処理し、スキップ状態やブロック境界を更新する。"""
        normalized = tag.lower()
        if normalized in SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if normalized == "title":
            self._in_title = False
            return
        if normalized in BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        """タグ内の文字列を受け取り、title または本文候補として蓄積する。"""
        if self._skip_depth:
            return
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        self._pieces.append(text)

    def readable_text(self) -> str:
        """蓄積した本文候補を行単位に整え、重複行を除外して返す。"""
        lines: list[str] = []
        seen: set[str] = set()
        current = ""
        for piece in self._pieces:
            if piece == "\n":
                if current:
                    normalized = re.sub(r"\s+", " ", current).strip()
                    if normalized and normalized not in seen:
                        lines.append(normalized)
                        seen.add(normalized)
                    current = ""
                continue
            current = f"{current} {piece}".strip()
        if current and current not in seen:
            lines.append(current)
        return "\n".join(lines)


async def fetch_and_rank_context(
    client: httpx.AsyncClient,
    *,
    question: str,
    candidates: list[PageCandidate],
    allowed_domains: list[str],
    top_k: int = DEFAULT_TOP_K,
) -> list[RankedChunk]:
    """許可ドメイン内の候補ページを取得し、BM25 + regex boost で上位チャンクを返す。"""
    normalized_candidates = dedupe_allowed_candidates(candidates, allowed_domains)
    if not normalized_candidates:
        return []

    tasks = [
        _fetch_page(client, candidate)
        for candidate in normalized_candidates[:MAX_FETCH_PAGES]
        if _is_fetchable_url(candidate.url)
    ]
    if not tasks:
        return []

    pages = [page for page in await asyncio.gather(*tasks) if page is not None]
    if not pages:
        return []

    chunks = _build_chunks(pages)
    return rank_chunks(question, chunks, top_k=top_k)


def dedupe_allowed_candidates(
    candidates: list[PageCandidate],
    allowed_domains: list[str],
) -> list[PageCandidate]:
    """許可ドメイン内の候補 URL だけを正規化し、重複を除外して返す。"""
    normalized_allowed = [domain.lower() for domain in allowed_domains]
    deduped: list[PageCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        parsed = urlparse(candidate.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        host = parsed.hostname.lower()
        if normalized_allowed and not any(
            host == domain or host.endswith(f".{domain}") for domain in normalized_allowed
        ):
            continue
        url = parsed._replace(fragment="").geturl()
        if url in seen:
            continue
        title = candidate.title.strip() or _fallback_title(url)
        deduped.append(PageCandidate(title=title[:80], url=url))
        seen.add(url)
    return deduped


def extract_readable_html(html: str) -> tuple[str, str]:
    """HTML からページタイトルと、検索用の読みやすい本文テキストを抽出する。"""
    parser = _ReadableHTMLParser()
    parser.feed(html[:MAX_FETCH_BYTES])
    title = _clean_text(parser.title)
    description = _clean_text(parser.description)
    body = parser.readable_text()
    parts = [part for part in (title, description, body) if part]
    return title, "\n".join(parts)


def rank_chunks(
    question: str,
    chunks: list[RankedChunk],
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[RankedChunk]:
    """質問に対して各チャンクを BM25 と regex boost で採点し、上位だけを返す。"""
    if not chunks:
        return []

    query_terms = tokenize(question)
    tokenized_docs = [tokenize(f"{chunk.title}\n{chunk.text}\n{chunk.url}") for chunk in chunks]
    avgdl = sum(len(doc) for doc in tokenized_docs) / max(len(tokenized_docs), 1)
    doc_freq: Counter[str] = Counter()
    for doc in tokenized_docs:
        doc_freq.update(set(doc))

    ranked: list[RankedChunk] = []
    for chunk, doc_terms in zip(chunks, tokenized_docs, strict=True):
        bm25 = _bm25_score(query_terms, doc_terms, doc_freq, len(chunks), avgdl)
        boost = _regex_boost(question, chunk)
        ranked.append(
            RankedChunk(
                title=chunk.title,
                url=chunk.url,
                text=chunk.text,
                score=bm25 + boost,
            )
        )

    ranked.sort(key=lambda item: item.score, reverse=True)
    selected: list[RankedChunk] = []
    per_url: Counter[str] = Counter()
    for chunk in ranked:
        if chunk.score <= 0 and selected:
            continue
        if per_url[chunk.url] >= 3:
            continue
        selected.append(chunk)
        per_url[chunk.url] += 1
        if len(selected) >= top_k:
            break
    return selected


def tokenize(text: str) -> list[str]:
    """BM25 用に英数字トークンと日本語 n-gram トークンへ分解する。"""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    tokens.extend(ASCII_TOKEN_RE.findall(normalized))
    for match in JAPANESE_RE.finditer(normalized):
        value = match.group(0)
        if len(value) <= 2:
            tokens.append(value)
            continue
        tokens.extend(value[index : index + 2] for index in range(len(value) - 1))
        tokens.extend(value[index : index + 3] for index in range(len(value) - 2))
    return tokens


async def _fetch_page(
    client: httpx.AsyncClient,
    candidate: PageCandidate,
) -> FetchedPage | None:
    """候補 URL を取得し、HTML または text/plain から本文を抽出して返す。"""
    try:
        response = await client.get(
            candidate.url,
            headers={
                "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "Site-LLM-Bot/0.1",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    content_type = response.headers.get("content-type", "").lower()
    if content_type and not any(
        allowed in content_type for allowed in ("text/html", "text/plain", "application/xhtml")
    ):
        return None

    body = response.text[:MAX_FETCH_BYTES]
    if "html" in content_type or "<html" in body[:500].lower():
        parsed_title, text = extract_readable_html(body)
        title = parsed_title or candidate.title
    else:
        title = candidate.title
        text = _clean_text(body)

    if len(text) < 80:
        return None
    return FetchedPage(title=title or _fallback_title(candidate.url), url=candidate.url, text=text)


def _build_chunks(pages: list[FetchedPage]) -> list[RankedChunk]:
    """取得済みページ群の本文をチャンク化し、未採点の RankedChunk に変換する。"""
    chunks: list[RankedChunk] = []
    for page in pages:
        page_chunks = _chunk_text(page.text)
        for text in page_chunks[:MAX_CHUNKS_PER_PAGE]:
            chunks.append(RankedChunk(title=page.title, url=page.url, text=text, score=0.0))
    return chunks


def _chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """本文を段落境界に沿って、指定文字数と重なり幅を持つチャンクへ分割する。"""
    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if current and current_len + len(paragraph) + 1 > max_chars:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
            tail = chunk[-overlap:] if overlap and len(chunk) > overlap else ""
            current = [tail] if tail else []
            current_len = len(tail)
        current.append(paragraph)
        current_len += len(paragraph) + 1

    if current:
        chunk = "\n".join(current).strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _bm25_score(
    query_terms: list[str],
    doc_terms: list[str],
    doc_freq: Counter[str],
    total_docs: int,
    avgdl: float,
) -> float:
    """クエリ語と文書語から BM25 スコアを計算する。"""
    if not query_terms or not doc_terms:
        return 0.0

    term_counts = Counter(doc_terms)
    doc_len = len(doc_terms)
    score = 0.0
    k1 = 1.4
    b = 0.72
    for term in query_terms:
        df = doc_freq.get(term, 0)
        if not df:
            continue
        idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
        tf = term_counts[term]
        denom = tf + k1 * (1 - b + b * doc_len / max(avgdl, 1.0))
        score += idf * (tf * (k1 + 1) / denom)
    return score


def _regex_boost(question: str, chunk: RankedChunk) -> float:
    """質問意図に合う固定語句や日時・施工事例などの手がかりで追加点を計算する。"""
    normalized_question = unicodedata.normalize("NFKC", question).lower()
    haystack = unicodedata.normalize(
        "NFKC",
        f"{chunk.title}\n{chunk.url}\n{chunk.text}",
    ).lower()
    boost = 0.0

    for literal in _query_literals(normalized_question):
        if re.search(re.escape(literal), haystack):
            boost += min(1.6, 0.25 + len(literal) / 8)

    if any(word in normalized_question for word in ("最新", "新しい", "直近", "新着")):
        if any(word in haystack for word in ("最新", "新着", "new", "更新日", "投稿日")):
            boost += 1.5
        if DATE_RE.search(haystack):
            boost += 0.8

    if any(word in normalized_question for word in ("施工事例", "事例", "実績", "works", "case")):
        if any(word in haystack for word in ("施工事例", "事例", "/works", "/case")):
            boost += 1.2

    if any(word in normalized_question for word in ("費用", "価格", "料金", "金額", "いくら")):
        if any(word in haystack for word in ("費用", "価格", "料金", "万円", "円")):
            boost += 1.0

    if any(word in normalized_question for word in ("エリア", "地域", "対応", "施工エリア")):
        if any(word in haystack for word in ("エリア", "地域", "対応", "施工エリア")):
            boost += 1.0

    return boost


def _query_literals(question: str) -> list[str]:
    """質問文から regex boost 用の検索語句を抽出し、長い語は部分語に分割する。"""
    literals: list[str] = []
    for value in re.findall(r"[a-z0-9][a-z0-9._/-]*|[ぁ-んァ-ン一-龯々ー]{2,}", question):
        if value in STOP_LITERALS:
            continue
        if len(value) <= 12:
            literals.append(value)
            continue
        for size in (4, 5, 6):
            literals.extend(value[index : index + size] for index in range(len(value) - size + 1))
    seen: set[str] = set()
    deduped: list[str] = []
    for literal in literals:
        if literal in seen:
            continue
        seen.add(literal)
        deduped.append(literal)
    return deduped[:30]


def _is_fetchable_url(url: str) -> bool:
    """HTML 本文抽出の対象外にしたい画像・PDF・zip などの URL を除外する。"""
    path = urlparse(url).path.lower()
    return not path.endswith(
        (
            ".bmp",
            ".gif",
            ".ico",
            ".jpeg",
            ".jpg",
            ".pdf",
            ".png",
            ".svg",
            ".webp",
            ".zip",
        )
    )


def _fallback_title(url: str) -> str:
    """タイトルが取れない場合に URL パスやホスト名から表示用タイトルを作る。"""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return parsed.hostname or "関連ページ"
    return path.split("/")[-1].removesuffix(".html").removesuffix(".htm") or "関連ページ"


def _clean_text(text: str) -> str:
    """改行と空白を整え、前後の余白を削除する。"""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
