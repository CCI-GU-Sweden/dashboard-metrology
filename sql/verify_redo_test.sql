-- Test real grants, duplicate handling and generation switching without retaining changes.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL ROLE filestats_dashboard;
DO $$
DECLARE m_id bigint; src text; fs bigint; old_run bigint; inserted integer;
BEGIN
 SELECT m.id,r.source,r.fileset_id,r.id INTO m_id,src,fs,old_run
 FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id LIMIT 1;
 IF m_id IS NULL THEN RAISE EXCEPTION 'No completed measurement to test'; END IF;
 INSERT INTO metrology_redo_request(source,fileset_id,measurement_id,requested_by)
 VALUES(src,fs,m_id,-1);
 INSERT INTO metrology_redo_request(source,fileset_id,measurement_id,requested_by)
 VALUES(src,fs,m_id,-1) ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS inserted = ROW_COUNT;
 IF inserted <> 0 THEN RAISE EXCEPTION 'Duplicate queue request was accepted'; END IF;
END $$;
RESET ROLE;
SET LOCAL ROLE metrology_processor;
DO $$
DECLARE req public.metrology_redo_request%ROWTYPE; old_run public.metrology_run%ROWTYPE; new_run bigint;
BEGIN
 SELECT * INTO req FROM public.metrology_redo_request WHERE requested_by=-1 ORDER BY id DESC LIMIT 1 FOR UPDATE;
 SELECT * INTO old_run FROM public.metrology_current_run WHERE source=req.source AND fileset_id=req.fileset_id;
 INSERT INTO public.metrology_run(source,group_id,fileset_id,analysis_version,config_hash,generation,state,attempt_count)
 VALUES(req.source,old_run.group_id,req.fileset_id,'redo-test','redo-test',old_run.generation+1000,'running',1) RETURNING id INTO new_run;
 UPDATE public.metrology_redo_request SET run_id=new_run,state='running' WHERE id=req.id;
 IF (SELECT id FROM public.metrology_current_run WHERE source=req.source AND fileset_id=req.fileset_id) <> old_run.id THEN
   RAISE EXCEPTION 'Running replacement hid the previous result';
 END IF;
 UPDATE public.metrology_run SET state='retryable_failure' WHERE id=new_run;
 UPDATE public.metrology_redo_request SET state='pending',error_message='test failure' WHERE id=req.id;
 IF (SELECT id FROM public.metrology_current_run WHERE source=req.source AND fileset_id=req.fileset_id) <> old_run.id THEN
   RAISE EXCEPTION 'Failed replacement hid the previous result';
 END IF;
 UPDATE public.metrology_run SET state='complete',processed_at=now() WHERE id=new_run;
 UPDATE public.metrology_redo_request SET state='complete' WHERE id=req.id;
 IF (SELECT id FROM public.metrology_current_run WHERE source=req.source AND fileset_id=req.fileset_id) <> new_run THEN
   RAISE EXCEPTION 'Successful replacement did not become current';
 END IF;
END $$;
RESET ROLE;
SET LOCAL ROLE dashboard_backup_reader;
LOCK TABLE public.metrology_redo_request IN ACCESS SHARE MODE;
SELECT count(*) FROM public.metrology_redo_request;
ROLLBACK;
