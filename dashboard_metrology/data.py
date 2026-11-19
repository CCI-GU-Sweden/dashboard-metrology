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
               count(m.id) AS measurement_count
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
