-- Run garmin_daily_metrics.sql FIRST. Back up existing data before running.
-- Existing unassigned rows are retained but are not visible to any new account.
begin;

-- Replaces the single-account date key with an account + date key.
alter table public.garmin_daily_metrics alter column user_id drop default;
update public.garmin_daily_metrics set user_id = 'legacy-unassigned' where user_id is null;
alter table public.garmin_daily_metrics alter column user_id set not null;
do $$
declare key_name text;
begin
    for key_name in select conname from pg_constraint
        where conrelid = 'public.garmin_daily_metrics'::regclass and contype in ('p', 'u')
        and conkey = array[(select attnum from pg_attribute where attrelid = 'public.garmin_daily_metrics'::regclass and attname = 'date')]::smallint[]
    loop
        execute format('alter table public.garmin_daily_metrics drop constraint %I', key_name);
    end loop;
end $$;
drop index if exists public.garmin_daily_metrics_date_sync_key;
create unique index if not exists garmin_daily_metrics_account_date_key
    on public.garmin_daily_metrics(user_id, date);

-- Remove ALL old public policies. RLS policies combine with OR, so leaving one
-- permissive policy would defeat account isolation.
do $$
declare policy_row record;
begin
    for policy_row in select policyname from pg_policies
        where schemaname = 'public' and tablename = 'garmin_daily_metrics'
    loop
        execute format('drop policy %I on public.garmin_daily_metrics', policy_row.policyname);
    end loop;
end $$;
alter table public.garmin_daily_metrics enable row level security;
revoke all on public.garmin_daily_metrics from anon;
grant select, insert, update on public.garmin_daily_metrics to authenticated;
create policy account_read on public.garmin_daily_metrics for select to authenticated
    using (user_id = (select auth.uid())::text);
create policy account_insert on public.garmin_daily_metrics for insert to authenticated
    with check (user_id = (select auth.uid())::text);
create policy account_update on public.garmin_daily_metrics for update to authenticated
    using (user_id = (select auth.uid())::text)
    with check (user_id = (select auth.uid())::text);

create table if not exists public.dashboard_goals (
    user_id uuid primary key references auth.users(id) on delete cascade,
    rules jsonb not null default '[]'::jsonb check (jsonb_typeof(rules) = 'array')
);
alter table public.dashboard_goals enable row level security;
revoke all on public.dashboard_goals from anon;
grant select, insert, update on public.dashboard_goals to authenticated;
drop policy if exists own_goals_read on public.dashboard_goals;
drop policy if exists own_goals_insert on public.dashboard_goals;
drop policy if exists own_goals_update on public.dashboard_goals;
create policy own_goals_read on public.dashboard_goals for select to authenticated using (user_id = (select auth.uid()));
create policy own_goals_insert on public.dashboard_goals for insert to authenticated with check (user_id = (select auth.uid()));
create policy own_goals_update on public.dashboard_goals for update to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
notify pgrst, 'reload schema';
commit;
