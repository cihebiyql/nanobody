#!/usr/bin/env bash
set -Eeuo pipefail

RUN_ROOT=${RUN_ROOT:-/data/qlyu/projects/pvrig_rfantibody_docking1024_v2_20260712}
SMOKE_ROOT=${SMOKE_ROOT:-$RUN_ROOT/smoke}
mkdir -p "$SMOKE_ROOT"/{arms,logs,status}
exec 8>"$SMOKE_ROOT/smoke.lock"
if ! flock -n 8; then
  echo "Generation smoke controller is already running"
  exit 0
fi

arms=(P1_orig_S P1_qrg_S P1_ekg_S P1_qkg_L)
gpus=(1 3 5 2)
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

AA3_TO_1 = {
    "ALA":"A", "ARG":"R", "ASN":"N", "ASP":"D", "CYS":"C",
    "GLN":"Q", "GLU":"E", "GLY":"G", "HIS":"H", "ILE":"I",
    "LEU":"L", "LYS":"K", "MET":"M", "PHE":"F", "PRO":"P",
    "SER":"S", "THR":"T", "TRP":"W", "TYR":"Y", "VAL":"V",
}

def sequence(path):
    residues = {}
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("ATOM") and len(line) >= 27 and line[21] == "H" and line[12:16].strip() == "CA":
            residues[int(line[22:26])] = AA3_TO_1[line[17:20].strip()]
    return "".join(residues[key] for key in sorted(residues))

root = Path(sys.argv[1])
arms = ("P1_orig_S", "P1_qrg_S", "P1_ekg_S", "P1_qkg_L")
rows = []
fasta = []
for arm in arms:
    arm_root = root / "arms" / arm
    pdbs = list((arm_root / "backbones").glob("design_*.pdb"))
    trbs = list((arm_root / "backbones").glob("design_*.trb"))
    sequences = list((arm_root / "sequences").glob("design_*_dldesign_*.pdb"))
    ok = len(pdbs) == len(trbs) == len(sequences) == 1
    if sequences:
        text = sequences[0].read_text(encoding="ascii", errors="replace")
        ok = ok and all(f" {label}" in text for label in ("H1", "H2", "H3"))
        seq = sequence(sequences[0])
        ok = ok and seq.endswith("VTVSS")
        fasta.extend((f">{arm}", seq))
    rows.append({"arm_id": arm, "pdb": len(pdbs), "trb": len(trbs), "sequence": len(sequences), "pass": ok})
payload = {"schema_version": 1, "status": "PASS" if all(row["pass"] for row in rows) else "FAIL", "arms": rows}
(root / "status" / "smoke_summary.json").write_text(json.dumps(payload, indent=2) + "\n")
if payload["status"] != "PASS":
    raise SystemExit(1)
print(json.dumps(payload, indent=2))
(root / "smoke_candidates.fasta").write_text("\n".join(fasta) + "\n", encoding="ascii")
PY

[[ ! -e "$SMOKE_ROOT/qc_fast" ]] || {
  echo "Refusing to overwrite existing smoke QC directory: $SMOKE_ROOT/qc_fast" >&2
  exit 2
}
/data/qlyu/software/vhh_eval_tools/bin/vhh-large-scale-screen \
  "$SMOKE_ROOT/smoke_candidates.fasta" \
  -o "$SMOKE_ROOT/qc_fast" \
  --stage fast --fast-chunk-size 4 --chunk-jobs 1 --workers 4 \
  >"$SMOKE_ROOT/logs/qc_fast.log" 2>&1
python3 - "$SMOKE_ROOT/qc_fast/fast_merged.tsv" <<'PY'
import csv
import sys

rows = {row["candidate_id"]: row for row in csv.DictReader(open(sys.argv[1], newline=""), delimiter="\t")}
for candidate_id in ("P1_qrg_S", "P1_ekg_S", "P1_qkg_L"):
    row = rows[candidate_id]
    if row["hard_fail"].strip().lower() == "true":
        raise SystemExit(f"{candidate_id} failed smoke QC: {row['reason_summary']}")
PY

date -Is > "$SMOKE_ROOT/status/smoke.complete"
