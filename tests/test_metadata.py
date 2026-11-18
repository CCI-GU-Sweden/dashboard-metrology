import sys
import types
import unittest
from unittest.mock import patch

from metrology_processor.metadata import extract_metadata, positive_number


class Map:
    def __init__(self, items):
        self.items = items

    def getValue(self):
        return self.items


class Image:
    def __init__(self, annotations):
        self.annotations = annotations

    def listAnnotations(self):
        return self.annotations

    def __getattr__(self, name):
        if name.startswith("getSize"):
            return lambda: {"X": 20, "Y": 10, "Z": 3, "C": 2, "T": 1}[name[-1]]
        raise AttributeError(name)


class MetadataTests(unittest.TestCase):
    def setUp(self):
        gateway = types.ModuleType("omero.gateway")
        gateway.MapAnnotationWrapper = Map
        self.modules = patch.dict(sys.modules, {"omero": types.ModuleType("omero"), "omero.gateway": gateway})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_annotations_and_authoritative_dimensions(self):
        result = extract_metadata(Image([Map([("Lens NA", "1.4"), ("Image Size C", "1")])]))
        self.assertEqual(result["Lens NA"], "1.4")
        self.assertEqual(result["Image Size C"], 2)
        self.assertEqual(result["axis_order"], "TCZYX")

    def test_conflicting_annotations_rejected(self):
        with self.assertRaisesRegex(ValueError, "Lens NA"):
            extract_metadata(Image([Map([("Lens NA", "1.4")]), Map([("Lens NA", "1.2")])]))

    def test_nonfinite_calibration_rejected(self):
        with self.assertRaises(ValueError):
            positive_number({"Lens NA": "nan"}, "Lens NA")


if __name__ == "__main__":
    unittest.main()
