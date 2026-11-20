"""Exercise worker claim/recovery decisions without connecting to OMERO."""
from contextlib import nullcontext
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / 'metrology_processor'
package = types.ModuleType('redo_worker_test')
package.__path__ = [str(ROOT)]
analysis = types.ModuleType('redo_worker_test.analysis')
analysis.analyze_fileset = None
omero = types.ModuleType('redo_worker_test.omero_io')
omero.attach = omero.connect = omero.filesets = None
with patch.dict(sys.modules, {'redo_worker_test': package,
                             'redo_worker_test.analysis': analysis,
                             'redo_worker_test.omero_io': omero}):
    spec = importlib.util.spec_from_file_location('redo_worker_test.worker', ROOT / 'worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)


class Cursor:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class Database:
    def __init__(self, redo, previous=None):
        self.redo, self.previous = redo, previous
        self.calls = []
    def transaction(self): return nullcontext()
    def execute(self, sql, params):
        self.calls.append((sql, params))
        if sql.startswith('SELECT id,run_id FROM public.metrology_redo_request'): return Cursor(self.redo)
        if sql.startswith('SELECT COALESCE(max(generation)'): return Cursor((3,))
        if sql.startswith('INSERT INTO public.metrology_run'): return Cursor((71,))
        if sql.startswith('SELECT state,attempt_count'): return Cursor(self.previous)
        if sql.startswith('SELECT EXISTS'): return Cursor((True,))
        return Cursor(None)


class RedoClaimTests(unittest.TestCase):
    def test_redo_creates_new_generation_even_when_fileset_was_complete(self):
        db = Database((5, None))
        self.assertEqual(worker.claim(db, 'test', 1, 567, None), 71)
        insert = next(call for call in db.calls if call[0].startswith('INSERT INTO public.metrology_run'))
        self.assertEqual(insert[1][5], 3)
        self.assertFalse(any(sql.startswith('SELECT EXISTS') for sql, _ in db.calls))
        self.assertTrue(any("SET run_id=%s,state='running'" in sql for sql, _ in db.calls))

    def test_interrupted_redo_reuses_run_and_increments_attempt(self):
        db = Database((5, 71), ('retryable_failure', 1))
        self.assertEqual(worker.claim(db, 'test', 1, 567, None), 71)
        self.assertFalse(any(sql.startswith('INSERT INTO public.metrology_run') for sql, _ in db.calls))
        self.assertTrue(any('attempt_count=attempt_count+1' in sql for sql, _ in db.calls))

    def test_exhausted_attempts_fail_request_and_keep_old_run(self):
        db = Database((5, 71), ('running', 3))
        self.assertIsNone(worker.claim(db, 'test', 1, 567, None))
        self.assertTrue(any("state='failed'" in sql for sql, _ in db.calls))

    def test_completed_fileset_without_request_is_skipped(self):
        db = Database(None)
        self.assertIsNone(worker.claim(db, 'test', 1, 567, None))


if __name__ == '__main__': unittest.main()
