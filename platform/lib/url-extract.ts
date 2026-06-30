// 登録URLをクロールして本文テキストを抽出する。
// RAG取り込み用なので、装飾よりも読めるプレーンテキスト化を優先する。

export interface ExtractedPage {
  title: string;
  text: string;
}

const MAX_BYTES = 5_000_000; // 取り込み上限（暴走防止）

export async function extractTextFromUrl(url: string): Promise<ExtractedPage> {
  const res = await fetch(url, {
    headers: { "User-Agent": "SiteLLMBot-Ingest/1.0" },
    redirect: "follow",
  });
  if (!res.ok) {
    throw new Error(`URLの取得に失敗しました (HTTP ${res.status})`);
  }

  const contentType = res.headers.get("content-type") ?? "";
  const raw = await res.text();
  if (raw.length > MAX_BYTES) {
    throw new Error("ページが大きすぎます");
  }

  // HTML以外（text/plain等）はそのまま本文として扱う
  if (!contentType.includes("html")) {
    return { title: deriveTitleFromUrl(url), text: raw.trim() };
  }

  const title = extractTitle(raw) ?? deriveTitleFromUrl(url);
  const text = htmlToText(raw);
  if (!text) {
    throw new Error("本文を抽出できませんでした");
  }
  return { title, text };
}

function extractTitle(html: string): string | null {
  const match = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (!match) return null;
  const title = decodeEntities(match[1]).replace(/\s+/g, " ").trim();
  return title || null;
}

function htmlToText(html: string): string {
  let text = html;
  // 本文に不要な要素を中身ごと除去
  text = text.replace(/<script[\s\S]*?<\/script>/gi, " ");
  text = text.replace(/<style[\s\S]*?<\/style>/gi, " ");
  text = text.replace(/<noscript[\s\S]*?<\/noscript>/gi, " ");
  text = text.replace(/<!--[\s\S]*?-->/g, " ");
  // 改行要素(br)は単一改行
  text = text.replace(/<br\s*\/?>/gi, "\n");
  // 段落・見出し・リスト項目・表行などブロック要素の終わりは段落区切り(空行)にする。
  // こうしておくとチャンク分割の段落境界(\n\n)が機能し、文脈を保ちやすい。
  text = text.replace(
    /<\/(p|div|section|article|header|footer|main|aside|h[1-6]|li|ul|ol|tr|table|blockquote|pre)\s*>/gi,
    "\n\n"
  );
  // 残りのタグを除去
  text = text.replace(/<[^>]+>/g, " ");
  text = decodeEntities(text);
  // 空白・改行の正規化（行内空白は1つ、行頭行末の空白除去、3連以上の改行は2連に）
  text = text.replace(/[ \t]+/g, " ");
  text = text.replace(/ *\n */g, "\n");
  text = text.replace(/\n{3,}/g, "\n\n");
  return text.trim();
}

function decodeEntities(s: string): string {
  return s
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/gi, "'")
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code, 10)));
}

function deriveTitleFromUrl(url: string): string {
  try {
    const { hostname, pathname } = new URL(url);
    const last = pathname.split("/").filter(Boolean).pop();
    return last ? `${hostname} / ${decodeURIComponent(last)}` : hostname;
  } catch {
    return url;
  }
}
