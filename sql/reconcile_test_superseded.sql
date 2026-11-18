-- Record the old OOM-interrupted test run as superseded by its successful rerun.
\set ON_ERROR_STOP on
UPDATE public.metrology_run old
SET state = 'permanent_failure',
    error_message = 'Interrupted by test OOM; superseded by a successful newer run',
    updated_at = now()
WHERE old.source = 'core-omero-test' AND old.fileset_id = 510
  AND old.state = 'running' AND old.analysis_version = 'meteor-core-eb0627a5760efb5c565913bef2a442532c647b6e'
  AND EXISTS (SELECT 1 FROM public.metrology_run newer
              WHERE newer.source = old.source AND newer.fileset_id = old.fileset_id
                AND newer.state = 'complete' AND newer.id <> old.id);
