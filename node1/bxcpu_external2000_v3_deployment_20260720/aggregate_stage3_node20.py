#!/usr/bin/env python3
import argparse
import collections
import csv
import datetime
import hashlib
import json
import os
import pathlib


parser = argparse.ArgumentParser()
parser.add_argument("--publish-root", required=True)
parser.add_argument("--manifest", required=True)
args = parser.parse_args()
root = pathlib.Path(args.publish_root)
manifest = pathlib.Path(args.manifest)
with manifest.open() as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if not rows or len({row["job_id"] for row in rows}) != len(rows):
    raise SystemExit("Stage3 manifest is empty or has duplicate job IDs")

output_rows = []
counts = collections.Counter()
errors = []
for row in rows:
    job_id = row["job_id"]
    status_path = root / "status/jobs" / f"{job_id}.json"
    result_path = root / "results" / job_id / "job_result.json"
    result = {}
    if not status_path.exists():
        state = "ABSENT"
    else:
        try:
            status = json.load(status_path.open())
            state = status.get("status", "MISSING")
            if state == "FAILED" and int(status.get("attempts", 0) or 0) >= 2:
                state = "FAILED_MAX_ATTEMPTS"
        except Exception as exc:
            state = "BAD_STATUS"
            errors.append({"job_id": job_id, "error": repr(exc)})
    if result_path.exists():
        try:
            result = json.load(result_path.open())
        except Exception as exc:
            errors.append({"job_id": job_id, "error": repr(exc)})
    counts[state] += 1
    if state == "SUCCESS" and (
        result.get("state") != "SUCCESS"
        or result.get("job_hash") != row["job_hash"]
        or result.get("protocol_core_sha256") != row["protocol_core_sha256"]
    ):
        errors.append({"job_id": job_id, "error": "success result identity/protocol mismatch"})
    output_rows.append(
        {
            "job_id": job_id,
            "entity_id": row["entity_id"],
            "conformation": row["conformation"],
            "seed": row["seed"],
            "status": state,
            "selected_model_count": result.get("selected_model_count", ""),
            "job_hash": row["job_hash"],
            "protocol_core_sha256": row["protocol_core_sha256"],
        }
    )

reports = root / "reports"
reports.mkdir(parents=True, exist_ok=True)
tsv = reports / "stage3_node20_job_results.tsv"
tmp = tsv.with_suffix(".tsv.tmp")
with tmp.open("w", newline="") as handle:
    writer = csv.DictWriter(
        handle, fieldnames=output_rows[0].keys(), delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(output_rows)
os.replace(tmp, tsv)

terminal = counts.get("SUCCESS", 0) + counts.get("FAILED_MAX_ATTEMPTS", 0)
receipt = {
    "schema_version": "pvrig_v29_bxcpu_stage3_node20_aggregation_v1",
    "state": "COMPLETE" if terminal == len(rows) and not errors else "INCOMPLETE_OR_INVALID",
    "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "expected_jobs": len(rows),
    "counts": dict(counts),
    "terminal_jobs": terminal,
    "errors": errors,
    "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    "job_results_tsv": "reports/stage3_node20_job_results.tsv",
    "job_results_sha256": hashlib.sha256(tsv.read_bytes()).hexdigest(),
    "claim_boundary": "Computational docking geometry only; not affinity, Kd, IC50 or experimental blocking.",
}
output = reports / "STAGE3_NODE20_AGGREGATION.json"
tmp = output.with_suffix(".json.tmp")
tmp.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
os.replace(tmp, output)
print(json.dumps({key: value for key, value in receipt.items() if key != "errors"}, indent=2, sort_keys=True))
raise SystemExit(0 if receipt["state"] == "COMPLETE" else 1)
