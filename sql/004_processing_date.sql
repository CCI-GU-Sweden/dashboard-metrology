\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 3)
     OR EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 4) THEN
    RAISE EXCEPTION 'Expected schema version 3 without version 4';
  END IF;
END $$;
-- Old updated_at values may reflect retries rather than completion.
ALTER TABLE public.metrology_run ADD COLUMN processed_at timestamptz;
INSERT INTO public.metrology_schema_version(version) VALUES (4);
COMMIT;
