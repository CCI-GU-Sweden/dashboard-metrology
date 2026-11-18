"""Verify grants and constraints in the test database without retaining data."""
from pathlib import Path
import subprocess
import sys

sql = (Path(__file__).resolve().parents[1] / "sql" / "verify_initial.sql").read_bytes()
result = subprocess.run(["oc", "-n", "core-omero-test", "exec", "-i", "deploy/filestatistics-pg15", "--", "psql", "-w", "-U", "postgres", "-d", "omerofilestats", "-v", "ON_ERROR_STOP=1"], input=sql, capture_output=True)
print(result.stdout.decode(errors="replace"))
if result.returncode:
    print(result.stderr.decode(errors="replace"), file=sys.stderr)
sys.exit(result.returncode)
