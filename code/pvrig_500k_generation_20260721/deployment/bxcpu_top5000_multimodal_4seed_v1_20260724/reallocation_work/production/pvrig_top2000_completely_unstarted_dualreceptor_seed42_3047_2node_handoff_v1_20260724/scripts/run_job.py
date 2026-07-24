#!/usr/bin/env python3
"""Run one frozen HADDOCK job with locks, retries, and native/cross scoring."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from build_docking_jobs import render_cfg_from_job, render_restraints_from_job
from common import atomic_write_text, is_standard_atom_line, project_root, read_tsv, sha256_text, write_json


HADDOCK_DEFAULT = "/data/qlyu/anaconda3/envs/haddock3/bin/haddock3"


def root() -> Path:
    return Path(os.environ.get("PVRIG_PROJECT_ROOT", project_root())).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def manifest_rows() -> list[dict[str, str]]:
    path = root() / "manifests/docking_jobs.tsv"
    if not path.is_file():
        raise RuntimeError(f"job manifest missing: {path}")
    return read_tsv(path)


def validate_job_id(job_id: str) -> None:
    if not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id:
        raise RuntimeError(f"invalid job_id path component: {job_id!r}")


def find_job(job_id: str) -> dict[str, str]:
    validate_job_id(job_id)
    matches = [row for row in manifest_rows() if row["job_id"] == job_id]
    if len(matches) != 1:
        raise RuntimeError(f"job_id {job_id} matched {len(matches)} rows")
    return matches[0]


def state_path(job_id: str) -> Path:
    return root() / "status/jobs" / f"{job_id}.json"


def local_scratch_root() -> Path | None:
    value = os.environ.get("PVRIG_LOCAL_SCRATCH_ROOT", "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise RuntimeError("PVRIG_LOCAL_SCRATCH_ROOT must be an absolute path")
    return path.resolve()


def shared_run_path(job_id: str) -> Path:
    return root() / "runs" / job_id


def run_path(job_id: str) -> Path:
    scratch = local_scratch_root()
    return shared_run_path(job_id) if scratch is None else scratch / job_id


def result_path(job_id: str) -> Path:
    return root() / "results" / job_id / "job_result.json"


def read_state(job_id: str) -> dict[str, object]:
    try:
        return json.loads(state_path(job_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(job_id: str, payload: dict[str, object]) -> None:
    state = dict(payload)
    state.update({"job_id": job_id, "updated_at": utc_now()})
    write_json(state_path(job_id), state)


def source_path(job: dict[str, str]) -> Path:
    path = Path(job["monomer_source"])
    return path if path.is_absolute() else root() / path


def is_hydrogen(line: str) -> bool:
    element = line[76:78].strip().upper() if len(line) >= 78 else ""
    if not element:
        element = "".join(ch for ch in line[12:16] if ch.isalpha())[:1].upper()
    return element in {"H", "D"}


def normalize_monomer(source: Path, source_chain: str, destination: Path) -> set[str]:
    if not source.is_file():
        raise RuntimeError(f"monomer source missing: {source}")
    output: list[str] = []
    residues: set[str] = set()
    serial = 1
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not is_standard_atom_line(line) or line[21] != source_chain or is_hydrogen(line):
            continue
        residue = f"{int(line[22:26])}{line[26].strip()}"
        residues.add(residue)
        output.append(f"ATOM  {serial:5d}{line[11:21]}A{line[22:66]}{line[66:]}".rstrip())
        serial += 1
    if not output:
        raise RuntimeError(f"no standard heavy-atom residues for chain {source_chain} in {source}")
    atomic_write_text(destination, "\n".join(output) + "\nTER\nEND\n")
    return residues


def copy_receptor(job: dict[str, str], destination: Path) -> None:
    source = root() / job["receptor_pdb"]
    if not source.is_file():
        raise RuntimeError(f"normalized receptor missing: {source}")
    text = source.read_text(encoding="utf-8", errors="replace")
    if "HETATM" in text or not any(line.startswith("ATOM  ") and line[21] == "T" for line in text.splitlines()):
        raise RuntimeError(f"invalid normalized receptor: {source}")
    atomic_write_text(destination, text)


def archive_previous_attempt(job_id: str, attempt: int) -> None:
    archive_root = root() / "failed_attempts" / job_id / f"attempt_{attempt - 1}_{int(time.time())}"
    moved = False
    scratch_run = run_path(job_id)
    if scratch_run != shared_run_path(job_id) and scratch_run.exists():
        scratch = local_scratch_root()
        if scratch is None:
            raise RuntimeError("local scratch disappeared while archiving a failed attempt")
        try:
            scratch_run.resolve().relative_to(scratch)
        except ValueError as exc:
            raise RuntimeError(f"refusing to archive scratch path outside configured root: {scratch_run}") from exc
        archive_root.mkdir(parents=True, exist_ok=True)
        destination = archive_root / "scratch_run"
        temporary = archive_root / f".scratch_run.copying.{os.getpid()}"
        if destination.exists() or temporary.exists():
            raise RuntimeError(f"scratch archive destination already exists: {archive_root}")
        try:
            shutil.copytree(scratch_run, temporary, copy_function=shutil.copy2)
            temporary.replace(destination)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        shutil.rmtree(scratch_run)
        moved = True
    for label, source in (("run", shared_run_path(job_id)), ("result", result_path(job_id).parent)):
        if source.exists():
            archive_root.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(archive_root / label))
            moved = True
    if moved:
        atomic_write_text(archive_root / "ARCHIVED.txt", f"archived_at={utc_now()}\n")


def prepare_run(job: dict[str, str]) -> Path:
    run_dir = run_path(job["job_id"])
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    available_residues = normalize_monomer(source_path(job), job["monomer_source_chain"], data_dir / "vhh_chainA.pdb")
    requested_residues = {value.strip() for value in job["cdr_residues"].split(",") if value.strip()}
    missing = sorted(requested_residues - available_residues)
    if missing:
        raise RuntimeError(f"manifest CDR residues absent after monomer normalization: {missing}")
    copy_receptor(job, data_dir / "pvrig_chainT.pdb")
    cfg_text = render_cfg_from_job(job)
    restraint_text = render_restraints_from_job(job)
    if sha256_text(cfg_text) != job["cfg_hash"]:
        raise RuntimeError("rendered HADDOCK config hash does not match frozen manifest")
    if sha256_text(restraint_text) != job["restraint_hash"]:
        raise RuntimeError("rendered AIR restraint hash does not match frozen manifest")
    atomic_write_text(run_dir / "haddock3.cfg", cfg_text)
    atomic_write_text(data_dir / "air.tbl", restraint_text)
    write_json(run_dir / "job.json", job)
    return run_dir


def publish_scratch_run(job_id: str, run_dir: Path, attempt: int) -> Path:
    shared = shared_run_path(job_id)
    if run_dir == shared:
        return shared
    write_json(
        run_dir / "SCRATCH_PROVENANCE.json",
        {
            "schema_version": 1,
            "job_id": job_id,
            "attempt": attempt,
            "compute_host": socket.gethostname(),
            "local_scratch_path": str(run_dir),
            "published_at": utc_now(),
        },
    )
    shared.parent.mkdir(parents=True, exist_ok=True)
    temporary = shared.with_name(f".{shared.name}.publishing.{os.getpid()}")
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        shutil.copytree(run_dir, temporary, copy_function=shutil.copy2)
        temporary.replace(shared)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return shared


def cleanup_local_scratch(run_dir: Path) -> None:
    scratch = local_scratch_root()
    if scratch is None or run_dir == shared_run_path(run_dir.name):
        return
    try:
        run_dir.resolve().relative_to(scratch)
    except ValueError as exc:
        raise RuntimeError(f"refusing to clean scratch path outside configured root: {run_dir}") from exc
    shutil.rmtree(run_dir)


def run_haddock(run_dir: Path) -> int:
    stdout_path = run_dir / "haddock.stdout.log"
    stderr_path = run_dir / "haddock.stderr.log"
    override = os.environ.get("PVRIG_HADDOCK_CMD")
    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        if override:
            process = subprocess.run(override, cwd=run_dir, shell=True, stdout=stdout, stderr=stderr)
        else:
            executable = os.environ.get("HADDOCK3") or shutil.which("haddock3") or HADDOCK_DEFAULT
            process = subprocess.run([executable, "haddock3.cfg"], cwd=run_dir, stdout=stdout, stderr=stderr)
    return int(process.returncode)


def selected_models(run_dir: Path) -> list[Path]:
    selection_dir = run_dir / "haddock_run/6_seletopclusts"
    models = sorted(selection_dir.glob("cluster_*_model_*.pdb")) + sorted(selection_dir.glob("cluster_*_model_*.pdb.gz"))
    return sorted(set(models), key=lambda path: path.name)


def score_models(job: dict[str, str], models: list[Path]) -> list[dict[str, object]]:
    score_script = Path(os.environ.get("PVRIG_SCORE_POSE", root() / "scripts/score_pose.py"))
    if not score_script.is_file():
        raise RuntimeError(f"score_pose script missing: {score_script}")
    io_json = shared_run_path(job["job_id"]) / "haddock_run/6_seletopclusts/io.json"
    score_dir = result_path(job["job_id"]).parent / "pose_scores"
    score_dir.mkdir(parents=True, exist_ok=True)
    evidence: list[dict[str, object]] = []
    for model in models:
        name = model.name.removesuffix(".gz").removesuffix(".pdb")
        out = score_dir / f"{name}.json"
        command = [
            sys.executable,
            str(score_script),
            str(model),
            "--root",
            str(root()),
            "--vhh-chain",
            job["vhh_chain"],
            "--cdr1",
            job["cdr1_range"],
            "--cdr2",
            job["cdr2_range"],
            "--cdr3",
            job["cdr3_range"],
            "--out",
            str(out),
        ]
        if io_json.is_file():
            command.extend(["--io-json", str(io_json)])
        process = subprocess.run(command, cwd=root(), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        atomic_write_text(score_dir / f"{name}.stdout.log", process.stdout)
        atomic_write_text(score_dir / f"{name}.stderr.log", process.stderr)
        if process.returncode != 0 or not out.is_file():
            raise RuntimeError(f"score_pose failed for {model}: {process.stderr.strip()}")
        payload = json.loads(out.read_text(encoding="utf-8"))
        if {score["reference_id"] for score in payload.get("scores", [])} != {"8x6b", "9e6y"}:
            raise RuntimeError(f"incomplete native/cross score matrix for {model}")
        haddock = payload.get("haddock_io") or {}
        if not haddock.get("matched_model") or haddock.get("score") is None:
            raise RuntimeError(f"selected model has no matched HADDOCK score in io.json: {model}")
        evidence.append(payload)
    return evidence


def success_is_complete(job_id: str) -> bool:
    path = result_path(job_id)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return payload.get("state") == "SUCCESS" and int(payload.get("selected_model_count", 0)) > 0


def execute(job_id: str, max_attempts: int) -> int:
    validate_job_id(job_id)
    job = find_job(job_id)
    lock_path = root() / "status/locks" / f"{job_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"job already locked: {job_id}", file=sys.stderr)
            return 75
        state = read_state(job_id)
        if state.get("status") == "SUCCESS" and success_is_complete(job_id):
            print(f"skip successful job: {job_id}")
            return 0
        attempt = int(state.get("attempts", 0)) + 1
        if attempt > max_attempts:
            write_state(job_id, {"status": "FAILED_MAX_ATTEMPTS", "attempts": attempt - 1})
            return 1
        run_dir = run_path(job_id)
        scratch_run_dir = run_dir if run_dir != shared_run_path(job_id) else None
        if run_dir.exists() or shared_run_path(job_id).exists() or result_path(job_id).parent.exists():
            archive_previous_attempt(job_id, attempt)
        if run_dir.exists():
            raise RuntimeError(f"previous run directory still exists after archival: {run_dir}")
        write_state(
            job_id,
            {
                "status": "RUNNING",
                "stage": "prepare",
                "attempts": attempt,
                "pid": os.getpid(),
                "job_hash": job["job_hash"],
                "protocol_core_sha256": job["protocol_core_sha256"],
                "started_at": utc_now(),
            },
        )
        try:
            run_dir = prepare_run(job)
            write_state(job_id, {**read_state(job_id), "status": "RUNNING", "stage": "haddock", "pid": os.getpid()})
            return_code = run_haddock(run_dir)
            if return_code != 0:
                raise RuntimeError(f"HADDOCK3 exited with return code {return_code}")
            models = selected_models(run_dir)
            if not models:
                raise RuntimeError("HADDOCK3 produced no selected cluster models")
            if run_dir != shared_run_path(job_id):
                write_state(
                    job_id,
                    {**read_state(job_id), "status": "RUNNING", "stage": "publishing", "pid": os.getpid()},
                )
                run_dir = publish_scratch_run(job_id, run_dir, attempt)
                models = selected_models(run_dir)
            write_state(job_id, {**read_state(job_id), "status": "RUNNING", "stage": "scoring", "pid": os.getpid()})
            pose_scores = score_models(job, models)
            result = {
                "schema_version": 1,
                "job_id": job_id,
                "job_hash": job["job_hash"],
                "protocol_core_sha256": job["protocol_core_sha256"],
                "entity_id": job["entity_id"],
                "entity_type": job["entity_type"],
                "control_class": job["control_class"],
                "expected_behavior": job["expected_behavior"],
                "dock_conformation": job["conformation"],
                "seed": int(job["seed"]),
                "state": "SUCCESS",
                "selected_model_count": len(models),
                "selected_models": [str(path.relative_to(root())) for path in models],
                "pose_scores": pose_scores,
                "completed_at": utc_now(),
            }
            write_json(result_path(job_id), result)
            write_state(
                job_id,
                {
                    "status": "SUCCESS",
                    "stage": "complete",
                    "attempts": attempt,
                    "pid": os.getpid(),
                    "return_code": 0,
                    "selected_model_count": len(models),
                    "evidence": str(result_path(job_id).relative_to(root())),
                    "completed_at": utc_now(),
                },
            )
            try:
                if scratch_run_dir is not None:
                    cleanup_local_scratch(scratch_run_dir)
            except Exception as exc:
                print(f"WARNING: could not clean local scratch for {job_id}: {exc}", file=sys.stderr)
            return 0
        except Exception as exc:
            write_state(
                job_id,
                {
                    "status": "FAILED",
                    "stage": read_state(job_id).get("stage", "unknown"),
                    "attempts": attempt,
                    "pid": os.getpid(),
                    "return_code": 1,
                    "error": str(exc),
                },
            )
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--max-attempts", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        return execute(args.job_id, args.max_attempts)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
