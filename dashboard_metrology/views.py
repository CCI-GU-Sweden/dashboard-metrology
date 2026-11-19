from urllib.parse import urlsplit

from django.conf import settings
from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from accounts.permissions import operational_access
from . import data


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
        return render(request, "dashboard_metrology/home.html", {"summary": data.summary(), "microscopes": data.microscopes()})
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
        for item in measurements:
            item["omero_url"] = _omero_image_url(item["source"], item["image_id"])
        return render(request, "dashboard_metrology/microscope.html", {
            "microscope": info, "lenses": lens_list, "lens_id": lens_id,
            "measurements": measurements, "scores": data.latest_scores(microscope_id),
            "total": total, "page": page, "previous": page - 1 if page > 1 else None,
            "next": page + 1 if page * 50 < total else None,
        })
    except DatabaseError:
        return HttpResponse("Metrology data is currently unavailable.", status=503)


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
