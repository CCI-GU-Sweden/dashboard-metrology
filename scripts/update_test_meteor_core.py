"""Build current METEOR-core main and update the test CronJob without running it."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = "core-omero-test"
BUILD_CONFIG = "metrology-processor"
CRONJOB = "metrology-processor"
REPOSITORY = "https://github.com/CCI-GU-Sweden/METEOR-core.git"
IMAGE = "image-registry.openshift-image-registry.svc:5000/core-omero-test/metrology-processor"


def run(args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def main():
    output = run(["git", "ls-remote", "--exit-code", REPOSITORY, "refs/heads/main"])
    lines = output.splitlines()
    if len(lines) != 1:
        raise ValueError("Expected exactly one METEOR-core main revision")
    parts = lines[0].split()
    if len(parts) != 2 or parts[1] != "refs/heads/main" or not re.fullmatch(r"[0-9a-f]{40}", parts[0]):
        raise ValueError("Unexpected METEOR-core revision response")
    revision = parts[0]
    print(f"Building METEOR-core {revision}", flush=True)
    with tempfile.TemporaryDirectory(prefix="metrology-build-") as directory:
        context = Path(directory)
        shutil.copy2(ROOT / "Dockerfile.processor", context / "Dockerfile")
        shutil.copytree(ROOT / "metrology_processor", context / "metrology_processor", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        build = run(["oc", "-n", NAMESPACE, "start-build", BUILD_CONFIG,
                     f"--from-dir={context}", f"--build-arg=METEOR_CORE_REF={revision}", "--wait", "-o", "name"])
    if not re.fullmatch(r"build(?:\.build\.openshift\.io)?/metrology-processor-\d+", build):
        raise ValueError(f"Unexpected build identifier: {build!r}")
    data = json.loads(run(["oc", "-n", NAMESPACE, "get", build, "-o", "json"]))
    if data.get("status", {}).get("phase") != "Complete":
        raise RuntimeError("Build did not complete successfully")
    digest = data.get("status", {}).get("output", {}).get("to", {}).get("imageDigest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Build did not produce a valid image digest")
    image = f"{IMAGE}@{digest}"
    patch = {"spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [{"name": "processor", "image": image}]}}}}}}
    run(["oc", "-n", NAMESPACE, "patch", "cronjob", CRONJOB, "--type=strategic", "-p", json.dumps(patch, separators=(",", ":"))])
    print(f"Updated {NAMESPACE}/{CRONJOB} to {image}")
    print("Existing jobs are unchanged; the next scheduled job uses the new image. No OMERO connection was made.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, OSError, ValueError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        print(f"Update failed: {exc}", file=sys.stderr)
        sys.exit(1)
