"""Apply the versioned baseline to the explicitly named test database."""
from pathlib import Path
import subprocess
import sys

sql = (Path(__file__).resolve().parents[1] / "sql" / "001_initial.sql").read_bytes()
command = ["oc", "-n", "core-omero-test", "exec", "-i", "deploy/filestatistics-pg15", "--", "psql", "-w", "-U", "postgres", "-d", "omerofilestats", "-v", "ON_ERROR_STOP=1"]
result = subprocess.run(command, input=sql, capture_output=True)
print(result.stdout.decode(errors="replace"))
if result.returncode:
    print(result.stderr.decode(errors="replace"), file=sys.stderr)
sys.exit(result.returncode)
