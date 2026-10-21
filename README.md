# garmin-perissos
Perissos is a personal website designed to be a dashboard for my life. 

## Garmin → Supabase setup

1. Run `supabase/garmin_daily_metrics.sql` in the Supabase SQL editor. It adds
   the dashboard columns and backfills `active_minutes` from legacy `active_min`.
   Existing legacy columns remain available. This script does not change access policies.
2. Configure Actions secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and either
   `GARMIN_TOKEN_BASE64` (base64 JSON mapping OAuth filenames to token objects)
   or `GARMIN_EMAIL` / `GARMIN_PASSWORD`. Keep the service key in Actions only;
   the dashboard uses the anon key with appropriately configured database policies.
3. Optional Actions variables: `SUPABASE_USER_ID` (default `default`, must match
   the dashboard's Personal Sync Key) and `GARMIN_TIMEZONE` (default `Asia/Shanghai`).
4. Run the Garmin workflow manually, then refresh the dashboard cloud data.

The current dashboard and importer support one account per database table:
`date` is the unique upsert key. The editable user ID is a filter, not an
access-control boundary. Multiple accounts would require coordinated changes
in both clients and the database to use `(user_id, date)`.

Garmin sync writes `active_minutes` and an `activities` JSON array matching the
frontend. Missing measurements are omitted rather than replaced with invented
values; existing measurements survive updates. Manual logs and hydration are
left untouched. New rows need nullable/defaulted omitted columns, as in the
setup SQL. If an older schema has additional NOT NULL columns without defaults,
review those constraints before running the new importer.

Run offline payload checks with `python3 -m unittest discover -s tests`.

Training readiness is fetched separately using Garmin's
`get_training_readiness(date)` endpoint. The morning (`AFTER_WAKEUP_RESET`)
score is preferred, falling back to the first returned snapshot. Empty or
failed responses are logged and do not overwrite existing scores. Your watch
must support training readiness and have synced it to Garmin Connect.
`training_status` is a separate Garmin metric and is not currently imported.
The dashboard does not currently display training readiness.
