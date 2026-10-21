ALTER TABLE public.garmin_daily_metrics 
    ADD COLUMN IF NOT EXISTS training_status TEXT DEFAULT 'N/A',
    ADD COLUMN IF NOT EXISTS training_readiness INTEGER DEFAULT 0;

NOTIFY pgrst, 'reload schema';