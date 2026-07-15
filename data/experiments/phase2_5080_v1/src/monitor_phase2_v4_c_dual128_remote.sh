#!/usr/bin/env bash
set -uo pipefail

PROJECT_ROOT="${PVRIG_PROJECT_ROOT:-/data/qlyu/projects/pvrig_v3_dual_conformation_redocking_20260714}"
PYTHON_BIN="${PVRIG_PYTHON:-/data/qlyu/anaconda3/envs/haddock3/bin/python}"
POLL_SECONDS="${PVRIG_V4C_POLL_SECONDS:-60}"
LOCK_FILE="$PROJECT_ROOT/status/v4c_postterminal_aggregate_watcher.lock"
LOG_FILE="$PROJECT_ROOT/logs/v4c_postterminal_aggregate_watcher.log"
RESULT_FILE="$PROJECT_ROOT/status/v4c_postterminal_aggregate_watcher_result.json"

cd "$PROJECT_ROOT" || exit 2
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  printf '%s\n' "another V4-C post-terminal watcher already owns $LOCK_FILE" >&2
  exit 3
fi

printf '%s watcher_started pid=%s\n' "$(date -Is)" "$$" >>"$LOG_FILE"

while true; do
  summary="$($PYTHON_BIN scripts/status.py --json 2>>"$LOG_FILE")"
  status_rc=$?
  if [[ $status_rc -ne 0 ]]; then
    printf '%s status_failed rc=%s\n' "$(date -Is)" "$status_rc" >>"$LOG_FILE"
    sleep "$POLL_SECONDS"
    continue
  fi
  counts="$($PYTHON_BIN -c 'import json,sys; x=json.load(sys.stdin); c=x.get("counts",{}); print(sum(int(c.get(k,0)) for k in ("PENDING","QUEUED","RUNNING","MISSING_EVIDENCE")))' <<<"$summary")"
  printf '%s nonterminal=%s\n' "$(date -Is)" "$counts" >>"$LOG_FILE"
  if [[ "$counts" == "0" ]]; then
    break
  fi
  sleep "$POLL_SECONDS"
done

printf '%s aggregate_start\n' "$(date -Is)" >>"$LOG_FILE"
"$PYTHON_BIN" scripts/aggregate_results.py --expected-total-jobs 1050 >>"$LOG_FILE" 2>&1
aggregate_rc=$?

sha256sum \
  manifests/docking_jobs.tsv \
  PROTOCOL_CORE_LOCK.json \
  PROTOCOL_LOCK.json \
  reports/job_results.tsv \
  reports/pose_scores.tsv \
  reports/PROTOCOL_VALIDATION.json \
  reports/EVALUATOR_STABLE.json \
  reports/P2_P3_P4_ENRICHMENT.json \
  > reports/V4C_POSTTERMINAL_SHA256SUMS.txt 2>>"$LOG_FILE"
hash_rc=$?

"$PYTHON_BIN" - "$RESULT_FILE" "$aggregate_rc" "$hash_rc" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

out, aggregate_rc, hash_rc = sys.argv[1:]
root = Path.cwd()
evaluator_path = root / "reports/EVALUATOR_STABLE.json"
enrichment_path = root / "reports/P2_P3_P4_ENRICHMENT.json"
evaluator = json.loads(evaluator_path.read_text()) if evaluator_path.is_file() else {}
enrichment = json.loads(enrichment_path.read_text()) if enrichment_path.is_file() else {}
payload = {
    "schema_version": "pvrig_v4_c_postterminal_watcher_v1",
    "completed_at": datetime.now(timezone.utc).astimezone().isoformat(),
    "aggregate_returncode": int(aggregate_rc),
    "hash_returncode": int(hash_rc),
    "evaluator_status": evaluator.get("status", "MISSING"),
    "evaluator_evidence_mode": evaluator.get("evidence_mode", "MISSING"),
    "enrichment_status": enrichment.get("status", "MISSING"),
    "teacher_release_ready": (
        int(aggregate_rc) == 0
        and int(hash_rc) == 0
        and evaluator.get("status") == "PASS"
        and evaluator.get("evidence_mode") == "production_pose_backed"
    ),
    "claim_boundary": "Computational dual-docking evidence only; not experimental binding or blocking.",
}
Path(out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY

printf '%s watcher_complete aggregate_rc=%s hash_rc=%s\n' \
  "$(date -Is)" "$aggregate_rc" "$hash_rc" >>"$LOG_FILE"
exit "$aggregate_rc"
