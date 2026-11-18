"""Attach and verify a small test CSV using the test service account."""
import base64
import json
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
secret = subprocess.run(ns + ["get", "secret", "dashboard-metrology-omero", "-o", "json"], capture_output=True, text=True, check=True)
password = base64.b64decode(json.loads(secret.stdout)["data"]["OMERO_PASSWORD"]).decode()
code = '''import os, sys, tempfile
from omero.gateway import BlitzGateway
password = sys.stdin.readline().strip()
conn = BlitzGateway("metrology_service", password, host="omero", port=4064)
try:
    if not conn.connect():
        raise RuntimeError("login failed")
    conn.setGroupForSession(103)
    image = conn.getObject("Image", 567)
    if image is None:
        raise RuntimeError("image 567 is not visible")
    expected = b"metric,value,unit\\ntest,1,arbitrary\\n"
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "dashboard_metrology_test_567.csv")
        with open(path, "wb") as f:
            f.write(expected)
        annotation = conn.createFileAnnfromLocalFile(path, mimetype="text/csv", ns="org.openmicroscopy.dashboard.metrology.test")
        image.linkAnnotation(annotation)
        linked = [a for a in image.listAnnotations() if a.getId() == annotation.getId()]
        if len(linked) != 1:
            raise RuntimeError("created annotation is not linked")
        actual = b"".join(linked[0].getFileInChunks())
        if actual != expected:
            raise RuntimeError("linked content does not match")
        print("image=567 annotation=%d filename=dashboard_metrology_test_567.csv bytes=%d verified=true" % (annotation.getId(), len(actual)))
finally:
    conn.close()
'''
result = subprocess.run(ns + ["exec", "-i", "deploy/omero-server", "--", "/opt/omero/server/venv3/bin/python", "-c", code], input=password + "\n", text=True, capture_output=True)
if result.returncode:
    print("Attachment check failed; an annotation may have been created. Inspect before retrying.", file=sys.stderr)
    print("\n".join(line for line in result.stderr.replace(password, "[redacted]").splitlines() if not line.startswith("I1118")), file=sys.stderr)
    sys.exit(result.returncode)
print(result.stdout.strip())
