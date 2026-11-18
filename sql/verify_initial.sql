\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 1) THEN RAISE EXCEPTION 'baseline missing'; END IF;
  IF (SELECT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = 'metrology_processor') THEN RAISE EXCEPTION 'unsafe processor role'; END IF;
  IF NOT has_table_privilege('metrology_processor', 'public.metrology_run', 'INSERT,UPDATE,SELECT') THEN RAISE EXCEPTION 'processor grants missing'; END IF;
  IF has_table_privilege('metrology_processor', 'public.metrology_run', 'DELETE') THEN RAISE EXCEPTION 'processor delete grant'; END IF;
  IF NOT has_column_privilege('filestats_dashboard', 'public.metrology_measurement', 'status', 'UPDATE') THEN RAISE EXCEPTION 'status grant missing'; END IF;
  IF has_column_privilege('filestats_dashboard', 'public.metrology_measurement', 'value', 'UPDATE') THEN RAISE EXCEPTION 'unexpected measurement update grant'; END IF;
END $$;
INSERT INTO public.metrology_microscope(name) VALUES ('__schema_verification__');
INSERT INTO public.metrology_lens(microscope_id, magnification) SELECT id, 'test' FROM public.metrology_microscope WHERE name='__schema_verification__';
DO $$
BEGIN
  BEGIN
    INSERT INTO public.metrology_lens(microscope_id, magnification) SELECT id, 'test' FROM public.metrology_microscope WHERE name='__schema_verification__';
    RAISE EXCEPTION 'nullable lens uniqueness not enforced';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;
ROLLBACK;
