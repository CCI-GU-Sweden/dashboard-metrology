\set ON_ERROR_STOP on
INSERT INTO public.metrology_analysis_override(source,image_id,category)
VALUES ('core-omero-test',552,'Psf_Measure')
ON CONFLICT (source,image_id) DO UPDATE SET category=EXCLUDED.category, updated_at=now();
