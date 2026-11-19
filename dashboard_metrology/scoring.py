"""Read-only, on-demand scoring adapted from METEOR-view.

PostgreSQL calculates baselines and individual scores. Aggregates are based on
the median score per lens/category/day, then the mean across categories and
lenses. References are recalculated from the current data on each request.
"""
from collections import defaultdict
from statistics import mean, median

from .data import _rows


def measurements(microscope_id=None):
    # Unit is included in the baseline key so different units cannot be mixed.
    # Explicit threshold rows have no unit field: use them only when the metric
    # has a single unit for that lens type.
    rows = _rows("""
        WITH base AS (
            SELECT m.id, m.microscope_id, m.lens_id, m.category, m.measurement_type,
                   COALESCE(m.unit,'') AS unit, m.value, m.status,
                   l.magnification, l.numerical_aperture,
                   COALESCE(m.acquired_at, r.imported_at) AS measured_at
            FROM metrology_measurement m
            JOIN metrology_run r ON r.id=m.run_id AND r.state='complete'
            JOIN metrology_lens l ON l.id=m.lens_id
            WHERE l.numerical_aperture IS NOT NULL
              AND lower(m.status) NOT IN ('ignore','ignored','error','failed','failure')
              AND m.value NOT IN ('NaN'::float8, 'Infinity'::float8, '-Infinity'::float8)
        ), stats AS (
            SELECT magnification,numerical_aperture,category,measurement_type,unit,
                   count(*) AS samples, percentile_cont(0.5) WITHIN GROUP (ORDER BY value) AS median
            FROM base GROUP BY magnification,numerical_aperture,category,measurement_type,unit
        ), unit_counts AS (
            SELECT magnification,numerical_aperture,category,measurement_type,count(*) AS units
            FROM stats GROUP BY magnification,numerical_aperture,category,measurement_type
        ), reference AS (
            SELECT b.*, s.samples, t.id AS threshold_id,
                   COALESCE(t.expected_value,s.median) AS expected,
                   COALESCE(t.lower_bound,s.median-abs(s.median)*0.1) AS lower_bound,
                   COALESCE(t.upper_bound,s.median+abs(s.median)*0.1) AS upper_bound
            FROM base b JOIN stats s USING(magnification,numerical_aperture,category,measurement_type,unit)
            JOIN unit_counts u USING(magnification,numerical_aperture,category,measurement_type)
            LEFT JOIN LATERAL (
                SELECT id,expected_value,lower_bound,upper_bound FROM metrology_threshold t
                WHERE t.magnification=b.magnification AND t.numerical_aperture=b.numerical_aperture
                  AND t.category=b.category AND t.measurement_type=b.measurement_type
                  AND t.lower_bound IS NOT NULL AND t.upper_bound IS NOT NULL AND u.units=1
                ORDER BY t.version DESC,t.id DESC LIMIT 1
            ) t ON true
            WHERE s.samples>=3 OR t.id IS NOT NULL
        ), normalized AS (
            SELECT *, greatest(lower_bound,least(expected,upper_bound)) AS target FROM reference
        )
        SELECT id,microscope_id,lens_id,category,measurement_type,unit,value,measured_at,
               samples,threshold_id,expected,lower_bound,upper_bound,
               CASE WHEN value BETWEEN lower_bound AND upper_bound THEN 1.0
                    WHEN value < lower_bound THEN power(greatest(0.0,least(1.0,
                       (value-(lower_bound-3.0*greatest(target-lower_bound,1e-12))) /
                       (3.0*greatest(target-lower_bound,1e-12)))),2)
                    ELSE power(greatest(0.0,least(1.0,
                       ((upper_bound+3.0*greatest(upper_bound-target,1e-12))-value) /
                       (3.0*greatest(upper_bound-target,1e-12)))),2) END AS score
        FROM normalized WHERE (%s::bigint IS NULL OR microscope_id=%s)
        ORDER BY measured_at NULLS LAST,id
    """, [microscope_id, microscope_id])
    return rows


def status(score):
    if score is None:
        return "unscored"
    if score >= 1:
        return "success"
    return "warning" if score >= 0.7 else "critical"


def aggregate_status(score):
    return "success" if score >= 0.7 else "warning" if score >= 0.4 else "critical"


def aggregate(rows):
    """Calculate daily category, objective and microscope score histories."""
    categories = defaultdict(list)
    for row in rows:
        if row["measured_at"] is None:
            continue
        day = row["measured_at"].date()
        key = (row["microscope_id"], row["lens_id"], row["category"], day)
        categories[key].append(float(row["score"]))
    category_scores = {key: median(values) for key, values in categories.items()}
    objectives = defaultdict(list)
    for (microscope, lens, category, day), value in category_scores.items():
        objectives[(microscope, lens, day)].append(value)
    lens_scores = {key: mean(values) for key, values in objectives.items()}
    microscopes = defaultdict(list)
    for (microscope, lens, day), value in lens_scores.items():
        microscopes[(microscope, day)].append(value)
    microscope_scores = {key: mean(values) for key, values in microscopes.items()}
    return category_scores, lens_scores, microscope_scores


def latest_by_microscope(rows):
    _, _, histories = aggregate(rows)
    result = {}
    for (microscope, day), value in histories.items():
        if microscope not in result or day > result[microscope]["day"]:
            result[microscope] = {"day": day, "score": value, "status": aggregate_status(value)}
    return result
