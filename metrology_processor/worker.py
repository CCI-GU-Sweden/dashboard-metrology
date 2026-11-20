"""Standalone scheduled metrology worker."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import sys

import psycopg
from psycopg.types.json import Jsonb

from .analysis import analyze_fileset
from .omero_io import attach, connect, filesets
from .metadata import positive_number
from .dates import acquired_at

LOG = logging.getLogger(__name__)
VERSION = "meteor-core-" + os.getenv("METEOR_CORE_REVISION", "3de0672afc60199a6fca7be79fb041b730114e47")
CONFIG = "v1"


def claim(db, source, group_id, fileset_id, imported_ms):
    with db.transaction():
        redo = db.execute("SELECT id,run_id FROM public.metrology_redo_request WHERE source=%s AND fileset_id=%s AND state IN ('pending','running') FOR UPDATE", (source, fileset_id)).fetchone()
        if redo:
            request_id, run_id = redo
            if run_id is None:
                imported = datetime.fromtimestamp(imported_ms / 1000, timezone.utc) if imported_ms is not None else None
                generation = db.execute("SELECT COALESCE(max(generation),0)+1 FROM public.metrology_run WHERE source=%s AND fileset_id=%s", (source, fileset_id)).fetchone()[0]
                run_id = db.execute("INSERT INTO public.metrology_run(source,group_id,fileset_id,analysis_version,config_hash,generation,state,attempt_count,imported_at) VALUES(%s,%s,%s,%s,%s,%s,'running',1,%s) RETURNING id", (source, group_id, fileset_id, VERSION, CONFIG, generation, imported)).fetchone()[0]
                db.execute("UPDATE public.metrology_redo_request SET run_id=%s,state='running',updated_at=now() WHERE id=%s", (run_id, request_id))
                return run_id
            row = db.execute("SELECT state,attempt_count FROM public.metrology_run WHERE id=%s FOR UPDATE", (run_id,)).fetchone()
            if row[0] == 'complete':
                db.execute("UPDATE public.metrology_redo_request SET state='complete',updated_at=now() WHERE id=%s", (request_id,))
                return None
            if row[1] >= 3:
                db.execute("UPDATE public.metrology_run SET state='permanent_failure',error_message=COALESCE(error_message,'Retry limit reached after interrupted run'),updated_at=now() WHERE id=%s", (run_id,))
                db.execute("UPDATE public.metrology_redo_request SET state='failed',error_message='Retry limit reached',updated_at=now() WHERE id=%s", (request_id,))
                return None
            db.execute("UPDATE public.metrology_run SET state='running',attempt_count=attempt_count+1,updated_at=now() WHERE id=%s", (run_id,))
            db.execute("UPDATE public.metrology_redo_request SET state='running',updated_at=now() WHERE id=%s", (request_id,))
            return run_id
        if db.execute("SELECT EXISTS(SELECT 1 FROM public.metrology_run WHERE source=%s AND fileset_id=%s AND state='complete')", (source, fileset_id)).fetchone()[0]:
            return None
        row = db.execute("SELECT id, state, attempt_count FROM public.metrology_run WHERE source=%s AND fileset_id=%s AND analysis_version=%s AND config_hash=%s AND generation=1 FOR UPDATE", (source, fileset_id, VERSION, CONFIG)).fetchone()
        if row is None:
            imported = datetime.fromtimestamp(imported_ms / 1000, timezone.utc) if imported_ms is not None else None
            return db.execute("INSERT INTO public.metrology_run(source,group_id,fileset_id,analysis_version,config_hash,state,attempt_count,imported_at) VALUES(%s,%s,%s,%s,%s,'running',1,%s) RETURNING id", (source, group_id, fileset_id, VERSION, CONFIG, imported)).fetchone()[0]
        run_id, state, attempts = row
        if state in ("complete", "permanent_failure"):
            return None
        if attempts >= 3:
            db.execute("UPDATE public.metrology_run SET state='permanent_failure',error_message=COALESCE(error_message,'Retry limit reached after interrupted run'),updated_at=now() WHERE id=%s", (run_id,))
            return None
        db.execute("UPDATE public.metrology_run SET state='running',attempt_count=attempt_count+1,updated_at=now() WHERE id=%s", (run_id,))
        return run_id


def save_results(db, run_id, outputs):
    with db.transaction():
        ordinal = 0
        for image_id, name, metadata, measurements, artifacts, decision in outputs:
            metadata = dict(metadata)
            # Detector diagnostics can contain NumPy scalar values.
            metadata["classification"] = json.loads(json.dumps(decision, default=lambda value: value.item() if hasattr(value, "item") else str(value)))
            for input_id in metadata.get("contributing_image_ids", [image_id]):
                db.execute("INSERT INTO public.metrology_run_input(run_id,image_id,ordinal,image_name,metadata) VALUES(%s,%s,%s,%s,%s) ON CONFLICT (run_id,image_id) DO NOTHING", (run_id, input_id, ordinal, name if input_id == image_id else None, Jsonb(metadata if input_id == image_id else {})))
                ordinal += 1
            microscope_name = str(metadata.get("Microscope", "")).strip()
            if not microscope_name:
                raise ValueError("Missing microscope annotation")
            microscope_id = db.execute("INSERT INTO public.metrology_microscope(name) VALUES(%s) ON CONFLICT(name) DO UPDATE SET name=EXCLUDED.name RETURNING id", (microscope_name,)).fetchone()[0]
            magnification = str(metadata.get("Lens Magnification", "")).strip()
            lens_id = None
            if magnification:
                na = positive_number(metadata, "Lens NA") if metadata.get("Lens NA") else None
                lens_id = db.execute("INSERT INTO public.metrology_lens(microscope_id,magnification,numerical_aperture) VALUES(%s,%s,%s) ON CONFLICT ON CONSTRAINT metrology_lens_identity DO UPDATE SET magnification=EXCLUDED.magnification RETURNING id", (microscope_id, magnification, na)).fetchone()[0]
            for key, category, metric, value, unit, status in measurements:
                db.execute("INSERT INTO public.metrology_measurement(run_id,microscope_id,lens_id,metric_key,category,measurement_type,value,unit,status,acquired_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id,metric_key) DO NOTHING", (run_id, microscope_id, lens_id, key, category, metric, value, unit, status, acquired_at(metadata)))
            for image_id, key, mimetype, payload in artifacts:
                artifact_key = f"{image_id}-{key}"
                db.execute("INSERT INTO public.metrology_artifact(run_id,artifact_key,image_id,mime_type,checksum,payload) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id,artifact_key) DO NOTHING", (run_id, artifact_key, image_id, mimetype, hashlib.sha256(payload).hexdigest(), payload))
        db.execute("UPDATE public.metrology_run SET state='analyzed',updated_at=now() WHERE id=%s", (run_id,))


def upload_artifacts(db, connection, run_id):
    rows = db.execute("SELECT id,image_id,artifact_key,mime_type,payload FROM public.metrology_artifact WHERE run_id=%s AND state <> 'linked' ORDER BY id", (run_id,)).fetchall()
    for artifact_id, image_id, key, mime, payload in rows:
        filename = f"metrology-run-{run_id}-{key}"
        annotation_id = attach(connection, image_id, filename, mime, bytes(payload))
        with db.transaction():
            db.execute("UPDATE public.metrology_artifact SET state='linked',annotation_id=%s WHERE id=%s", (annotation_id, artifact_id))
    with db.transaction():
        db.execute("UPDATE public.metrology_run SET state='complete',error_message=NULL,processed_at=now(),updated_at=now() WHERE id=%s", (run_id,))
        db.execute("UPDATE public.metrology_redo_request SET state='complete',error_message=NULL,updated_at=now() WHERE run_id=%s AND state='running'", (run_id,))


def run(limit):
    source = os.environ["OMERO_SOURCE"]
    group_id = int(os.environ["OMERO_METROLOGY_GROUP_ID"])
    max_bytes = int(os.getenv("METROLOGY_MAX_IMAGE_BYTES", str(1024 ** 3)))
    db = psycopg.connect(host=os.environ["PGHOST"], port=os.getenv("PGPORT", "5432"), dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], autocommit=True)
    connection = None
    try:
        if not db.execute("SELECT pg_try_advisory_lock(%s)", (730625103,)).fetchone()[0]:
            LOG.info("Another metrology processor is running")
            return 0
        if db.execute("SELECT max(version) FROM public.metrology_schema_version").fetchone()[0] != 6:
            raise RuntimeError("Schema version 6 is required")
        connection = connect()
        selected = failures = 0
        queued = {row[0] for row in db.execute("SELECT fileset_id FROM public.metrology_redo_request WHERE source=%s AND state IN ('pending','running')", (source,)).fetchall()}
        available = filesets(connection)
        available.sort(key=lambda item: item[0] not in queued)
        for fileset_id, imported, image_ids in available:
            if selected >= limit:
                break
            run_id = claim(db, source, group_id, fileset_id, imported)
            if run_id is None:
                continue
            selected += 1
            try:
                db.execute("UPDATE public.metrology_run SET source_image_ids=%s WHERE id=%s", (image_ids, run_id))
                if not db.execute("SELECT EXISTS(SELECT 1 FROM public.metrology_artifact WHERE run_id=%s)", (run_id,)).fetchone()[0]:
                    override_rows = db.execute("SELECT image_id,category FROM public.metrology_analysis_override WHERE source=%s AND image_id = ANY(%s)", (source, image_ids)).fetchall()
                    outputs = analyze_fileset(connection, image_ids, dict(override_rows), max_bytes)
                    save_results(db, run_id, outputs)
                upload_artifacts(db, connection, run_id)
                LOG.info("Completed fileset %s (run %s)", fileset_id, run_id)
            except Exception as exc:
                failures += 1
                LOG.exception("Fileset %s failed", fileset_id)
                with db.transaction():
                    db.execute("UPDATE public.metrology_run SET state=CASE WHEN attempt_count >= 3 THEN 'permanent_failure' ELSE 'retryable_failure' END,error_message=%s,updated_at=now() WHERE id=%s", (str(exc)[:2000], run_id))
                    db.execute("UPDATE public.metrology_redo_request SET state=CASE WHEN (SELECT attempt_count FROM public.metrology_run WHERE id=%s) >= 3 THEN 'failed' ELSE 'pending' END,error_message=%s,updated_at=now() WHERE run_id=%s AND state='running'", (run_id, str(exc)[:2000], run_id))
        LOG.info("Attempted %s filesets; %s failed", selected, failures)
        return 1 if failures else 0
    finally:
        if connection is not None:
            connection.close()
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return run(args.limit)


if __name__ == "__main__":
    sys.exit(main())
