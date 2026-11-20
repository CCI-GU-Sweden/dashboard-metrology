"""Read-only access to the processor-owned PostgreSQL schema."""
from django.db import connection


def _rows(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def summary():
    return _rows("""
        SELECT (SELECT count(*) FROM metrology_microscope) AS microscopes,
          (SELECT count(*) FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
           WHERE r.state='complete') AS measurements,
          (SELECT count(*) FROM metrology_run r WHERE r.state IN ('retryable_failure','permanent_failure')
           AND NOT EXISTS (SELECT 1 FROM metrology_run done WHERE done.source=r.source
               AND done.fileset_id=r.fileset_id AND done.state='complete')
           AND NOT EXISTS (SELECT 1 FROM metrology_run newer WHERE newer.source=r.source
               AND newer.fileset_id=r.fileset_id AND newer.state IN ('retryable_failure','permanent_failure') AND newer.id>r.id)) AS failures
    """)[0]


def microscopes():
    return _rows("""
        SELECT m.id, m.name, m.location, count(DISTINCT l.id) AS lens_count,
               count(DISTINCT measurement.id) AS measurement_count,
               max(COALESCE(measurement.acquired_at, r.imported_at)) AS last_measurement
        FROM metrology_microscope m
        LEFT JOIN metrology_lens l ON l.microscope_id=m.id
        LEFT JOIN metrology_measurement measurement ON measurement.microscope_id=m.id
          AND EXISTS (SELECT 1 FROM metrology_current_run complete_run
                      WHERE complete_run.id=measurement.run_id AND complete_run.state='complete')
        LEFT JOIN metrology_current_run r ON r.id=measurement.run_id AND r.state='complete'
        GROUP BY m.id, m.name, m.location ORDER BY m.name, m.id
    """)


def microscope(identifier):
    rows = _rows("SELECT id,name,location FROM metrology_microscope WHERE id=%s", [identifier])
    return rows[0] if rows else None


def lenses(identifier):
    return _rows("""
        SELECT l.id,l.magnification,l.numerical_aperture,
               count(m.id) AS measurement_count,
               (SELECT string_agg(DISTINCT nullif(trim(i.metadata->>'Lens Immersion'), ''), ' / '
                                  ORDER BY nullif(trim(i.metadata->>'Lens Immersion'), ''))
                FROM metrology_measurement lm JOIN metrology_current_run lr ON lr.id=lm.run_id AND lr.state='complete'
                JOIN metrology_run_input i ON i.run_id=lm.run_id
                  AND lm.metric_key LIKE i.image_id::text || ':%%'
                WHERE lm.lens_id=l.id) AS immersion
        FROM metrology_lens l
        LEFT JOIN metrology_measurement m ON m.lens_id=l.id
          AND EXISTS (SELECT 1 FROM metrology_current_run r WHERE r.id=m.run_id AND r.state='complete')
        WHERE l.microscope_id=%s GROUP BY l.id,l.magnification,l.numerical_aperture
        ORDER BY l.magnification,l.numerical_aperture,l.id
    """, [identifier])


def measurements(microscope_id, lens_id=None, page=1, page_size=50):
    params = [microscope_id]
    condition = "m.microscope_id=%s AND r.state='complete'"
    if lens_id is not None:
        condition += " AND m.lens_id=%s"
        params.append(lens_id)
    count = _rows(f"SELECT count(*) AS total FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id WHERE {condition}", params)[0]["total"]
    rows = _rows(f"""
        SELECT m.id,m.category,m.measurement_type,m.value,m.unit,m.score,m.status,
               COALESCE(m.acquired_at,r.imported_at) AS measured_at,
               m.acquired_at IS NOT NULL AS has_acquisition_time,
               l.magnification,l.numerical_aperture,r.fileset_id,r.source,m.acquired_at,r.imported_at,r.processed_at,
               (SELECT i.image_id FROM metrology_run_input i WHERE i.run_id=r.id
                AND m.metric_key LIKE CAST(i.image_id AS text) || ':%%' LIMIT 1) AS image_id
        FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
        LEFT JOIN metrology_lens l ON l.id=m.lens_id
        WHERE {condition}
        ORDER BY COALESCE(m.acquired_at,r.imported_at) DESC NULLS LAST, m.id DESC
        LIMIT %s OFFSET %s
    """, [*params, page_size, (page - 1) * page_size])
    return rows, count


def latest_scores(microscope_id):
    return _rows("""
        SELECT s.level,s.score_key,s.score,s.status,s.period_start,
               l.magnification,l.numerical_aperture
        FROM metrology_score s LEFT JOIN metrology_lens l ON l.id=s.lens_id
        WHERE s.microscope_id=%s ORDER BY s.period_start DESC,s.id DESC LIMIT 50
    """, [microscope_id])


def history(microscope_id, lens_id=None, limit=5000):
    params = [microscope_id]
    condition = "m.microscope_id=%s AND r.state='complete' AND lower(m.status) NOT IN ('ignore','ignored')"
    if lens_id is not None:
        condition += " AND m.lens_id=%s"
        params.append(lens_id)
    rows = _rows(f"""
        SELECT m.id, m.category, m.measurement_type, m.unit, m.value, m.status,
               m.lens_id, l.magnification, l.numerical_aperture,
               COALESCE(m.acquired_at,r.imported_at) AS measured_at,
               m.acquired_at IS NOT NULL AS has_acquisition_time
        FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
        LEFT JOIN metrology_lens l ON l.id=m.lens_id
        WHERE {condition} AND COALESCE(m.acquired_at,r.imported_at) IS NOT NULL
        ORDER BY COALESCE(m.acquired_at,r.imported_at) DESC,m.id DESC
        LIMIT %s
    """, [*params, limit + 1])
    return list(reversed(rows[:limit])), len(rows) > limit


def score_details(microscope_id, lens_id, category, day):
    return _rows("""SELECT m.id,m.run_id,m.metric_key,m.measurement_type,m.value,m.unit,m.status,
        COALESCE(m.acquired_at,r.imported_at) AS measured_at,r.fileset_id,r.source,
        i.image_id,a.id AS artifact_id,
        (SELECT q.state FROM metrology_redo_request q WHERE q.source=r.source AND q.fileset_id=r.fileset_id
         ORDER BY q.id DESC LIMIT 1) AS redo_state
        FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
        LEFT JOIN LATERAL (SELECT image_id FROM metrology_run_input i WHERE i.run_id=r.id
             AND m.metric_key LIKE i.image_id::text || ':%%' LIMIT 1) i ON true
        LEFT JOIN LATERAL (SELECT id FROM metrology_artifact a WHERE a.run_id=r.id AND a.image_id=i.image_id
             AND a.state='linked' AND a.payload IS NOT NULL
             AND a.artifact_key IN (i.image_id::text || '-figure-' || split_part(m.metric_key,':',2) || '.png',
                                    i.image_id::text || '-psf-' || split_part(m.metric_key,':',2) || '.gif')
             AND a.mime_type IN ('image/png','image/jpeg','image/gif','image/webp')
             ORDER BY CASE WHEN a.mime_type='image/png' THEN 0 ELSE 1 END,a.id LIMIT 1) a ON true
        WHERE m.microscope_id=%s AND m.lens_id=%s AND m.category=%s
          AND (COALESCE(m.acquired_at,r.imported_at) AT TIME ZONE 'UTC')::date=%s
        ORDER BY measured_at,m.id""", [microscope_id, lens_id, category, day])


def ignore_measurement(measurement_id, actor_id):
    from django.db import transaction
    import json
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("""SELECT m.status FROM metrology_measurement m
                JOIN metrology_current_run r ON r.id=m.run_id WHERE m.id=%s FOR UPDATE OF m""", [measurement_id])
            row = cursor.fetchone()
            if not row:
                return 'not_found'
            if row[0].lower() in ('ignore', 'ignored'):
                return 'already_ignored'
            cursor.execute("UPDATE metrology_measurement SET status='ignored' WHERE id=%s", [measurement_id])
            cursor.execute("INSERT INTO metrology_action(measurement_id,action,actor_user_id,details) VALUES(%s,'ignore',%s,%s::jsonb)",
                           [measurement_id, actor_id, json.dumps({'previous_status': row[0]})])
    return 'ignored'


def restore_measurement(measurement_id, actor_id):
    from django.db import transaction
    import json
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("""SELECT m.status,m.metric_key,r.source,r.fileset_id FROM metrology_measurement m
                JOIN metrology_current_run r ON r.id=m.run_id WHERE m.id=%s FOR UPDATE OF m""", [measurement_id])
            row = cursor.fetchone()
            if not row:
                return 'not_found'
            if row[0].lower() not in ('ignore', 'ignored'):
                return 'already_active'
            cursor.execute("""SELECT a.details->>'previous_status' FROM metrology_action a
                JOIN metrology_measurement old ON old.id=a.measurement_id JOIN metrology_run r ON r.id=old.run_id
                WHERE a.action='ignore' AND old.metric_key=%s AND r.source=%s AND r.fileset_id=%s
                ORDER BY a.id DESC LIMIT 1""", [row[1], row[2], row[3]])
            previous = cursor.fetchone()
            if not previous or not previous[0] or previous[0].lower() in ('ignore', 'ignored'):
                return 'no_previous_status'
            cursor.execute("UPDATE metrology_measurement SET status=%s WHERE id=%s", [previous[0], measurement_id])
            cursor.execute("INSERT INTO metrology_action(measurement_id,action,actor_user_id,details) VALUES(%s,'restore',%s,%s::jsonb)",
                           [measurement_id, actor_id, json.dumps({'restored_status': previous[0]})])
    return 'restored'


def all_measurements(filters, page=1, page_size=50):
    conditions = ["r.state='complete'"]
    params = []
    for name, column in (("microscope", "m.microscope_id"), ("lens", "m.lens_id"),
                         ("category", "m.category"), ("status", "m.status")):
        if filters.get(name):
            conditions.append(f"{column}=%s")
            params.append(filters[name])
    if filters.get("search"):
        conditions.append("(m.measurement_type ILIKE %s OR microscope.name ILIKE %s)")
        term = '%' + filters['search'] + '%'
        params.extend([term, term])
    where = " AND ".join(conditions)
    base = " FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id JOIN metrology_microscope microscope ON microscope.id=m.microscope_id LEFT JOIN metrology_lens l ON l.id=m.lens_id "
    total = _rows("SELECT count(*) AS total" + base + " WHERE " + where, params)[0]['total']
    rows = _rows("""SELECT m.id,m.category,m.measurement_type,m.value,m.unit,m.status,m.acquired_at,
        r.imported_at,r.processed_at,r.source,r.fileset_id,microscope.name AS microscope_name,
        l.magnification,l.numerical_aperture,
        (SELECT q.state FROM metrology_redo_request q WHERE q.source=r.source AND q.fileset_id=r.fileset_id
         ORDER BY q.requested_at DESC,q.id DESC LIMIT 1) AS redo_state,
        (SELECT nullif(trim(i.metadata->>'Lens Immersion'), '') FROM metrology_run_input i
         WHERE i.run_id=r.id AND m.metric_key LIKE i.image_id::text || ':%%' LIMIT 1) AS immersion,
        (SELECT i.image_id FROM metrology_run_input i WHERE i.run_id=r.id
         AND m.metric_key LIKE i.image_id::text || ':%%' LIMIT 1) AS image_id""" + base + " WHERE " + where +
        " ORDER BY COALESCE(m.acquired_at,r.imported_at) DESC NULLS LAST,m.id DESC LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size])
    return rows, total


def enqueue_redo(measurement_id, actor_id):
    rows = _rows("""INSERT INTO metrology_redo_request(source,fileset_id,measurement_id,requested_by,requested_run_id)
        SELECT r.source,r.fileset_id,m.id,%s,r.id FROM metrology_measurement m
        JOIN metrology_current_run r ON r.id=m.run_id WHERE m.id=%s
        ON CONFLICT DO NOTHING RETURNING id""", [actor_id, measurement_id])
    if rows:
        return 'queued'
    exists = _rows("""SELECT EXISTS(SELECT 1 FROM metrology_measurement m
        JOIN metrology_current_run r ON r.id=m.run_id WHERE m.id=%s) AS present""", [measurement_id])[0]['present']
    return 'already_queued' if exists else 'not_found'


def enqueue_failed_redo(run_id, actor_id):
    rows = _rows("""INSERT INTO metrology_redo_request(source,fileset_id,measurement_id,requested_by,requested_run_id)
        SELECT r.source,r.fileset_id,NULL,%s,r.id FROM metrology_run r
        WHERE r.id=%s AND r.state IN ('retryable_failure','permanent_failure')
          AND NOT EXISTS (SELECT 1 FROM metrology_current_run done WHERE done.source=r.source AND done.fileset_id=r.fileset_id)
          AND NOT EXISTS (SELECT 1 FROM metrology_run newer WHERE newer.source=r.source AND newer.fileset_id=r.fileset_id
                          AND newer.id>r.id AND newer.state IN ('retryable_failure','permanent_failure'))
        ON CONFLICT DO NOTHING RETURNING id""", [actor_id, run_id])
    if rows:
        return 'queued'
    exists = _rows("""SELECT EXISTS(SELECT 1 FROM metrology_run r WHERE r.id=%s
       AND r.state IN ('retryable_failure','permanent_failure') AND NOT EXISTS
       (SELECT 1 FROM metrology_current_run done WHERE done.source=r.source AND done.fileset_id=r.fileset_id)
       AND NOT EXISTS (SELECT 1 FROM metrology_run newer WHERE newer.source=r.source AND newer.fileset_id=r.fileset_id
                       AND newer.id>r.id AND newer.state IN ('retryable_failure','permanent_failure'))) AS present""", [run_id])[0]['present']
    return 'already_queued' if exists else 'not_found'


def threshold_options():
    return _rows("""WITH metrics AS (
        SELECT m.id,m.category,m.measurement_type,COALESCE(m.unit,'') AS unit,m.value,
               l.magnification,l.numerical_aperture
        FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
        JOIN metrology_lens l ON l.id=m.lens_id
        WHERE l.numerical_aperture IS NOT NULL
          AND lower(m.status) NOT IN ('ignore','ignored','error','failed','failure')
          AND m.value NOT IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8)
    ), grouped AS (
      SELECT min(id) AS measurement_id,category,measurement_type,unit,magnification,numerical_aperture,
             count(*) AS samples,percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS median
      FROM metrics GROUP BY category,measurement_type,unit,magnification,numerical_aperture
    ), units AS (
      SELECT category,measurement_type,magnification,numerical_aperture,count(*) AS unit_count
      FROM grouped GROUP BY category,measurement_type,magnification,numerical_aperture
    )
    SELECT g.*,t.id AS threshold_id,t.expected_value,t.lower_bound,t.upper_bound,t.version,t.created_by,t.created_at
    FROM grouped g JOIN units u USING(category,measurement_type,magnification,numerical_aperture)
    LEFT JOIN LATERAL (SELECT * FROM metrology_threshold t WHERE t.category=g.category
      AND t.measurement_type=g.measurement_type AND t.magnification=g.magnification
      AND t.numerical_aperture=g.numerical_aperture AND t.lower_bound IS NOT NULL AND t.upper_bound IS NOT NULL
      AND (t.unit=g.unit OR (t.unit IS NULL AND u.unit_count=1))
      ORDER BY (t.unit IS NOT NULL) DESC,t.version DESC,t.id DESC LIMIT 1) t ON true
    ORDER BY g.category,g.measurement_type,g.magnification,g.numerical_aperture,g.unit""")


def save_threshold(measurement_id, actor_id, expected, lower, upper):
    from django.db import transaction
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("""SELECT m.category,m.measurement_type,l.magnification,l.numerical_aperture,COALESCE(m.unit,'')
                FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id
                JOIN metrology_lens l ON l.id=m.lens_id
                WHERE m.id=%s AND l.numerical_aperture IS NOT NULL
                AND lower(m.status) NOT IN ('ignore','ignored','error','failed','failure')""", [measurement_id])
            key = cursor.fetchone()
            if not key:
                return False
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(concat_ws('|',%s,%s,%s,%s::text,%s),0))", key)
            cursor.execute("""INSERT INTO metrology_threshold(category,measurement_type,magnification,numerical_aperture,unit,
                expected_value,lower_bound,upper_bound,version,created_by)
                SELECT %s,%s,%s,%s,%s,%s,%s,%s,COALESCE(max(version),0)+1,%s FROM metrology_threshold
                WHERE category=%s AND measurement_type=%s AND magnification=%s AND numerical_aperture=%s AND unit=%s""",
                [*key, expected, lower, upper, actor_id, *key])
    return True


def redo_requests(limit=100):
    return _rows("""SELECT q.id,q.source,q.fileset_id,q.state,q.requested_by,q.requested_at,
        q.updated_at,q.error_message,q.run_id,r.attempt_count
        FROM metrology_redo_request q LEFT JOIN metrology_run r ON r.id=q.run_id
        ORDER BY q.requested_at DESC,q.id DESC LIMIT %s""", [limit])


def filter_options():
    return {
        'categories': _rows("SELECT DISTINCT category FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id WHERE r.state='complete' ORDER BY category"),
        'statuses': _rows("SELECT DISTINCT status FROM metrology_measurement m JOIN metrology_current_run r ON r.id=m.run_id WHERE r.state='complete' ORDER BY status"),
        'lenses': _rows("""SELECT l.id,l.magnification,l.numerical_aperture,m.name AS microscope_name,
            (SELECT string_agg(DISTINCT nullif(trim(i.metadata->>'Lens Immersion'), ''), ' / '
                               ORDER BY nullif(trim(i.metadata->>'Lens Immersion'), ''))
             FROM metrology_measurement lm JOIN metrology_current_run lr ON lr.id=lm.run_id AND lr.state='complete'
             JOIN metrology_run_input i ON i.run_id=lm.run_id AND lm.metric_key LIKE i.image_id::text || ':%%'
             WHERE lm.lens_id=l.id) AS immersion
            FROM metrology_lens l JOIN metrology_microscope m ON m.id=l.microscope_id ORDER BY m.name,l.magnification,l.id"""),
    }


def figures(microscope_id, lens_id, category):
    # Figure index is the analysis-result index in both artifact_key and metric_key.
    # Only show linked, browser-displayable figures associated with this category.
    return _rows("""SELECT DISTINCT a.id,a.image_id,a.artifact_key,a.mime_type
        FROM metrology_artifact a JOIN metrology_current_run r ON r.id=a.run_id AND r.state='complete'
        JOIN metrology_measurement m ON m.run_id=a.run_id AND m.microscope_id=%s
          AND m.lens_id=%s AND m.category=%s
          AND split_part(m.metric_key,':',1)=a.image_id::text
          AND a.artifact_key IN (a.image_id::text || '-figure-' || split_part(m.metric_key,':',2) || '.png',
                                 a.image_id::text || '-psf-' || split_part(m.metric_key,':',2) || '.gif')
        WHERE a.state='linked' AND a.mime_type IN ('image/png','image/jpeg','image/gif','image/webp')
          AND a.payload IS NOT NULL ORDER BY a.id DESC LIMIT 36""", [microscope_id, lens_id, category])


def figure_payload(artifact_id):
    rows = _rows("""SELECT a.payload,a.mime_type FROM metrology_artifact a
        JOIN metrology_current_run r ON r.id=a.run_id AND r.state='complete'
        WHERE a.id=%s AND a.state='linked' AND a.payload IS NOT NULL
        AND a.mime_type IN ('image/png','image/jpeg','image/gif','image/webp')""", [artifact_id])
    return rows[0] if rows else None


def failed_runs(page=1, page_size=50):
    # Present the most recent failure per source/fileset; hide superseded failures.
    base = """
        FROM metrology_run r
        WHERE r.state IN ('retryable_failure','permanent_failure')
          AND NOT EXISTS (SELECT 1 FROM metrology_run done WHERE done.source=r.source
                          AND done.fileset_id=r.fileset_id AND done.state='complete')
          AND NOT EXISTS (SELECT 1 FROM metrology_run newer WHERE newer.source=r.source
                          AND newer.fileset_id=r.fileset_id
                          AND newer.state IN ('retryable_failure','permanent_failure') AND newer.id>r.id)
    """
    total = _rows("SELECT count(*) AS total " + base)[0]["total"]
    rows = _rows("SELECT r.id,r.fileset_id,r.source,r.state,r.attempt_count,r.error_message,r.updated_at,r.source_image_ids, (SELECT q.state FROM metrology_redo_request q WHERE q.source=r.source AND q.fileset_id=r.fileset_id ORDER BY q.id DESC LIMIT 1) AS redo_state " + base +
                 " ORDER BY r.updated_at DESC,r.id DESC LIMIT %s OFFSET %s", [page_size, (page - 1) * page_size])
    return rows, total
