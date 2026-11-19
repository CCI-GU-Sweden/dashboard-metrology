"""Verify PostgreSQL scoring against isolated temporary tables; no persistent data."""
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1] / "dashboard_metrology"
source = json.dumps({name: (root / f"{name}.py").read_text(encoding="utf-8") for name in ("data", "scoring")})
code = '''import os, sys, json, types
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django
django.setup()
from django.db import connection, transaction
source = json.load(sys.stdin)
package = types.ModuleType("phase3_fixtures")
package.__path__ = []
sys.modules[package.__name__] = package
for name in ("data", "scoring"):
    module = types.ModuleType("phase3_fixtures." + name)
    module.__package__ = "phase3_fixtures"
    sys.modules[module.__name__] = module
    exec(compile(source[name], name + ".py", "exec"), module.__dict__)
s = sys.modules["phase3_fixtures.scoring"]
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TEMP TABLE metrology_run (id bigint, state text, imported_at timestamptz) ON COMMIT DROP")
        cursor.execute("CREATE TEMP TABLE metrology_lens (id bigint, magnification text, numerical_aperture float8) ON COMMIT DROP")
        cursor.execute("CREATE TEMP TABLE metrology_measurement (id bigint,run_id bigint,microscope_id bigint,lens_id bigint,category text,measurement_type text,unit text,value float8,status text,acquired_at timestamptz) ON COMMIT DROP")
        cursor.execute("CREATE TEMP TABLE metrology_threshold (id bigint, magnification text,numerical_aperture float8,category text,measurement_type text,expected_value float8,lower_bound float8,upper_bound float8,version int) ON COMMIT DROP")
        cursor.execute("INSERT INTO metrology_run VALUES (1,'complete','2026-01-01T00:00:00Z')")
        cursor.execute("INSERT INTO metrology_lens VALUES (1,'40x',1.2)")
        cursor.execute("INSERT INTO metrology_measurement VALUES (1,1,1,1,'A','derived','um',90,'success',NULL),(2,1,1,1,'A','derived','um',100,'success',NULL),(3,1,1,1,'A','derived','um',110,'success',NULL),(4,1,1,1,'A','explicit','um',120,'success',NULL),(5,1,1,1,'A','insufficient','um',10,'success',NULL),(6,1,1,1,'A','derived','nm',500,'success',NULL)")
        cursor.execute("INSERT INTO metrology_threshold VALUES (1,'40x',1.2,'A','explicit',100,90,110,1)")
    rows = {row["id"]: row for row in s.measurements()}
    assert set(rows) == {1,2,3,4}, set(rows)
    assert all(abs(rows[i]["score"] - 1.0) < 1e-10 for i in (1,2,3))
    assert abs(rows[4]["score"] - (2/3)**2) < 1e-10
    assert rows[4]["threshold_id"] == 1
    print("Derived and explicit baselines, scoring, missing samples and unit isolation passed")
'''
result = subprocess.run(["oc", "-n", "core-omero-test", "exec", "-i", "deploy/dashboard-django", "--", "python", "-c", code], input=source.encode(), capture_output=True)
print(result.stdout.decode(errors="replace"))
if result.returncode:
    errors = result.stderr.decode(errors="replace")
    print("\n".join(line for line in errors.splitlines() if not line.startswith("I1119")), file=sys.stderr)
sys.exit(result.returncode)
