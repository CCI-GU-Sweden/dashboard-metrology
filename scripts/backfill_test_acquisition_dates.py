"""Repair missing acquisition dates from saved OMERO metadata, in test only.

Run from the repository root with --apply to write; default is a dry run.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from metrology_processor.dates import acquired_at

COMMAND = ["oc", "-n", "core-omero-test", "exec", "-i", "deploy/filestatistics-pg15", "--",
           "psql", "-X", "-w", "-U", "postgres", "-d", "omerofilestats", "-v", "ON_ERROR_STOP=1"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    query = """SELECT row_to_json(t) FROM (SELECT m.id, i.metadata->>'Acquisition date' AS date
      FROM public.metrology_measurement m JOIN public.metrology_run_input i
      ON i.run_id=m.run_id AND m.metric_key LIKE i.image_id::text || ':%'
      WHERE m.acquired_at IS NULL AND i.metadata ? 'Acquisition date') t;"""
    output = subprocess.run(COMMAND + ["-Atc", query], check=True, capture_output=True, text=True).stdout
    updates = []
    skipped = 0
    for line in output.splitlines():
        row = json.loads(line)
        date = acquired_at({"Acquisition date": row["date"]})
        if date is None:
            skipped += 1
            continue
        updates.append((int(row["id"]), date.isoformat()))
    print(f"Eligible measurements: {len(updates)}; invalid or ambiguous dates: {skipped}")
    if args.apply and updates:
        values = ",".join(f"({identifier},'{date}'::timestamptz)" for identifier, date in updates)
        sql = ("BEGIN; UPDATE public.metrology_measurement m SET acquired_at=v.acquired_at "
               f"FROM (VALUES {values}) v(id,acquired_at) WHERE m.id=v.id AND m.acquired_at IS NULL; COMMIT;")
        subprocess.run(COMMAND, input=sql, text=True, check=True)


if __name__ == "__main__":
    main()
