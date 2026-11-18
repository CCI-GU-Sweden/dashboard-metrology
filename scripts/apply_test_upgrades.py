"""Apply the pending processor schema upgrades to the test database."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
for filename in ("002_analysis_override.sql", "003_artifact_payload.sql"):
    sql = (root / "sql" / filename).read_bytes()
    cmd = ["oc", "-n", "core-omero-test", "exec", "-i", "deploy/filestatistics-pg15", "--", "psql", "-w", "-U", "postgres", "-d", "omerofilestats", "-v", "ON_ERROR_STOP=1"]
    result = subprocess.run(cmd, input=sql, capture_output=True)
    if result.returncode:
        print(result.stderr.decode(errors="replace"), file=sys.stderr)
        sys.exit(result.returncode)
    print(f"Applied {filename}")
