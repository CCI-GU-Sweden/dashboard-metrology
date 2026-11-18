"""Inspect annotation keys and calibration presence without printing values."""
import base64
import json
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
secret = subprocess.run(ns + ["get", "secret", "dashboard-metrology-omero", "-o", "json"], capture_output=True, text=True, check=True)
password = base64.b64decode(json.loads(secret.stdout)["data"]["OMERO_PASSWORD"]).decode()
code = '''import sys
from omero.gateway import BlitzGateway, MapAnnotationWrapper
conn = BlitzGateway("metrology_service", sys.stdin.readline().strip(), host="omero", port=4064)
try:
    if not conn.connect(): raise RuntimeError("login failed")
    conn.setGroupForSession(103)
    for fs in conn.getObjects("Fileset"):
        event = fs.getDetails().getCreationEvent()
        print("fileset", fs.getId(), "timestamp", event.getTime() if event else None, "images", [i.getId() for i in fs.copyImages()])
    for image in conn.getObjects("Image"):
        keys = sorted({str(k) for a in image.listAnnotations() if isinstance(a, MapAnnotationWrapper) for k, v in a.getValue()})
        if image.getId() in (564, 556, 552):
            kinds = [v for a in image.listAnnotations() if isinstance(a, MapAnnotationWrapper) for k, v in a.getValue() if k == "Image type"]
            print("review image", image.getId(), "name", image.getName(), "image type", kinds)
finally:
    conn.close()
'''
result = subprocess.run(ns + ["exec", "-i", "deploy/omero-server", "--", "/opt/omero/server/venv3/bin/python", "-c", code], input=password + "\n", capture_output=True, text=True)
if result.returncode:
    print("OMERO inspection failed", file=sys.stderr)
    sys.exit(result.returncode)
print(result.stdout)
