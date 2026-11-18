import sys
import types
import unittest
from unittest.mock import patch

from metrology_processor.routing import analyze, validate_metadata


class RoutingTests(unittest.TestCase):
    def test_override_is_passed_to_core(self):
        calls = []
        core = types.ModuleType("METEOR_core.metrology")
        core.metrology_splitter = lambda image, name, metadata, **kw: calls.append(kw) or [{"status": "success"}]
        with patch.dict(sys.modules, {"METEOR_core": types.ModuleType("METEOR_core"), "METEOR_core.metrology": core}):
            analyze(None, "ambiguous", {}, "Psf_Measure")
        self.assertEqual(calls, [{"category_override": "Psf_Measure"}])

    def test_unknown_override_rejected(self):
        with self.assertRaises(ValueError):
            analyze(None, "x", {}, "not-an-analysis")

    def test_psf_requires_calibration(self):
        with self.assertRaisesRegex(ValueError, "Lens NA"):
            validate_metadata({"Physical pixel size X": 0.1, "Physical pixel size Y": 0.1, "Physical pixel size Z": 0.3, "Image Size Z": 5}, "Psf_Measure")


if __name__ == "__main__":
    unittest.main()
