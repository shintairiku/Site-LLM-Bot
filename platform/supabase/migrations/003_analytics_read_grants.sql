-- analytics_* テーブルは元々 service_role のみ書き込み可能な設定だが、
-- プラットフォーム（ログイン済みテナント）が読み取れるよう SELECT を付与する。
-- RLS ポリシー（001 で設定済み）により、自テナントのデータのみ参照できる。

grant select on public.analytics_chat_messages      to authenticated;
grant select on public.analytics_unique_users       to authenticated;
grant select on public.analytics_related_link_clicks to authenticated;
