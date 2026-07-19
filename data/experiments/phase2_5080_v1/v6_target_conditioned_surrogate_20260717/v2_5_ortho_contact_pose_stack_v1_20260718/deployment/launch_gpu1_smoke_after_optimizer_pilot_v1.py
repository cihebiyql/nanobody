#!/usr/bin/env python3
"""Start the audited V2.5 head smoke only after the GPU1 optimizer pilot passes."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path


PILOT_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_d_inner_optimizer_pilot_runtime_v1_2_20260718"
)
SOURCE_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_ortho_heads_smoke_package_v1_20260718"
)
OVERLAY_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_ortho_heads_gpu1_sequential_overlay_v1_20260718"
)
RUNTIME_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_ortho_heads_gpu1_sequential_smoke_runtime_v1_20260718"
)
AUTH_PATH = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_ortho_heads_gpu1_sequential_operator_authorization_v1_20260718.json"
)
WATCH_ROOT = Path(
    "/data1/qlyu/projects/"
    "pvrig_v2_5_ortho_heads_gpu1_post_optimizer_autostart_v1_20260718"
)

EXPECTED_PLAN_SHA = "3ad5ad802b915421ec40d519118233f0a24ddcb6250ffdccd0880e17e19ac114"
EXPECTED_OVERLAY_SHA = "ebf72b4460756dde25448ba98e5d6683686082edb395f6e214134974efcee221"
EXPECTED_LAUNCHER_SHA = "755b82b220dea0f857257ca773c0557d1c4a1c5c4b57a946f3eb20cdf377d27e"
EXPECTED_SOURCE_MANIFEST_SHA = "8fb2fda3c9d1ab19b1ed881e9c13fff826efccc6c14238182ce784e205af6849"
EXPECTED_SOURCE_SHA256S_SHA = "95788336b963a3eaf953f6c5434e94840cfd18cd5bb2a3d6eabc2e590a68d0a4"
AUTH_TOKEN = "I_ACCEPT_V2_5_GPU1_SEQUENTIAL_ONE_EPOCH_REAL_SMOKE"
POLL_SECONDS = 30


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> int:
    require(not WATCH_ROOT.exists(), "watch_root_exists")
    require(not AUTH_PATH.exists(), "authorization_already_exists")
    require(not RUNTIME_ROOT.exists(), "smoke_runtime_already_exists")
    WATCH_ROOT.mkdir(parents=True, exist_ok=False)
    atomic_json(
        WATCH_ROOT / "STATUS.json",
        {
            "status": "WAITING_FOR_PASS_INNER_ONLY_OPTIMIZER_PILOT_COMPLETE",
            "pilot_root": str(PILOT_ROOT),
            "physical_gpu": 1,
            "v4_f_test32_access_count": 0,
        },
    )

    while True:
        terminal_path = PILOT_ROOT / "TERMINAL.json"
        if terminal_path.is_file():
            pilot = json.loads(terminal_path.read_text())
            require(
                pilot.get("status") == "PASS_INNER_ONLY_OPTIMIZER_PILOT_COMPLETE",
                f"optimizer_pilot_not_pass:{pilot.get('status')}",
            )
            require(pilot.get("variants") == 6, "optimizer_pilot_variant_count")
            require(pilot.get("sealed_evaluation_access_count") == 0, "sealed_access")
            results_path = PILOT_ROOT / "RESULTS.tsv"
            require(results_path.is_file(), "optimizer_results_missing")
            require(sha256(results_path) == pilot.get("results_sha256"), "optimizer_results_hash")
            break
        time.sleep(POLL_SECONDS)

    plan = OVERLAY_ROOT / "GPU1_SEQUENTIAL_JOB_PLAN.json"
    overlay = OVERLAY_ROOT / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
    launcher = OVERLAY_ROOT / "src" / "launch_gpu1_sequential_smoke_v1.py"
    require(sha256(plan) == EXPECTED_PLAN_SHA, "plan_hash")
    require(sha256(overlay) == EXPECTED_OVERLAY_SHA, "overlay_hash")
    require(sha256(launcher) == EXPECTED_LAUNCHER_SHA, "launcher_hash")
    require(
        sha256(SOURCE_ROOT / "PACKAGE_MANIFEST.json") == EXPECTED_SOURCE_MANIFEST_SHA,
        "source_manifest_hash",
    )
    require(
        sha256(SOURCE_ROOT / "SHA256SUMS") == EXPECTED_SOURCE_SHA256S_SHA,
        "source_sha256s_hash",
    )

    authorization = {
        "status": "EXPLICITLY_AUTHORIZED_FOR_ONE_GPU1_SEQUENTIAL_REAL_SMOKE",
        "authorization_token": AUTH_TOKEN,
        "job_plan_sha256": EXPECTED_PLAN_SHA,
        "overlay_sha256": EXPECTED_OVERLAY_SHA,
        "physical_gpu": 1,
        "max_cpu_per_process": 8,
        "v4_f_test32_access_count": 0,
        "claim_boundary": (
            "Open-only computational surrogate of independent 8X6B/9E6Y Docking geometry; "
            "not binding probability, affinity, experimental blocking, Docking Gold, or submission evidence."
        ),
    }
    atomic_json(AUTH_PATH, authorization)

    stdout = (WATCH_ROOT / "SMOKE_LAUNCHER_STDOUT.log").open("w")
    stderr = (WATCH_ROOT / "SMOKE_LAUNCHER_STDERR.log").open("w")
    process = subprocess.Popen(
        ["/data1/qlyu/software/envs/pvrig-v6-tc/bin/python", str(launcher)],
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=stderr,
        start_new_session=True,
    )
    atomic_json(
        WATCH_ROOT / "LAUNCH_RECEIPT.json",
        {
            "status": "PASS_V2_5_GPU1_SMOKE_LAUNCHED_AFTER_OPTIMIZER_PILOT",
            "pid": process.pid,
            "pilot_terminal_sha256": sha256(PILOT_ROOT / "TERMINAL.json"),
            "pilot_results_sha256": sha256(PILOT_ROOT / "RESULTS.tsv"),
            "launcher_sha256": EXPECTED_LAUNCHER_SHA,
            "plan_sha256": EXPECTED_PLAN_SHA,
            "overlay_sha256": EXPECTED_OVERLAY_SHA,
            "physical_gpu": 1,
            "max_cpu_per_process": 8,
            "v4_f_test32_access_count": 0,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
