-- Remove the agent's standalone deduplication probe, if it has no child rows.
\set ON_ERROR_STOP on
DELETE FROM public.metrology_run AS r
WHERE r.source = '__verification__' AND r.fileset_id = 999999
  AND NOT EXISTS (SELECT 1 FROM public.metrology_run_input i WHERE i.run_id = r.id)
  AND NOT EXISTS (SELECT 1 FROM public.metrology_measurement m WHERE m.run_id = r.id)
  AND NOT EXISTS (SELECT 1 FROM public.metrology_artifact a WHERE a.run_id = r.id);
