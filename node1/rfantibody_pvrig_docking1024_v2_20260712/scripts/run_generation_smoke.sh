#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
SMOKE_ROOT="$RUN_ROOT/smoke"
mkdir -p "$SMOKE_ROOT"/{arms,logs,status}

arms=(P1_orig_S P1_qrg_S P1_ekg_S P1_qkg_S)
gpus=(1 2 3 4)
pids=()
for i in "${!arms[@]}"; do
  arm=${arms[$i]}
  gpu=${gpus[$i]}
  (
    ARM_OUTPUT_BASE="$SMOKE_ROOT/arms" \
    TARGET_BACKBONES_OVERRIDE=1 \
    SEQS_PER_BACKBONE_OVERRIDE=1 \
      bash "$RUN_ROOT/scripts/run_generation_arm.sh" "$arm" "$gpu"
  ) >"$SMOKE_ROOT/logs/${arm}.log" 2>&1 &
  pids+=("$!")
done

rc=0
for pid in "${pids[@]}"; do
  wait "$pid" || rc=1
done
[[ "$rc" -eq 0 ]] || { echo "Generation smoke failed" >&2; exit 1; }

python3 - "$SMOKE_ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
arms = ("P1_orig_S", "P1_qrg_S", "P1_ekg_S", "P1_qkg_S")
rows = []
for arm in arms:
    arm_root = root / "arms" / arm
    pdbs = list((arm_root / "backbones").glob("design_*.pdb"))
    trbs = list((arm_root / "backbones").glob("design_*.trb"))
    sequences = list((arm_root / "sequences").glob("design_*_dldesign_*.pdb"))
    ok = len(pdbs) == len(trbs) == len(sequences) == 1
    if sequences:
        text = sequences[0].read_text(encoding="ascii", errors="replace")
        ok = ok and all(f" {label}" in text for label in ("H1", "H2", "H3"))
    rows.append({"arm_id": arm, "pdb": len(pdbs), "trb": len(trbs), "sequence": len(sequences), "pass": ok})
payload = {"schema_version": 1, "status": "PASS" if all(row["pass"] for row in rows) else "FAIL", "arms": rows}
(root / "status" / "smoke_summary.json").write_text(json.dumps(payload, indent=2) + "\n")
if payload["status"] != "PASS":
    raise SystemExit(1)
print(json.dumps(payload, indent=2))
PY

date -Is > "$SMOKE_ROOT/status/smoke.complete"
