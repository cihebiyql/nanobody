#!/usr/bin/env bash
set -uo pipefail
R=/data/qlyu/projects/pvrig_v6_v4h_stage1_contact_teacher_v1_20260718
PY=/data/qlyu/software/micromamba-root/envs/torch-cu126-py311/bin/python
mkdir -p "$R/status"
"$PY" "$R/code/extract_v4h_stage1_contact_teacher.py" --campaign-root /data/qlyu/projects/pvrig_v4_h_research_dual_docking_v1_20260717 --terminal-package "$R/terminal_package" --contract "$R/code/V4H_STAGE1_CONTACT_TEACHER_CONTRACT_V1.json" --output-dir "$R/output_v1" --workers 2 --dry-run > "$R/status/dry_run.stdout" 2> "$R/status/dry_run.stderr"
rc=$?
printf '{"status":"%s","return_code":%d,"finished_at":"%s"}\n' "$([[ $rc == 0 ]] && echo PASS_CONTACT_DRY_RUN || echo FAIL_CONTACT_DRY_RUN)" "$rc" "$(date -Is)" > "$R/status/dry_run_terminal.json"
exit "$rc"
