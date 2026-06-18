-- テナントごとのプロンプトを履歴付きで管理するテーブル
-- 現在のプロンプト = tenant_idごとの最新レコード（created_at降順の先頭）
create table if not exists public.prompts (
  id          uuid default gen_random_uuid() primary key,
  tenant_id   text not null,
  content     text not null,
  note        text,
  created_by  text,
  created_at  timestamptz not null default now()
);

create index if not exists prompts_tenant_id_created_at_idx
  on public.prompts (tenant_id, created_at desc);

alter table public.prompts enable row level security;

-- 自テナントのプロンプトのみ参照可
create policy "prompts: テナントフィルタ (select)"
  on public.prompts
  for select
  using (
    tenant_id = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );

-- 自テナントのプロンプトのみ追加可
create policy "prompts: テナントフィルタ (insert)"
  on public.prompts
  for insert
  with check (
    tenant_id = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );
