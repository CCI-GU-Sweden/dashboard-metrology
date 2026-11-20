from types import SimpleNamespace
from unittest.mock import patch
import json

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from datetime import datetime, timezone, timedelta

from . import views, scoring
from .overdue import is_overdue
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
        with patch("dashboard_metrology.dashboard_module.summary", return_value={"microscopes": 2, "measurements": 5, "failures": 1}), patch("dashboard_metrology.dashboard_module.microscopes", return_value=[]):
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

    @patch('dashboard_metrology.views.data.microscopes')
    @patch('dashboard_metrology.views.data.summary', return_value={'microscopes': 1, 'measurements': 1, 'failures': 0})
    def test_overdue_badge_is_in_addition_to_score(self, summary, microscopes):
        now = datetime(2026, 5, 15, 12, tzinfo=timezone.utc)
        microscopes.return_value = [{'id': 1, 'name': 'Test', 'lens_count': 1, 'measurement_count': 1,
                                   'last_measurement': now - timedelta(days=50)}]
        with patch('dashboard_metrology.overdue.timezone.now', return_value=now):
            response = views.home(self.request('/metrology/', self.staff))
        self.assertContains(response, 'Overdue')
        self.assertContains(response, 'Not scored yet')

    def test_direct_views_deny_non_staff(self):
        for user in (self.researcher, self.anonymous, SimpleNamespace(is_authenticated=True, is_active=False, role="staff")):
            self.assertEqual(views.home(self.request("/metrology/", user)).status_code, 403)
            self.assertEqual(views.microscope(self.request("/metrology/microscopes/1/", user), 1).status_code, 403)
            self.assertEqual(views.history(self.request("/metrology/microscopes/1/history/", user), 1).status_code, 403)
            self.assertEqual(views.failures(self.request("/metrology/review/", user)).status_code, 403)
            self.assertEqual(views.measurements(self.request("/metrology/measurements/", user)).status_code, 403)
            self.assertEqual(views.figures(self.request("/metrology/microscopes/1/figures/", user), 1).status_code, 403)
            self.assertEqual(views.attachment(self.request("/metrology/attachments/1/", user), 1).status_code, 403)

    @patch('dashboard_metrology.views.data.enqueue_redo', return_value='queued')
    def test_redo_requires_admin_post_and_queues_measurement(self, enqueue):
        self.assertEqual(views.redo(self.request('/metrology/measurements/4/redo/', self.admin), 4).status_code, 405)
        request = self.factory.post('/metrology/measurements/4/redo/')
        request.user = self.staff
        self.assertEqual(views.redo(request, 4).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        self.assertEqual(views.redo(request, 4).status_code, 302)
        enqueue.assert_called_once_with(4, 42)
        enqueue.return_value = 'not_found'
        self.assertEqual(views.redo(request, 99).status_code, 404)

    @patch('dashboard_metrology.views.data.enqueue_redo', return_value='already_queued')
    def test_redo_json_stays_on_page(self, enqueue):
        request = self.factory.post('/metrology/measurements/4/redo/', HTTP_ACCEPT='application/json')
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        response = views.redo(request, 4)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)['status'], 'already_queued')

    @patch('dashboard_metrology.views.data.ignore_measurement', return_value='ignored')
    def test_ignore_requires_admin_and_post(self, ignore):
        self.assertEqual(views.ignore_measurement(self.request('/metrology/measurements/4/ignore/', self.admin), 4).status_code, 405)
        request = self.factory.post('/metrology/measurements/4/ignore/')
        request.user = self.staff
        self.assertEqual(views.ignore_measurement(request, 4).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        self.assertEqual(json.loads(views.ignore_measurement(request, 4).content)['status'], 'ignored')
        ignore.assert_called_once_with(4, 42)

    @patch('dashboard_metrology.views.data.restore_measurement', return_value='restored')
    def test_restore_requires_admin(self, restore):
        request = self.factory.post('/metrology/measurements/4/restore/')
        request.user = self.staff
        self.assertEqual(views.restore_measurement(request, 4).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        self.assertEqual(json.loads(views.restore_measurement(request, 4).content)['status'], 'restored')
        restore.assert_called_once_with(4, 42)

    @patch('dashboard_metrology.views.data.score_details', return_value=[{'id': 5, 'artifact_id': 12, 'source': 'test', 'image_id': 567}])
    @patch('dashboard_metrology.views.data.lenses', return_value=[{'id': 2}])
    @patch('dashboard_metrology.views.data.microscope', return_value={'id': 1})
    def test_score_details_validate_and_restrict_actions(self, microscope, lenses, details):
        url='/metrology/microscopes/1/score-details/?lens=2&category=PSF&day=2026-01-01'
        response=views.score_details(self.request(url, self.staff), 1)
        result=json.loads(response.content)['measurements'][0]
        self.assertEqual(result['figure_url'], '/metrology/attachments/12/')
        self.assertNotIn('ignore_url', result)
        self.assertEqual(views.score_details(self.request(url, self.researcher), 1).status_code, 403)
        self.assertEqual(views.score_details(self.request('/?lens=2&category=PSF&day=wrong', self.staff), 1).status_code, 400)

    @patch('dashboard_metrology.views.data.redo_requests', return_value=[])
    def test_redo_queue_staff_access(self, requests):
        self.assertContains(views.redo_queue(self.request('/metrology/redo/', self.staff)), 'No REDO requests yet')
        self.assertEqual(views.redo_queue(self.request('/metrology/redo/', self.researcher)).status_code, 403)

    @patch('dashboard_metrology.views.data.enqueue_failed_redo', return_value='queued')
    def test_failed_redo_requires_admin_and_targets_run(self, enqueue):
        request = self.factory.post('/metrology/review/5/redo/')
        request.user = self.staff
        self.assertEqual(views.redo_failed(request, 5).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        self.assertEqual(views.redo_failed(request, 5).status_code, 302)
        enqueue.assert_called_once_with(5, 42)

    @patch('dashboard_metrology.views.data.save_threshold', return_value=True)
    def test_threshold_requires_admin_and_finite_ordered_bounds(self, save):
        request = self.factory.post('/metrology/thresholds/2/', {'expected':'1', 'lower':'0.5', 'upper':'2'})
        request.user = self.staff
        self.assertEqual(views.threshold_save(request, 2).status_code, 403)
        request.user = SimpleNamespace(is_authenticated=True, is_active=True, role='admin', id=42)
        self.assertEqual(views.threshold_save(request, 2).status_code, 302)
        save.assert_called_once_with(2, 42, 1.0, 0.5, 2.0)
        for values in ({'expected':'NaN','lower':'0','upper':'2'}, {'expected':'3','lower':'0','upper':'2'}):
            invalid = self.factory.post('/metrology/thresholds/2/', values)
            invalid.user = request.user
            self.assertEqual(views.threshold_save(invalid, 2).status_code, 400)

    @patch('dashboard_metrology.views.data.threshold_options', return_value=[])
    def test_threshold_page_staff_access(self, options):
        self.assertContains(views.thresholds(self.request('/metrology/thresholds/', self.staff)), 'No calibrated measurements')
        self.assertEqual(views.thresholds(self.request('/metrology/thresholds/', self.researcher)).status_code, 403)

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
    @patch("dashboard_metrology.views.data.lenses", return_value=[{"id": 2, "magnification": "40x", "numerical_aperture": 1.2, "immersion": "Water"}])
    @patch("dashboard_metrology.views.data.microscope", return_value={"id": 1, "name": "Test", "location": None})
    def test_microscope_filter_and_missing_scores(self, info, lenses, measurements, scores):
        response = views.microscope(self.request("/metrology/microscopes/1/?lens=2", self.staff), 1)
        self.assertContains(response, "No scores calculated yet")
        self.assertContains(response, "Water")
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


class OverdueTests(SimpleTestCase):
    def test_calendar_month_boundary_and_missing(self):
        now = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)
        cutoff = datetime(2026, 2, 28, 13, tzinfo=timezone.utc)
        self.assertTrue(is_overdue(cutoff - timedelta(seconds=1), now))
        self.assertFalse(is_overdue(cutoff, now))
        self.assertFalse(is_overdue(None, now))

    @patch('dashboard_metrology.dashboard_module.microscopes')
    @patch('dashboard_metrology.dashboard_module.summary', return_value={'microscopes': 3, 'measurements': 5, 'failures': 0})
    def test_overview_counts_only_overdue_microscopes(self, summary, microscopes):
        now = datetime(2026, 5, 15, 12, tzinfo=timezone.utc)
        microscopes.return_value = [{'last_measurement': now - timedelta(days=50)}, {'last_measurement': now}, {'last_measurement': None}]
        with patch('dashboard_metrology.overdue.timezone.now', return_value=now):
            values = {item['label']: item['value'] for item in overview_metrics(None)}
        self.assertEqual(values['Overdue microscopes'], '1')
