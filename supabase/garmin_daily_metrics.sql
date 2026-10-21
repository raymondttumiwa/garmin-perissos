-- Single-user dashboard schema: both clients upsert on date.
-- Run in the Supabase SQL editor before enabling the updated sync.
begin;
create table if not exists public.garmin_daily_metrics (
    date date primary key
);
alter table public.garmin_daily_metrics
    add column if not exists user_id text default 'default',
    add column if not exists training_readiness integer,
    add column if not exists training_status text,
    add column if not exists steps integer,
    add column if not exists sleep_hours numeric,
    add column if not exists sleep_score integer,
    add column if not exists active_minutes integer,
    add column if not exists resting_hr integer,
    add column if not exists body_battery integer,
    add column if not exists stress_avg integer,
    add column if not exists hydration_ml integer,
    add column if not exists manual_logs jsonb default '{}'::jsonb,
    add column if not exists activities jsonb default '[]'::jsonb;

update public.garmin_daily_metrics set user_id = 'default' where user_id is null;
alter table public.garmin_daily_metrics alter column user_id set default 'default';

-- An absent reading must not look like a measured zero.
-- Existing scores are preserved; legacy zeros cannot be distinguished safely.
alter table public.garmin_daily_metrics
    alter column training_readiness drop default;

-- Preserve historical active-minute values from the previous importer.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'garmin_daily_metrics'
          and column_name = 'active_min'
    ) then
        execute 'update public.garmin_daily_metrics set active_minutes = active_min where active_minutes is null';
    end if;
end $$;

-- Required by the importer's on_conflict=date and the dashboard's upsert.
-- Existing duplicate dates must be resolved before this index can be created.
create unique index if not exists garmin_daily_metrics_date_sync_key
    on public.garmin_daily_metrics (date);
notify pgrst, 'reload schema';
commit;
