from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from accounts.permissions import operational_access
from . import data, scoring


def _image_for_microscope(name):
    normalized = "".join(ch for ch in name.lower() if ch.isalnum())
    for key, image in (("lsm980", "LSM980.png"), ("lsm880", "LSM880.png"),
                       ("lsm710", "LSM710.png"), ("lsm700", "LSM700.png"),
                       ("elyra7", "ELYRA7.png"), ("observer", "Observer.png"),
                       ("imager", "Imager.png"), ("cd7", "CD7.png")):
        if key in normalized:
            return image
    return "Microscope.png"


def _omero_image_url(source, image_id):
    """Only use configured trusted server URLs, never annotation-provided URLs."""
    urls = getattr(settings, "DASHBOARD_METROLOGY_OMERO_URLS", {})
    base = urls.get(source, "")
    parsed = urlsplit(base)
    if not image_id or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    return f"{base.rstrip('/')}/webclient/?show=image-{int(image_id)}"


@require_GET
def home(request):
    if not operational_access(request.user):
        return HttpResponseForbidden("Staff access required.")
    try:
        rows = scoring.measurements()
        latest = scoring.latest_by_microscope(rows)
        microscopes = data.microscopes()
        for item in microscopes:
            item["image"] = _image_for_microscope(item["name"])
            item["latest_score"] = latest.get(item["id"])
        _, _, scores = scoring.aggregate(rows)
        score_history = [{"microscope_id": microscope, "day": str(day), "score": score}
                         for (microscope, day), score in sorted(scores.items())]
        chart_data = [{"id": item["id"], "name": item["name"], "url": reverse("metrology_microscope", args=[item["id"]])} for item in microscopes]
        return render(request, "dashboard_metrology/home.html", {"summary": data.summary(), "microscopes": microscopes, "score_history": score_history, "microscope_chart_data": chart_data})
    except DatabaseError:
        return HttpResponse("Metrology data is currently unavailable.", status=503)


@require_GET
def microscope(request, microscope_id):
    if not operational_access(request.user):
        return HttpResponseForbidden("Staff access required.")
    try:
        info = data.microscope(microscope_id)
        if info is None:
            return HttpResponseNotFound("Microscope not found.")
        lens_raw = request.GET.get("lens", "")
        lens_id = int(lens_raw) if len(lens_raw) <= 19 and lens_raw.isascii() and lens_raw.isdigit() and int(lens_raw) > 0 else None
        if lens_raw and lens_id is None:
            return HttpResponse("Invalid lens filter.", status=400)
        lens_list = data.lenses(microscope_id)
        if lens_id is not None and not any(lens["id"] == lens_id for lens in lens_list):
            return HttpResponseNotFound("Lens not found.")
        page_raw = request.GET.get("page", "1")
        if len(page_raw) > 6 or not page_raw.isascii() or not page_raw.isdigit() or not 1 <= int(page_raw) <= 100000:
            return HttpResponse("Invalid page.", status=400)
        page = int(page_raw)
        measurements, total = data.measurements(microscope_id, lens_id, page)
        scored = scoring.measurements(microscope_id)
        score_by_id = {row["id"]: row for row in scored}
        for item in measurements:
            item["omero_url"] = _omero_image_url(item["source"], item["image_id"])
            item["score"] = score_by_id.get(item["id"], {}).get("score")
            item["score_status"] = scoring.status(item["score"])
        categories, objectives, microscopes = scoring.aggregate(scored)
        lens_lookup = {lens["id"]: lens for lens in lens_list}
        scores = []
        for (mid, lens, day), value in objectives.items():
            if lens_id is not None and lens != lens_id:
                continue
            info_lens = lens_lookup.get(lens, {})
            scores.append({"level": "lens", "score_key": "Overall", "score": value,
                           "status": scoring.aggregate_status(value), "period_start": day,
                           "magnification": info_lens.get("magnification"), "immersion": info_lens.get("immersion")})
        for (mid, lens, category, day), value in categories.items():
            if lens_id is not None and lens != lens_id:
                continue
            info_lens = lens_lookup.get(lens, {})
            scores.append({"level": "category", "score_key": category, "score": value,
                           "status": scoring.aggregate_status(value), "period_start": day,
                           "magnification": info_lens.get("magnification"), "immersion": info_lens.get("immersion")})
        scores.sort(key=lambda row: row["period_start"], reverse=True)
        lens_history = [{"lens_id": lens, "day": str(day), "score": value}
                        for (_, lens, day), value in objectives.items()]
        category_history = [{"lens_id": lens, "category": category, "day": str(day), "score": value}
                            for (_, lens, category, day), value in categories.items()]
        return render(request, "dashboard_metrology/microscope.html", {
            "microscope": info, "lenses": lens_list, "lens_id": lens_id,
            "measurements": measurements, "scores": scores[:50],
            "lens_history": lens_history, "category_history": category_history,
            "total": total, "page": page, "previous": page - 1 if page > 1 else None,
            "next": page + 1 if page * 50 < total else None,
        })
    except DatabaseError:
        return HttpResponse("Metrology data is currently unavailable.", status=503)


