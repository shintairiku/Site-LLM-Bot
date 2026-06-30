-- テナントとGoogleアカウントのメールアドレスを紐づけるテーブル
create table if not exists public.tenant_members (
  email      text primary key,
  tenant_id  text not null,
  created_at timestamptz not null default now()
);

-- tenant_membersはサービスロールのみ操作可（管理者がダッシュボードで直接管理）
alter table public.tenant_members enable row level security;

create policy "tenant_members: 自身のレコードのみ参照可"
  on public.tenant_members
  for select
  using (email = auth.email());


-- analytics_unique_users: ログインユーザーの所属テナントのデータのみ参照可
alter table public.analytics_unique_users enable row level security;

create policy "analytics_unique_users: テナントフィルタ"
  on public.analytics_unique_users
  for select
  using (
    tenant_id::text = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );


-- analytics_chat_messages: ログインユーザーの所属テナントのデータのみ参照可
alter table public.analytics_chat_messages enable row level security;

create policy "analytics_chat_messages: テナントフィルタ"
  on public.analytics_chat_messages
  for select
  using (
    tenant_id::text = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );


-- analytics_related_link_clicks: ログインユーザーの所属テナントのデータのみ参照可
alter table public.analytics_related_link_clicks enable row level security;

create policy "analytics_related_link_clicks: テナントフィルタ"
  on public.analytics_related_link_clicks
  for select
  using (
    tenant_id::text = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );
