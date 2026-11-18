\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 2)
     OR EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 3) THEN
    RAISE EXCEPTION 'Expected schema version 2 without version 3';
  END IF;
END $$;
ALTER TABLE public.metrology_artifact ADD COLUMN payload bytea;
INSERT INTO public.metrology_schema_version(version) VALUES (3);
COMMIT;
