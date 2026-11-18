-- Apply after baseline 1 with a setup identity. Overrides are specific to an
-- OMERO image and can be removed to restore automatic classification.
\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 1)
     OR EXISTS (SELECT 1 FROM public.metrology_schema_version WHERE version = 2) THEN
    RAISE EXCEPTION 'Expected schema version 1 without version 2';
  END IF;
END $$;
CREATE TABLE public.metrology_analysis_override (
    source text NOT NULL,
    image_id bigint NOT NULL,
    category text NOT NULL CHECK (category IN ('Argo_2D_Rings_Analysis', 'Argo_Intensity_Linearity', 'Psf_Measure', 'Plastic_Field_Uniformity', '3D_Crossing_Stairs', 'star_resolution')),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by bigint,
    PRIMARY KEY (source, image_id)
);
GRANT SELECT ON public.metrology_analysis_override TO metrology_processor, filestats_dashboard;
GRANT INSERT, UPDATE, DELETE ON public.metrology_analysis_override TO filestats_dashboard;
INSERT INTO public.metrology_schema_version(version) VALUES (2);
COMMIT;
