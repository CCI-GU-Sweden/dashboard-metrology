"""Run the read-only scoring SQL with the test dashboard DB identity."""
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
source = json.load(sys.stdin)
package = types.ModuleType("phase3_probe")
package.__path__ = []
sys.modules["phase3_probe"] = package
for name in ("data", "scoring"):
    module = types.ModuleType("phase3_probe." + name)
    module.__package__ = "phase3_probe"
    sys.modules[module.__name__] = module
    exec(compile(source[name], name + ".py", "exec"), module.__dict__)
s = sys.modules["phase3_probe.scoring"]
rows = s.measurements()
assert all(0 <= row["score"] <= 1 for row in rows)
for row in rows:
    lower, upper, expected, value = (row[x] for x in ("lower_bound", "upper_bound", "expected", "value"))
    target = min(max(expected, lower), upper)
    if lower <= value <= upper:
        expected_score = 1.0
    elif value < lower:
        width = 3 * max(target - lower, 1e-12)
        expected_score = max(0.0, min(1.0, (value - (lower - width)) / width)) ** 2
    else:
        width = 3 * max(upper - target, 1e-12)
        expected_score = max(0.0, min(1.0, ((upper + width) - value) / width)) ** 2
    assert abs(row["score"] - expected_score) < 1e-10
categories, lenses, microscopes = s.aggregate(rows)
print("scored measurements:", len(rows), "category/day:", len(categories), "lens/day:", len(lenses), "microscope/day:", len(microscopes))
if rows:
    mid = rows[0]["microscope_id"]
    assert all(row["microscope_id"] == mid for row in s.measurements(mid))
    print("filtered scoring passed")
'''
result = subprocess.run(["oc", "-n", "core-omero-test", "exec", "-i", "deploy/dashboard-django", "--", "python", "-c", code], input=source.encode(), capture_output=True)
print(result.stdout.decode(errors="replace"))
if result.returncode:
    errors = result.stderr.decode(errors="replace")
    print("\n".join(line for line in errors.splitlines() if not line.startswith("I1119")), file=sys.stderr)
sys.exit(result.returncode)
