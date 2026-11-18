"""Test the provisioned login over TCP without printing credentials."""
import base64
import json
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
secret = subprocess.run(ns + ["get", "secret", "dashboard-metrology-db", "-o", "json"], text=True, capture_output=True, check=True)
password = base64.b64decode(json.loads(secret.stdout)["data"]["PGPASSWORD"]).decode()
command = "IFS= read -r PGPASSWORD; PGPASSWORD=$(printf '%s' \"$PGPASSWORD\" | tr -d '\\r'); export PGPASSWORD; exec psql -w -h localhost -U metrology_worker -d omerofilestats -Atc 'SELECT current_user, version FROM public.metrology_schema_version'"
result = subprocess.run(ns + ["exec", "-i", "deploy/filestatistics-pg15", "--", "sh", "-c", command], input=password + "\n", text=True, capture_output=True)
if result.returncode:
    print("Database login check failed.", file=sys.stderr)
    sys.exit(result.returncode)
print(result.stdout.strip())