@require_GET
def measurements(request):
    if not operational_access(request.user):
        return HttpResponseForbidden("Staff access required.")
    filters = {key: request.GET.get(key, '').strip()[:200] for key in ('microscope', 'lens', 'category', 'status', 'search')}
    for key in ('microscope', 'lens'):
        if filters[key] and (not filters[key].isascii() or not filters[key].isdigit() or len(filters[key]) > 18 or int(filters[key]) < 1):
            return HttpResponse("Invalid filter.", status=400)
    raw = request.GET.get('page', '1')
    if len(raw) > 6 or not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 100000:
        return HttpResponse("Invalid page.", status=400)
    page = int(raw)
    try:
        rows, total = data.all_measurements(filters, page)
        score_by_id = {row['id']: row['score'] for row in scoring.measurements()}
        for item in rows:
            item['omero_url'] = _omero_image_url(item['source'], item['image_id'])
            item['score'] = score_by_id.get(item['id'])
        query = request.GET.copy()
        query.pop('page', None)
        return render(request, 'dashboard_metrology/measurements.html', {
            'measurements': rows, 'filters': filters, 'options': data.filter_options(),
            'microscopes': data.microscopes(), 'total': total, 'page': page,
            'previous': page - 1 if page > 1 else None,
            'next': page + 1 if page * 50 < total else None, 'query': query.urlencode()})
    except DatabaseError:
        return HttpResponse("Metrology data is currently unavailable.", status=503)


@require_GET
def figures(request, microscope_id):
    if not operational_access(request.user):
        return JsonResponse({'error': 'Staff access required.'}, status=403)
    lens = request.GET.get('lens', '')
    category = request.GET.get('category', '')
    if not lens.isascii() or not lens.isdigit() or len(lens) > 18 or int(lens) < 1 or not category or len(category) > 200:
        return JsonResponse({'error': 'Invalid selection.'}, status=400)
    try:
        if not data.microscope(microscope_id) or not any(item['id'] == int(lens) for item in data.lenses(microscope_id)):
            return JsonResponse({'error': 'Not found.'}, status=404)
        items = data.figures(microscope_id, int(lens), category)
        for item in items:
            item['url'] = reverse('metrology_attachment', args=[item['id']])
        return JsonResponse({'figures': items})
    except DatabaseError:
        return JsonResponse({'error': 'Metrology data is currently unavailable.'}, status=503)


@require_GET
def attachment(request, artifact_id):
    if not operational_access(request.user):
        return HttpResponseForbidden('Staff access required.')
    try:
        item = data.figure_payload(artifact_id)
        if not item:
            return HttpResponseNotFound('Figure not found.')
        response = HttpResponse(bytes(item['payload']), content_type=item['mime_type'])
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=300'
        return response
    except DatabaseError:
        return HttpResponse('Metrology data is currently unavailable.', status=503)


@require_GET
def history(request, microscope_id):
    if not operational_access(request.user):
        return JsonResponse({"error": "Staff access required."}, status=403)
    try:
        if data.microscope(microscope_id) is None:
            return JsonResponse({"error": "Microscope not found."}, status=404)
        lens_raw = request.GET.get("lens", "")
        if lens_raw and (len(lens_raw) > 19 or not lens_raw.isascii() or not lens_raw.isdigit() or int(lens_raw) < 1):
            return JsonResponse({"error": "Invalid lens filter."}, status=400)
        lens_id = int(lens_raw) if lens_raw else None
        if lens_id is not None and not any(lens["id"] == lens_id for lens in data.lenses(microscope_id)):
            return JsonResponse({"error": "Lens not found."}, status=404)
        rows, truncated = data.history(microscope_id, lens_id)
        scored = {row["id"]: row["score"] for row in scoring.measurements(microscope_id)}
        for row in rows:
            row["score"] = scored.get(row["id"])
        return JsonResponse({"measurements": rows, "truncated": truncated})
    except DatabaseError:
        return JsonResponse({"error": "Metrology data is currently unavailable."}, status=503)


@require_GET
def failures(request):
    if not operational_access(request.user):
        return HttpResponseForbidden("Staff access required.")
    raw = request.GET.get("page", "1")
    if len(raw) > 6 or not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 100000:
        return HttpResponse("Invalid page.", status=400)
    page = int(raw)
    try:
        rows, total = data.failed_runs(page)
        return render(request, "dashboard_metrology/failures.html", {
            "failures": rows, "total": total, "page": page,
            "previous": page - 1 if page > 1 else None,
            "next": page + 1 if page * 50 < total else None,
        })
    except DatabaseError:
        return HttpResponse("Metrology data is currently unavailable.", status=503)
