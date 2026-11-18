"""Check test account access without exposing Secret contents."""
import base64
import json
import subprocess
import sys

ns = ["oc", "-n", "core-omero-test"]
result = subprocess.run(ns + ["get", "secret", "dashboard-metrology-omero", "-o", "json"], capture_output=True, text=True, check=True)
password = base64.b64decode(json.loads(result.stdout)["data"]["OMERO_PASSWORD"]).decode()
code = '''import sys
from omero.gateway import BlitzGateway
password = sys.stdin.readline().strip()
conn = BlitzGateway("metrology_service", password, host="omero", port=4064)
try:
    if not conn.connect():
        raise RuntimeError("login failed: " + type(conn._last_error).__name__ + ": " + str(conn._last_error))
    print("groups:", [(g.getId(), g.getName()) for g in conn.getGroupsMemberOf()])
    conn.setGroupForSession(103)
    images = list(conn.getObjects("Image"))
    filesets = list(conn.getObjects("Fileset"))
    print("visible images:", len(images), "visible filesets:", len(filesets))
    if images:
        img = images[0]
        print("sample image id:", img.getId(), "dimensions:", img.getSizeX(), img.getSizeY(), img.getSizeZ(), img.getSizeC(), img.getSizeT())
        planes = img.getPrimaryPixels().getPlanes([(0, 0, 0), (0, 0, 0)])
        print("batched sample plane shapes:", [plane.shape for plane in planes])
        print("sample can annotate:", img.canAnnotate())
finally:
    conn.close()
'''
check = subprocess.run(ns + ["exec", "-i", "deploy/omero-server", "--", "/opt/omero/server/venv3/bin/python", "-c", code], input=password + "\n", capture_output=True, text=True)
if check.returncode:
    print("Account access check failed; inspect deployment logs and group policy.", file=sys.stderr)
    print("\n".join(line for line in check.stderr.replace(password, "[redacted]").splitlines() if not line.startswith("I1118")), file=sys.stderr)
    sys.exit(check.returncode)
print(check.stdout)
