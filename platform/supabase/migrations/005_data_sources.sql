-- テナントごとのRAGデータソース（PDF/テキスト/URL）を pgvector で管理する。
-- ファイル本体はチャンク分割→embedding化したうえで data_chunks に保存し、
-- 推論時は質問のembeddingとの類似度検索（match_data_chunks）で関連チャンクを取り出す。
set local role postgres;

-- pgvector拡張。Supabaseでは extensions スキーマに作成されるため、
-- 型(vector)・演算子(<=>)・opクラス(vector_cosine_ops)を解決できるよう search_path に追加する。
create extension if not exists vector with schema extensions;
set local search_path = public, extensions;

-- 取り込んだデータソース1件ごとのメタデータ（管理画面の一覧表示用）
create table if not exists public.data_sources (
  id          uuid default gen_random_uuid() primary key,
  tenant_id   text not null,
  kind        text not null check (kind in ('pdf', 'text', 'url')),
  title       text not null,
  source_url  text,
  status      text not null default 'ready' check (status in ('processing', 'ready', 'error')),
  bytes       bigint,
  chunk_count integer not null default 0,
  created_by  text,
  created_at  timestamptz not null default now()
);

create index if not exists data_sources_tenant_id_created_at_idx
  on public.data_sources (tenant_id, created_at desc);

alter table public.data_sources enable row level security;

-- 再実行できるよう既存ポリシーを掃除してから作成する（create policyにif not existsが無いため）
drop policy if exists "data_sources: テナントフィルタ (select)" on public.data_sources;
drop policy if exists "data_sources: テナントフィルタ (insert)" on public.data_sources;
drop policy if exists "data_sources: テナントフィルタ (delete)" on public.data_sources;

create policy "data_sources: テナントフィルタ (select)"
  on public.data_sources for select
  using (
    tenant_id = (select tenant_id from public.tenant_members where email = auth.email())
  );

create policy "data_sources: テナントフィルタ (insert)"
  on public.data_sources for insert
  with check (
    tenant_id = (select tenant_id from public.tenant_members where email = auth.email())
  );

create policy "data_sources: テナントフィルタ (delete)"
  on public.data_sources for delete
  using (
    tenant_id = (select tenant_id from public.tenant_members where email = auth.email())
  );


-- チャンク本文 + embedding（text-embedding-3-small = 1536次元）
create table if not exists public.data_chunks (
  id             uuid default gen_random_uuid() primary key,
  tenant_id      text not null,
  data_source_id uuid not null references public.data_sources (id) on delete cascade,
  chunk_index    integer not null,
  content        text not null,
  embedding      vector(1536) not null,
  created_at     timestamptz not null default now()
);

create index if not exists data_chunks_data_source_id_idx
  on public.data_chunks (data_source_id);

-- コサイン距離でのHNSW近似最近傍索引
create index if not exists data_chunks_embedding_idx
  on public.data_chunks using hnsw (embedding vector_cosine_ops);

alter table public.data_chunks enable row level security;

-- プラットフォーム（authenticated）は自テナントのチャンクのみ追加可。
-- 参照は推論時にPython（service_role）がRPC経由で行うため select ポリシーは付けない。
drop policy if exists "data_chunks: テナントフィルタ (insert)" on public.data_chunks;

create policy "data_chunks: テナントフィルタ (insert)"
  on public.data_chunks for insert
  with check (
    tenant_id = (select tenant_id from public.tenant_members where email = auth.email())
  );


-- 質問embeddingとの類似度検索。query_embedding は '[...]' 形式の文字列で受け取り vector にキャスト。
-- テナント越境を防ぐため match_tenant でフィルタする。
create or replace function public.match_data_chunks(
  query_embedding text,
  match_tenant text,
  match_count int default 5
)
returns table (
  id uuid,
  data_source_id uuid,
  content text,
  similarity float
)
language sql
stable
set search_path = public, extensions
as $$
  select
    dc.id,
    dc.data_source_id,
    dc.content,
    1 - (dc.embedding <=> query_embedding::vector(1536)) as similarity
  from public.data_chunks dc
  where dc.tenant_id = match_tenant
  order by dc.embedding <=> query_embedding::vector(1536)
  limit match_count;
$$;

-- 権限付与：
-- - data_sources は authenticated が CRUD（RLSで自テナントに限定）
-- - data_chunks は authenticated が insert のみ
-- - 類似度検索RPCは推論側（service_role）専用に閉じる
grant select, insert, delete on public.data_sources to authenticated;
grant insert                 on public.data_chunks  to authenticated;

revoke execute on function public.match_data_chunks(text, text, int) from public, authenticated;
grant  execute on function public.match_data_chunks(text, text, int) to service_role;
