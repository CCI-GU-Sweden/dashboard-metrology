"""Exercise viewer queries with the deployed test dashboard DB identity."""
from pathlib import Path
import subprocess
import sys

source = (Path(__file__).resolve().parents[1] / "dashboard_metrology" / "data.py").read_bytes()
code = '''import os, sys
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dashboard.settings")
import django
django.setup()
scope = {}
exec(compile(sys.stdin.read(), "data.py", "exec"), scope)
summary = scope["summary"]()
microscopes = scope["microscopes"]()
print("summary:", summary)
print("microscopes:", len(microscopes))
if microscopes:
    identifier = microscopes[0]["id"]
    print("lenses:", len(scope["lenses"](identifier)))
    records, total = scope["measurements"](identifier)
    print("measurement page/total:", len(records), total)
    print("scores:", len(scope["latest_scores"](identifier)))
'''
result = subprocess.run(["oc", "-n", "core-omero-test", "exec", "-i", "deploy/dashboard-django", "--", "python", "-c", code], input=source, capture_output=True)
print(result.stdout.decode(errors="replace"))
if result.returncode:
    print(result.stderr.decode(errors="replace"), file=sys.stderr)
sys.exit(result.returncode)
