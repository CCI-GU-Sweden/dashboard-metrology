\set ON_ERROR_STOP on
BEGIN;
DO $$ DECLARE constraint_name text; BEGIN
 IF (SELECT max(version) FROM public.metrology_schema_version) <> 5 THEN
   RAISE EXCEPTION 'Expected schema version 5';
 END IF;
 FOR constraint_name IN SELECT conname FROM pg_constraint WHERE conrelid='public.metrology_threshold'::regclass AND contype='u' LOOP
   EXECUTE format('ALTER TABLE public.metrology_threshold DROP CONSTRAINT %I', constraint_name);
 END LOOP;
END $$;
ALTER TABLE public.metrology_threshold ADD COLUMN unit text;
ALTER TABLE public.metrology_threshold ADD COLUMN created_by bigint;
ALTER TABLE public.metrology_threshold ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE public.metrology_threshold ADD CONSTRAINT metrology_threshold_version_key
 UNIQUE NULLS NOT DISTINCT (category,measurement_type,magnification,numerical_aperture,unit,version);
ALTER TABLE public.metrology_redo_request ALTER COLUMN measurement_id DROP NOT NULL;
ALTER TABLE public.metrology_redo_request ADD COLUMN requested_run_id bigint REFERENCES public.metrology_run(id);
UPDATE public.metrology_redo_request q SET requested_run_id=m.run_id FROM public.metrology_measurement m WHERE m.id=q.measurement_id;
ALTER TABLE public.metrology_run ADD COLUMN source_image_ids bigint[];
GRANT INSERT ON public.metrology_threshold TO filestats_dashboard;
GRANT USAGE, SELECT ON SEQUENCE public.metrology_threshold_id_seq TO filestats_dashboard;
INSERT INTO public.metrology_schema_version(version) VALUES (6);
COMMIT;
