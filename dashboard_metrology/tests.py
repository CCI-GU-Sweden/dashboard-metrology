from types import SimpleNamespace
from unittest.mock import patch
import json

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from datetime import datetime, timezone

from . import views, scoring
from .dashboard_module import module, overview_metrics


class ViewerTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = SimpleNamespace(is_authenticated=True, is_active=True, role="staff")
        self.admin = SimpleNamespace(is_authenticated=True, is_active=True, role="admin")
        self.researcher = SimpleNamespace(is_authenticated=True, is_active=True, role="researcher")
        self.anonymous = SimpleNamespace(is_authenticated=False, is_active=False, role="")
        scoring = patch("dashboard_metrology.views.scoring.measurements", return_value=[])
        scoring.start()
        self.addCleanup(scoring.stop)

    def request(self, path, user):
        request = self.factory.get(path)
        request.user = user
        return request

    def test_descriptor_uses_staff_access(self):
        self.assertTrue(module.can_view(self.staff))
        self.assertTrue(module.can_view(self.admin))
        self.assertFalse(module.can_view(self.researcher))
        self.assertFalse(module.can_view(self.anonymous))
        with patch("dashboard_metrology.dashboard_module.summary", return_value={"microscopes": 2, "measurements": 5, "failures": 1}):
            self.assertEqual(overview_metrics(self.staff)[1]["value"], "5")

    @patch("dashboard_metrology.views.data.microscopes")
    @patch("dashboard_metrology.views.data.summary")
    @patch("dashboard_metrology.views.scoring.measurements")
    def test_home_renders_live_score_and_safe_icon(self, measures, summary, microscopes):
        day = datetime(2026, 1, 10, tzinfo=timezone.utc)
        measures.return_value = [{"microscope_id": 1, "lens_id": 2, "category": "PSF", "score": 0.8, "measured_at": day}]
        summary.return_value = {"microscopes": 1, "measurements": 1, "failures": 0}
        microscopes.return_value = [{"id": 1, "name": "LSM980", "location": None, "lens_count": 1, "measurement_count": 1, "last_measurement": day}]
        response = views.home(self.request("/metrology/", self.staff))
        self.assertContains(response, "80%")
        self.assertContains(response, "LSM980.png")
        self.assertContains(response, 'id="metrology-score-history"', html=False)

    def test_direct_views_deny_non_staff(self):
        for user in (self.researcher, self.anonymous, SimpleNamespace(is_authenticated=True, is_active=False, role="staff")):
            self.assertEqual(views.home(self.request("/metrology/", user)).status_code, 403)
            self.assertEqual(views.microscope(self.request("/metrology/microscopes/1/", user), 1).status_code, 403)
            self.assertEqual(views.history(self.request("/metrology/microscopes/1/history/", user), 1).status_code, 403)
            self.assertEqual(views.failures(self.request("/metrology/review/", user)).status_code, 403)
            self.assertEqual(views.measurements(self.request("/metrology/measurements/", user)).status_code, 403)
            self.assertEqual(views.figures(self.request("/metrology/microscopes/1/figures/", user), 1).status_code, 403)
            self.assertEqual(views.attachment(self.request("/metrology/attachments/1/", user), 1).status_code, 403)

    @patch("dashboard_metrology.views.data.figure_payload")
    def test_image_attachment_returns_safe_content_type_and_missing_is_404(self, payload):
        payload.return_value = {"payload": b"example", "mime_type": "image/png"}
        response = views.attachment(self.request("/metrology/attachments/1/", self.staff), 1)
        self.assertEqual(response.content, b"example")
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        payload.return_value = None
        self.assertEqual(views.attachment(self.request("/metrology/attachments/1/", self.staff), 1).status_code, 404)

    @patch("dashboard_metrology.views.data.figures", return_value=[{"id": 12, "image_id": 567, "artifact_key": "567-figure-0.png", "mime_type": "image/png"}])
    @patch("dashboard_metrology.views.data.lenses", return_value=[{"id": 2}])
    @patch("dashboard_metrology.views.data.microscope", return_value={"id": 1})
    def test_figures_validate_selection_and_return_local_urls(self, microscope, lenses, figures):
        response = views.figures(self.request('/metrology/microscopes/1/figures/?lens=2&category=PSF', self.staff), 1)
        self.assertEqual(json.loads(response.content)['figures'][0]['url'], '/metrology/attachments/12/')
        figures.assert_called_once_with(1, 2, 'PSF')
        self.assertEqual(views.figures(self.request('/metrology/microscopes/1/figures/?lens=3&category=PSF', self.staff), 1).status_code, 404)
        self.assertEqual(views.figures(self.request('/metrology/microscopes/1/figures/?lens=-1&category=PSF', self.staff), 1).status_code, 400)

    @patch('dashboard_metrology.views.data.microscopes', return_value=[])
    @patch('dashboard_metrology.views.data.filter_options', return_value={'lenses': [], 'categories': [], 'statuses': []})
    @patch('dashboard_metrology.views.data.all_measurements', return_value=([], 0))
    def test_measurements_filter_and_validation(self, measurements, options, microscopes):
        response = views.measurements(self.request('/metrology/measurements/?category=PSF&search=spot', self.staff))
        self.assertContains(response, 'No measurements match these filters')
        self.assertEqual(measurements.call_args.args[0]['category'], 'PSF')
        self.assertEqual(measurements.call_args.args[0]['search'], 'spot')
        self.assertEqual(views.measurements(self.request('/metrology/measurements/?lens=-1', self.staff)).status_code, 400)

    @patch("dashboard_metrology.views.data.microscopes")
    @patch("dashboard_metrology.views.data.summary")
    def test_home_escapes_names_and_supports_empty_state(self, summary, microscopes):
        summary.return_value = {"microscopes": 1, "measurements": 0, "failures": 0}
        microscopes.return_value = [{"id": 1, "name": "<script>", "location": None, "lens_count": 0, "measurement_count": 0, "last_measurement": None}]
        response = views.home(self.request("/metrology/", self.staff))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;", html=False)
        self.assertNotContains(response, "<script>", html=False)
        microscopes.return_value = []
        self.assertContains(views.home(self.request("/metrology/", self.staff)), "No microscope measurements")

    @patch("dashboard_metrology.views.data.microscopes", side_effect=DatabaseError)
    def test_database_unavailable_is_503(self, _):
        self.assertEqual(views.home(self.request("/metrology/", self.staff)).status_code, 503)

    @patch("dashboard_metrology.views.data.latest_scores", return_value=[])
    @patch("dashboard_metrology.views.data.measurements", return_value=([], 0))
    @patch("dashboard_metrology.views.data.lenses", return_value=[{"id": 2, "magnification": "40x", "numerical_aperture": 1.2}])
    @patch("dashboard_metrology.views.data.microscope", return_value={"id": 1, "name": "Test", "location": None})
    def test_microscope_filter_and_missing_scores(self, info, lenses, measurements, scores):
        response = views.microscope(self.request("/metrology/microscopes/1/?lens=2", self.staff), 1)
        self.assertContains(response, "No scores calculated yet")
        measurements.assert_called_once_with(1, 2, 1)
        self.assertEqual(views.microscope(self.request("/metrology/microscopes/1/?lens=9", self.staff), 1).status_code, 404)
        self.assertEqual(views.microscope(self.request("/metrology/microscopes/1/?page=-1", self.staff), 1).status_code, 400)

    @override_settings(DASHBOARD_METROLOGY_OMERO_URLS={"test": "https://omero.example"})
    def test_omero_url_requires_trusted_https_configuration(self):
        self.assertEqual(views._omero_image_url("test", 567), "https://omero.example/webclient/?show=image-567")
        self.assertEqual(views._omero_image_url("unknown", 567), "")
        with self.settings(DASHBOARD_METROLOGY_OMERO_URLS={"test": "https://evil.example@host.example"}):
            self.assertEqual(views._omero_image_url("test", 567), "")

    def test_registered_urls_resolve(self):
        self.assertEqual(reverse("metrology_home"), "/metrology/")
        self.assertEqual(reverse("metrology_microscope", args=[42]), "/metrology/microscopes/42/")
        self.assertEqual(reverse("metrology_history", args=[42]), "/metrology/microscopes/42/history/")
        self.assertEqual(reverse("metrology_failures"), "/metrology/review/")

    @patch("dashboard_metrology.views.data.history", return_value=([{"id": 1, "measurement_type": "PSF X", "value": 0.4}], False))
    @patch("dashboard_metrology.views.data.lenses", return_value=[{"id": 2}])
    @patch("dashboard_metrology.views.data.microscope", return_value={"id": 1})
    def test_history_filters_authorization_and_data(self, microscope, lenses, history):
        response = views.history(self.request("/metrology/microscopes/1/history/?lens=2", self.staff), 1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["measurements"][0]["value"], 0.4)
        history.assert_called_once_with(1, 2)
        self.assertEqual(views.history(self.request("/metrology/microscopes/1/history/?lens=8", self.staff), 1).status_code, 404)
        self.assertEqual(views.history(self.request("/metrology/microscopes/1/history/?lens=-1", self.staff), 1).status_code, 400)

    @patch("dashboard_metrology.views.data.failed_runs")
    def test_review_page_escapes_failure_and_handles_empty(self, failed_runs):
        failed_runs.return_value = ([{"fileset_id": 3, "source": "test", "state": "permanent_failure", "attempt_count": 3, "error_message": "<script>bad</script>", "updated_at": None}], 1)
        response = views.failures(self.request("/metrology/review/", self.staff))
        self.assertContains(response, "&lt;script&gt;bad&lt;/script&gt;", html=False)
        failed_runs.return_value = ([], 0)
        self.assertContains(views.failures(self.request("/metrology/review/", self.staff)), "No filesets need attention")

    @patch("dashboard_metrology.views.data.microscope", side_effect=DatabaseError)
    def test_history_unavailable(self, _):
        self.assertEqual(views.history(self.request("/metrology/microscopes/1/history/", self.staff), 1).status_code, 503)


