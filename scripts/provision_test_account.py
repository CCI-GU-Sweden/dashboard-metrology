"""Provision one test-only OMERO service identity without printing credentials."""
import json
import secrets
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
password = secrets.token_urlsafe(36)
secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "dashboard-metrology-omero", "namespace": "core-omero-test"}, "type": "Opaque", "stringData": {"OMERO_USER": "metrology_service", "OMERO_PASSWORD": password, "OMERO_METROLOGY_GROUP_ID": "103"}}
created = subprocess.run(ns + ["create", "-f", "-"], input=json.dumps(secret), text=True, capture_output=True)
if created.returncode:
    sys.exit("Secret creation failed; no account was attempted: " + created.stderr.strip())
print("Created dashboard-metrology-omero Secret.", flush=True)
command = 'IFS= read -r pass; pass=$(printf "%s" "$pass" | tr -d "\\r"); export OMERO_PASSWORD="$ROOTPASS"; exec /opt/omero/server/OMERO.server/bin/omero user add -s localhost -u root -C -P "$pass" metrology_service Metrology Service --group-id 103'
result = subprocess.run(ns + ["exec", "-i", "deploy/omero-server", "--", "sh", "-c", command], input=password + "\n", text=True, capture_output=True)
if result.returncode:
    sys.exit("Account creation failed; Secret remains for reconciliation. Inspect OMERO account state before retrying.")
print("OMERO account creation command succeeded.")
