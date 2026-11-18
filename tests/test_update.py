import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("update_test_meteor_core", Path(__file__).resolve().parents[1] / "scripts" / "update_test_meteor_core.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def test_build_uses_exact_revision_and_patches_digest(self):
        calls = []
        revision = "a" * 40
        digest = "sha256:" + "b" * 64

        def fake_run(args):
            calls.append(args)
            if args[0] == "git":
                return revision + "\trefs/heads/main"
            if "start-build" in args:
                self.assertIn("--build-arg=METEOR_CORE_REF=" + revision, args)
                return "build.build.openshift.io/metrology-processor-5"
            if "get" in args:
                return json.dumps({"status": {"phase": "Complete", "output": {"to": {"imageDigest": digest}}}})
            return "patched"

        with patch.object(update, "run", side_effect=fake_run):
            update.main()
        self.assertEqual(calls[-1][0:3], ["oc", "-n", "core-omero-test"])
        self.assertIn("patch", calls[-1])
        self.assertIn(digest, calls[-1][-1])

    def test_failed_build_never_patches_cronjob(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            if args[0] == "git":
                return "a" * 40 + "\trefs/heads/main"
            if "start-build" in args:
                return "build.build.openshift.io/metrology-processor-5"
            return json.dumps({"status": {"phase": "Failed"}})

        with patch.object(update, "run", side_effect=fake_run):
            with self.assertRaises(RuntimeError):
                update.main()
        self.assertFalse(any("patch" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
