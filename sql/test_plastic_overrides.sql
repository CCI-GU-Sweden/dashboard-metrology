-- Test-only overrides for the two clearly named Plastic CZI filesets.
\set ON_ERROR_STOP on
BEGIN;
INSERT INTO public.metrology_analysis_override(source,image_id,category)
VALUES ('core-omero-test',561,'Plastic_Field_Uniformity'),
       ('core-omero-test',556,'Plastic_Field_Uniformity')
ON CONFLICT (source,image_id) DO UPDATE SET category=EXCLUDED.category, updated_at=now();
COMMIT;
