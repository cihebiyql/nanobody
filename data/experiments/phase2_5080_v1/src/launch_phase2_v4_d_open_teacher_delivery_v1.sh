#!/usr/bin/env bash
set -Eeuo pipefail

EXP=/mnt/d/work/抗体/data/experiments/phase2_5080_v1
PYTHON=/usr/bin/python3
SSH_EXE=/mnt/c/Windows/System32/OpenSSH/ssh.exe
SCRIPT=$EXP/src/deliver_phase2_v4_d_open_teacher_from_node23.py
PREREG=$EXP/audits/phase2_v4_d_open_teacher_delivery_v1_preregistration.json
FREEZE=$EXP/audits/phase2_v4_d_open_teacher_delivery_v1_implementation_freeze.json
DELIVERY=$EXP/prepared/pvrig_v4_d_open_teacher_v1/remote_delivery_v1
SESSION=pvrig_v4d_open_teacher_delivery_v1
LOG=$DELIVERY/status/delivery_watcher.log
EXPECTED_SCRIPT_SHA256=cbb4b26f3c628ff08376f98756335420dff4b6ccaf715935ac21a35e7bb8ce94
EXPECTED_PREREG_SHA256=6ff017afbdc4269601169157dc741691b06c74e77f845a191d643e1127a1c89d
EXPECTED_FREEZE_SHA256=639892444fb845f34bafa5570cc42d024c3b16e11abc49af1cd321b27a233cd1

[[ ${PYTHONOPTIMIZE:-0} == 0 || -z ${PYTHONOPTIMIZE:-} ]]
[[ $(sha256sum "$SCRIPT" | awk '{print $1}') == "$EXPECTED_SCRIPT_SHA256" ]]
[[ $(sha256sum "$PREREG" | awk '{print $1}') == "$EXPECTED_PREREG_SHA256" ]]
[[ $(sha256sum "$FREEZE" | awk '{print $1}') == "$EXPECTED_FREEZE_SHA256" ]]
[[ -x "$PYTHON" && -f "$SSH_EXE" ]]
mkdir -p "$DELIVERY/status"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "session_already_running:$SESSION" >&2
  exit 75
fi

COMMAND=$(printf \
  "exec env PYTHONOPTIMIZE=0 %q %q --watch --production --delivery-root %q --ssh-exe %q --remote-host node23 --remote-root %q --poll-seconds 60 --preregistration %q --implementation-freeze %q --expected-script-sha256 %q --expected-preregistration-sha256 %q --expected-implementation-freeze-sha256 %q >>%q 2>&1" \
  "$PYTHON" "$SCRIPT" "$DELIVERY" "$SSH_EXE" \
  "/data/qlyu/projects/pvrig_v4_d_open_teacher_postprocess_v1_20260716" \
  "$PREREG" "$FREEZE" "$EXPECTED_SCRIPT_SHA256" "$EXPECTED_PREREG_SHA256" \
  "$EXPECTED_FREEZE_SHA256" "$LOG")
tmux new-session -d -s "$SESSION" "$COMMAND"
sleep 2
tmux has-session -t "$SESSION"
tmux list-panes -t "$SESSION" -F '#{pane_pid} #{pane_current_command}'
