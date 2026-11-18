import unittest
from unittest.mock import patch

import numpy as np

from metrology_processor.omero_io import filesets, load_image
from metrology_processor.results import normalize_results


class Event:
    def __init__(self, value): self.value = value
    def getTime(self): return self.value


class Details:
    def __init__(self, value): self.value = value
    def getCreationEvent(self): return Event(self.value)


class Ref:
    def __init__(self, identifier): self.identifier = identifier
    def getId(self): return self.identifier


class Fileset(Ref):
    def __init__(self, identifier, created, images):
        super().__init__(identifier)
        self.created, self.images = created, images
    def getDetails(self): return Details(self.created)
    def copyImages(self): return [Ref(i) for i in self.images]


class ProcessorTests(unittest.TestCase):
    def test_filesets_sorted_by_import_time_and_id(self):
        connection = type("Conn", (), {"getObjects": lambda self, kind: [Fileset(1, 10, [4]), Fileset(3, 20, [9, 2]), Fileset(2, 20, [5])]})()
        self.assertEqual(filesets(connection), [(3, 20, [2, 9]), (2, 20, [5]), (1, 10, [4])])

    def test_load_checks_memory_before_allocation(self):
        pixels = type("Pixels", (), {"getPlanes": lambda self, coords: (np.zeros((4, 5), dtype=np.uint16) for _ in coords)})()
        image = type("Image", (), {"getPrimaryPixels": lambda self: pixels})()
        connection = type("Conn", (), {"getObject": lambda self, kind, identifier: image})()
        metadata = {f"Image Size {a}": n for a, n in zip("TCZYX", (1, 1, 2, 4, 5))}
        with patch("metrology_processor.omero_io.extract_metadata", return_value=metadata):
            with self.assertRaisesRegex(ValueError, "over configured"):
                load_image(connection, 3, 79)
            _, _, stack = load_image(connection, 3, 80)
        self.assertEqual(stack.shape, (1, 1, 2, 4, 5))

    def test_results_include_machine_readable_attachment(self):
        measurements, artifacts = normalize_results(5, [{"status": "success", "measurements": [{"name": "x", "category": "PSF", "value": 0.5, "unit": "um"}]}])
        self.assertEqual(measurements[0][3], 0.5)
        self.assertEqual(artifacts[0][1], "measurements.json")

    def test_failed_analysis_does_not_create_success(self):
        with self.assertRaises(ValueError):
            normalize_results(5, [{"status": "error", "measurements": []}])

    def test_psf_extras_are_encoded(self):
        result = {"status": "success", "measurements": [{"name": "x", "category": "PSF", "value": 1}],
                  "tiff": {"image": np.ones((2, 4, 4)), "upscaled_pixel_size": {"X": 0.1, "Y": 0.1, "Z": 0.3}},
                  "gif": {"frames": np.ones((2, 2, 4, 4))}}
        _, artifacts = normalize_results(5, [result])
        self.assertEqual({artifact[2] for artifact in artifacts}, {"image/tiff", "image/gif", "application/json"})


if __name__ == "__main__": unittest.main()
