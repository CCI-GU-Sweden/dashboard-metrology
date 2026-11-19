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
          (SELECT count(*) FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id
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
          AND EXISTS (SELECT 1 FROM metrology_run complete_run
                      WHERE complete_run.id=measurement.run_id AND complete_run.state='complete')
        LEFT JOIN metrology_run r ON r.id=measurement.run_id AND r.state='complete'
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
                FROM metrology_measurement lm JOIN metrology_run lr ON lr.id=lm.run_id AND lr.state='complete'
                JOIN metrology_run_input i ON i.run_id=lm.run_id
                  AND lm.metric_key LIKE i.image_id::text || ':%%'
                WHERE lm.lens_id=l.id) AS immersion
        FROM metrology_lens l
        LEFT JOIN metrology_measurement m ON m.lens_id=l.id
          AND EXISTS (SELECT 1 FROM metrology_run r WHERE r.id=m.run_id AND r.state='complete')
        WHERE l.microscope_id=%s GROUP BY l.id,l.magnification,l.numerical_aperture
        ORDER BY l.magnification,l.numerical_aperture,l.id
    """, [identifier])


def measurements(microscope_id, lens_id=None, page=1, page_size=50):
    params = [microscope_id]
    condition = "m.microscope_id=%s AND r.state='complete'"
    if lens_id is not None:
        condition += " AND m.lens_id=%s"
        params.append(lens_id)
    count = _rows(f"SELECT count(*) AS total FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id WHERE {condition}", params)[0]["total"]
    rows = _rows(f"""
        SELECT m.id,m.category,m.measurement_type,m.value,m.unit,m.score,m.status,
               COALESCE(m.acquired_at,r.imported_at) AS measured_at,
               m.acquired_at IS NOT NULL AS has_acquisition_time,
               l.magnification,l.numerical_aperture,r.fileset_id,r.source,m.acquired_at,r.imported_at,r.processed_at,
               (SELECT i.image_id FROM metrology_run_input i WHERE i.run_id=r.id
                AND m.metric_key LIKE CAST(i.image_id AS text) || ':%%' LIMIT 1) AS image_id
        FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id
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
    condition = "m.microscope_id=%s AND r.state='complete'"
    if lens_id is not None:
        condition += " AND m.lens_id=%s"
        params.append(lens_id)
    rows = _rows(f"""
        SELECT m.id, m.category, m.measurement_type, m.unit, m.value, m.status,
               m.lens_id, l.magnification, l.numerical_aperture,
               COALESCE(m.acquired_at,r.imported_at) AS measured_at,
               m.acquired_at IS NOT NULL AS has_acquisition_time
        FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id
        LEFT JOIN metrology_lens l ON l.id=m.lens_id
        WHERE {condition} AND COALESCE(m.acquired_at,r.imported_at) IS NOT NULL
        ORDER BY COALESCE(m.acquired_at,r.imported_at) DESC,m.id DESC
        LIMIT %s
    """, [*params, limit + 1])
    return list(reversed(rows[:limit])), len(rows) > limit


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
    base = " FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id JOIN metrology_microscope microscope ON microscope.id=m.microscope_id LEFT JOIN metrology_lens l ON l.id=m.lens_id "
    total = _rows("SELECT count(*) AS total" + base + " WHERE " + where, params)[0]['total']
    rows = _rows("""SELECT m.id,m.category,m.measurement_type,m.value,m.unit,m.status,m.acquired_at,
        r.imported_at,r.processed_at,r.source,r.fileset_id,microscope.name AS microscope_name,
        l.magnification,l.numerical_aperture,
        (SELECT nullif(trim(i.metadata->>'Lens Immersion'), '') FROM metrology_run_input i
         WHERE i.run_id=r.id AND m.metric_key LIKE i.image_id::text || ':%%' LIMIT 1) AS immersion,
        (SELECT i.image_id FROM metrology_run_input i WHERE i.run_id=r.id
         AND m.metric_key LIKE i.image_id::text || ':%%' LIMIT 1) AS image_id""" + base + " WHERE " + where +
        " ORDER BY COALESCE(m.acquired_at,r.imported_at) DESC NULLS LAST,m.id DESC LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size])
    return rows, total


def filter_options():
    return {
        'categories': _rows("SELECT DISTINCT category FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id WHERE r.state='complete' ORDER BY category"),
        'statuses': _rows("SELECT DISTINCT status FROM metrology_measurement m JOIN metrology_run r ON r.id=m.run_id WHERE r.state='complete' ORDER BY status"),
        'lenses': _rows("""SELECT l.id,l.magnification,l.numerical_aperture,m.name AS microscope_name,
            (SELECT string_agg(DISTINCT nullif(trim(i.metadata->>'Lens Immersion'), ''), ' / '
                               ORDER BY nullif(trim(i.metadata->>'Lens Immersion'), ''))
             FROM metrology_measurement lm JOIN metrology_run lr ON lr.id=lm.run_id AND lr.state='complete'
             JOIN metrology_run_input i ON i.run_id=lm.run_id AND lm.metric_key LIKE i.image_id::text || ':%%'
             WHERE lm.lens_id=l.id) AS immersion
            FROM metrology_lens l JOIN metrology_microscope m ON m.id=l.microscope_id ORDER BY m.name,l.magnification,l.id"""),
    }


def figures(microscope_id, lens_id, category):
    # Figure index is the analysis-result index in both artifact_key and metric_key.
    # Only show linked, browser-displayable figures associated with this category.
    return _rows("""SELECT DISTINCT a.id,a.image_id,a.artifact_key,a.mime_type
        FROM metrology_artifact a JOIN metrology_run r ON r.id=a.run_id AND r.state='complete'
        JOIN metrology_measurement m ON m.run_id=a.run_id AND m.microscope_id=%s
          AND m.lens_id=%s AND m.category=%s
          AND split_part(m.metric_key,':',1)=a.image_id::text
          AND a.artifact_key IN (a.image_id::text || '-figure-' || split_part(m.metric_key,':',2) || '.png',
                                 a.image_id::text || '-psf-' || split_part(m.metric_key,':',2) || '.gif')
        WHERE a.state='linked' AND a.mime_type IN ('image/png','image/jpeg','image/gif','image/webp')
          AND a.payload IS NOT NULL ORDER BY a.id DESC LIMIT 36""", [microscope_id, lens_id, category])


def figure_payload(artifact_id):
    rows = _rows("""SELECT a.payload,a.mime_type FROM metrology_artifact a
        JOIN metrology_run r ON r.id=a.run_id AND r.state='complete'
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
    rows = _rows("SELECT r.fileset_id,r.source,r.state,r.attempt_count,r.error_message,r.updated_at " + base +
                 " ORDER BY r.updated_at DESC,r.id DESC LIMIT %s OFFSET %s", [page_size, (page - 1) * page_size])
    return rows, total
