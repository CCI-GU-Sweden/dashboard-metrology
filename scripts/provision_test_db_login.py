"""Create the test processor login and Secret; never print the password."""
import json
import secrets
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
password = secrets.token_hex(32)
secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "dashboard-metrology-db", "namespace": "core-omero-test"}, "type": "Opaque", "stringData": {"PGUSER": "metrology_worker", "PGPASSWORD": password}}
result = subprocess.run(ns + ["create", "-f", "-"], input=json.dumps(secret), text=True, capture_output=True)
if result.returncode:
    sys.exit("Secret creation failed; database login was not attempted.")
print("Created dashboard-metrology-db Secret.", flush=True)
# Generated hex has no SQL quoting characters. The statement travels over stdin,
# not command-line arguments. Do not print SQL or subprocess output on failure.
sql = "BEGIN; CREATE ROLE metrology_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '" + password + "'; GRANT metrology_processor TO metrology_worker; COMMIT;\n"
result = subprocess.run(ns + ["exec", "-i", "deploy/filestatistics-pg15", "--", "psql", "-w", "-U", "postgres", "-d", "omerofilestats", "-v", "ON_ERROR_STOP=1"], input=sql, text=True, capture_output=True)
if result.returncode:
    sys.exit("Database login creation failed; Secret remains for reconciliation. Inspect role state before retrying.")
print("Created metrology_worker login and granted metrology_processor.")
