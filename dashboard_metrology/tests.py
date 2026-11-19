from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from . import views
from .dashboard_module import module, overview_metrics


class ViewerTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.staff = SimpleNamespace(is_authenticated=True, is_active=True, role="staff")
        self.admin = SimpleNamespace(is_authenticated=True, is_active=True, role="admin")
        self.researcher = SimpleNamespace(is_authenticated=True, is_active=True, role="researcher")
        self.anonymous = SimpleNamespace(is_authenticated=False, is_active=False, role="")

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

    def test_direct_views_deny_non_staff(self):
        for user in (self.researcher, self.anonymous, SimpleNamespace(is_authenticated=True, is_active=False, role="staff")):
            self.assertEqual(views.home(self.request("/metrology/", user)).status_code, 403)
            self.assertEqual(views.microscope(self.request("/metrology/microscopes/1/", user), 1).status_code, 403)

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

    @patch("dashboard_metrology.views.data.summary", side_effect=DatabaseError)
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
