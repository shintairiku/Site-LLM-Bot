import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { embedTexts, toVectorLiteral } from "@/lib/openai";
import { chunkText } from "@/lib/chunk";
import { extractTextFromFile } from "@/lib/file-extract";
import { extractTextFromUrl } from "@/lib/url-extract";

const MAX_FILE_BYTES = 25 * 1024 * 1024; // 25MB
const ALLOWED_EXTENSIONS = ["pdf", "txt", "md"] as const;

interface Member {
  tenant_id: string;
}

const SELECT_COLUMNS =
  "id, kind, title, source_url, status, bytes, chunk_count, created_by, created_at";

async function resolveMember() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { supabase, user: null, member: null as Member | null };

  const { data: member } = await supabase
    .from("tenant_members")
    .select("tenant_id")
    .eq("email", user.email!)
    .single();

  return { supabase, user, member: (member as Member | null) ?? null };
}

export async function GET() {
  const { supabase, user } = await resolveMember();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { data, error } = await supabase
    .from("data_sources")
    .select(SELECT_COLUMNS)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(request: Request) {
  const { supabase, user, member } = await resolveMember();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  if (!member) return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const contentType = request.headers.get("content-type") ?? "";

  try {
    if (contentType.includes("multipart/form-data")) {
      return await handleFileUpload(supabase, member, user.email!, request);
    }
    return await handleUrlIngest(supabase, member, user.email!, request);
  } catch (err) {
    const message = err instanceof Error ? err.message : "取り込みに失敗しました";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/**
 * テキストをチャンク分割→embedding化し、data_sources と data_chunks に保存する。
 * チャンク保存に失敗した場合は data_sources 行を削除して整合を保つ（chunksはFKカスケードで除去）。
 */
async function ingest(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  params: {
    tenantId: string;
    email: string;
    kind: "pdf" | "text" | "url";
    title: string;
    sourceUrl: string | null;
    bytes: number;
    text: string;
  }
) {
  const chunks = chunkText(params.text);
  if (chunks.length === 0) {
    return NextResponse.json({ error: "本文を抽出できませんでした" }, { status: 400 });
  }

  const { data: source, error: sourceError } = await supabase
    .from("data_sources")
    .insert({
      tenant_id: params.tenantId,
      kind: params.kind,
      title: params.title,
      source_url: params.sourceUrl,
      bytes: params.bytes,
      chunk_count: chunks.length,
      status: "ready",
      created_by: params.email,
    })
    .select(SELECT_COLUMNS)
    .single();

  if (sourceError) {
    return NextResponse.json({ error: sourceError.message }, { status: 500 });
  }

  try {
    const embeddings = await embedTexts(chunks);
    const rows = chunks.map((content, i) => ({
      tenant_id: params.tenantId,
      data_source_id: source.id,
      chunk_index: i,
      content,
      embedding: toVectorLiteral(embeddings[i]),
    }));

    const { error: chunkError } = await supabase.from("data_chunks").insert(rows);
    if (chunkError) throw new Error(chunkError.message);
  } catch (err) {
    // 失敗したらメタデータ行ごとロールバック（chunksはカスケード削除）
    await supabase.from("data_sources").delete().eq("id", source.id);
    const message = err instanceof Error ? err.message : "embedding生成に失敗しました";
    return NextResponse.json({ error: message }, { status: 500 });
  }

  return NextResponse.json(source, { status: 201 });
}

async function handleFileUpload(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  member: Member,
  email: string,
  request: Request
) {
  const formData = await request.formData();
  const file = formData.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "ファイルが指定されていません" }, { status: 400 });
  }
  if (file.size === 0) {
    return NextResponse.json({ error: "空のファイルです" }, { status: 400 });
  }
  if (file.size > MAX_FILE_BYTES) {
    return NextResponse.json({ error: "ファイルサイズが大きすぎます（上限25MB）" }, { status: 400 });
  }

  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED_EXTENSIONS.includes(ext as (typeof ALLOWED_EXTENSIONS)[number])) {
    return NextResponse.json(
      { error: `対応していない形式です（${ALLOWED_EXTENSIONS.join(", ")} のみ）` },
      { status: 400 }
    );
  }

  const text = await extractTextFromFile(file);

  return ingest(supabase, {
    tenantId: member.tenant_id,
    email,
    kind: ext === "pdf" ? "pdf" : "text",
    title: file.name,
    sourceUrl: null,
    bytes: file.size,
    text,
  });
}

async function handleUrlIngest(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  supabase: any,
  member: Member,
  email: string,
  request: Request
) {
  const body = await request.json();
  const url = typeof body.url === "string" ? body.url.trim() : "";

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return NextResponse.json({ error: "URLの形式が不正です" }, { status: 400 });
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return NextResponse.json({ error: "http(s) のURLのみ対応しています" }, { status: 400 });
  }

  const { title, text } = await extractTextFromUrl(url);
  const bytes = new TextEncoder().encode(text).length;

  return ingest(supabase, {
    tenantId: member.tenant_id,
    email,
    kind: "url",
    title,
    sourceUrl: url,
    bytes,
    text: `${title}\n${url}\n\n${text}`,
  });
}

export async function DELETE(request: Request) {
  const { supabase, user } = await resolveMember();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });

  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  if (!id) return NextResponse.json({ error: "id is required" }, { status: 400 });

  // RLSにより自テナントの行のみ削除できる。data_chunks はFKカスケードで除去される。
  const { error } = await supabase.from("data_sources").delete().eq("id", id);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  return NextResponse.json({ ok: true });
}