class ScoreAggregationTests(SimpleTestCase):
    def test_category_medians_then_lens_and_microscope_means(self):
        day = datetime(2026, 1, 10, tzinfo=timezone.utc)
        rows = [
            {"microscope_id": 1, "lens_id": 1, "category": "PSF", "score": x, "measured_at": day}
            for x in (0.1, 0.8, 0.9)
        ] + [
            {"microscope_id": 1, "lens_id": 1, "category": "Field", "score": 0.4, "measured_at": day},
            {"microscope_id": 1, "lens_id": 2, "category": "PSF", "score": 1.0, "measured_at": day},
            {"microscope_id": 1, "lens_id": 2, "category": "PSF", "score": 0.0, "measured_at": None},
        ]
        categories, lenses, microscopes = scoring.aggregate(rows)
        self.assertAlmostEqual(categories[(1, 1, "PSF", day.date())], 0.8)
        self.assertAlmostEqual(lenses[(1, 1, day.date())], 0.6)
        self.assertAlmostEqual(microscopes[(1, day.date())], 0.8)
        self.assertEqual(scoring.latest_by_microscope(rows)[1]["status"], "success")

    def test_aggregate_status_boundaries(self):
        self.assertEqual(scoring.aggregate_status(0.7), "success")
        self.assertEqual(scoring.aggregate_status(0.4), "warning")
        self.assertEqual(scoring.aggregate_status(0.39), "critical")
