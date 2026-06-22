set local role postgres;

create table if not exists public.analytics_session_feedback (
  id          bigserial primary key,
  tenant_id   text not null,
  session_id  text not null,
  visitor_id  text,
  resolved    boolean not null,
  page_url    text,
  occurred_at timestamptz not null default now()
);

create index if not exists analytics_session_feedback_tenant_occurred
  on public.analytics_session_feedback (tenant_id, occurred_at);

alter table public.analytics_session_feedback enable row level security;

create policy "analytics_session_feedback: テナントフィルタ"
  on public.analytics_session_feedback
  for select
  using (
    tenant_id::text = (
      select tenant_id from public.tenant_members
      where email = auth.email()
    )
  );

create or replace function record_session_feedback(
  p_tenant_id   text,
  p_session_id  text,
  p_visitor_id  text,
  p_resolved    boolean,
  p_page_url    text,
  p_occurred_at timestamptz
) returns void
language plpgsql
security definer
as $$
begin
  insert into public.analytics_session_feedback (
    tenant_id, session_id, visitor_id, resolved, page_url, occurred_at
  ) values (
    p_tenant_id, p_session_id, p_visitor_id, p_resolved, p_page_url, p_occurred_at
  );
end;
$$;

grant select on public.analytics_session_feedback to authenticated;
