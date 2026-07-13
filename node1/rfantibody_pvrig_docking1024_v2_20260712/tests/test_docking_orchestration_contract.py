from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_minimal_inputs(run_root: Path) -> None:
    inputs = run_root / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "hotspot_residues_8x6b.txt").write_text("33\n34\n101\n106\n", encoding="ascii")
    (inputs / "PVRIG_hotspot_set_v1.csv").write_text("hotspot_id,pdb_8x6b_ref\nh1,T:33S\n", encoding="ascii")
    (inputs / "pvrig_8x6b_chainT.pdb").write_text(
        "ATOM      1  CA  SER T  33      0.000   0.000   0.000  1.00 20.00           C\n"
        "ATOM      2  CA  SER T  34      1.000   0.000   0.000  1.00 20.00           C\n"
        "ATOM      3  CA  SER T 101      2.000   0.000   0.000  1.00 20.00           C\n"
        "ATOM      4  CA  SER T 106      3.000   0.000   0.000  1.00 20.00           C\nEND\n",
        encoding="ascii",
    )


def write_candidates(path: Path) -> None:
    path.parent.mkdir(parents=True)
    rows = [
        {
            "candidate_id": "cand_a",
            "sequence": "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISGSGGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCARDYWGQGTLVTVSS",
            "cdr1": "GFTFSSY",
            "cdr2": "AISGSG",
            "cdr3": "DY",
            "docking_cohort_rank": "1",
        },
        {
            "candidate_id": "cand_b",
            "sequence": "EVQLVESGGGLVQPGGSLRLSCAASGFTFSNYAMSWVRQAPGKGLEWVSAITGSGGSTYYADSVKGRFTISRDNAKNTLYLQMNSLRAEDTAVYYCARAYWGQGTLVTVSS",
            "cdr1": "GFTFSNY",
            "cdr2": "AITGSG",
            "cdr3": "AY",
            "docking_cohort_rank": "2",
        },
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_build_package_materializes_manifest_restraints_and_provenance(tmp_path: Path) -> None:
    build = load_module("build_docking_package", ROOT / "scripts" / "build_docking_package.py")
    write_minimal_inputs(tmp_path)
    candidates = tmp_path / "data" / "candidates.tsv"
    write_candidates(candidates)

    summary = build.build_package(tmp_path, candidates, expected_count=2, receptor_chain="T", ncores_per_haddock=4, gpu_ids="1,2,3,4,5,7")

    assert summary["candidate_count"] == 2
    assert summary["unique_candidate_sequences"] == 2
    assert summary["gpu_ids_for_nbb2"] == "1,2,3,4,5,7"
    manifest = tmp_path / "docking" / "manifests" / "docking_candidates.tsv"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8"), delimiter="\t"))
    assert [row["candidate_id"] for row in rows] == ["cand_a", "cand_b"]
    assert rows[0]["restraint_policy"] == build.RESTRAINT_POLICY
    restraint = Path(rows[0]["restraint_file"]).read_text(encoding="ascii")
    assert "segid A" in restraint
    assert "segid T" in restraint
    assert "resi 33" in restraint and "resi 106" in restraint
    cfg = Path(rows[0]["haddock_cfg"]).read_text(encoding="ascii")
    assert "pvrig_8x6b_chainT.pdb" in cfg
    assert "run_cand_a_pvrig_8x6b_full_interface" in cfg


def test_load_aware_scheduler_waits_when_load_is_at_threshold() -> None:
    sched = load_module("run_haddock_load_aware", ROOT / "scripts" / "run_haddock_load_aware.py")
    assert sched.allowed_parallel(current_load=60.0, max_load1=56.0, cores_per_job=4, max_parallel=8) == 0
    assert sched.allowed_parallel(current_load=40.0, max_load1=56.0, cores_per_job=4, max_parallel=8) == 4


def test_scheduler_state_writes_are_safe_across_concurrent_schedulers(tmp_path: Path) -> None:
    sched = load_module("run_haddock_load_aware_concurrent", ROOT / "scripts" / "run_haddock_load_aware.py")
    state = tmp_path / "haddock_controller.json"

    def write_many(worker: int) -> None:
        for sequence in range(40):
            sched.write_json_atomic(state, {"worker": worker, "sequence": sequence})

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(write_many, range(12)))
    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["worker"] in range(12)
    assert payload["sequence"] in range(40)
    assert not list(tmp_path.glob(".haddock_controller.json.*.tmp"))


def test_status_reports_missingness_from_atomic_state(tmp_path: Path) -> None:
    write_minimal_inputs(tmp_path)
    candidates = tmp_path / "data" / "candidates.tsv"
    write_candidates(candidates)
    build = load_module("build_docking_package", ROOT / "scripts" / "build_docking_package.py")
    build.build_package(tmp_path, candidates, expected_count=2, receptor_chain="T", ncores_per_haddock=4, gpu_ids="1,2,3,4,5,7")
    state_dir = tmp_path / "docking" / "state" / "nbb2"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "cand_a.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")

    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "status_docking.py"), "--run-root", str(tmp_path), "--json"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["candidate_count"] == 2
    assert payload["nbb2_counts"]["success"] == 1
    assert payload["nbb2_counts"]["pending"] == 1
    assert payload["missingness"]["restraint_missing"] == 0
    assert payload["missingness"]["cfg_missing"] == 0


def test_status_counts_only_haddock_selected_models(tmp_path: Path) -> None:
    write_minimal_inputs(tmp_path)
    candidates = tmp_path / "data" / "candidates.tsv"
    write_candidates(candidates)
    build = load_module("build_docking_package_selected", ROOT / "scripts" / "build_docking_package.py")
    build.build_package(tmp_path, candidates, expected_count=2, receptor_chain="T", ncores_per_haddock=4, gpu_ids="1,2,3,4,5,7")

    state_dir = tmp_path / "docking" / "state" / "haddock"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "cand_a.json").write_text(json.dumps({"status": "success"}), encoding="utf-8")
    run_dir = tmp_path / "docking" / "haddock" / "cand_a" / "run_cand_a_pvrig_8x6b_full_interface"
    selected_dir = run_dir / "6_seletopclusts"
    selected_dir.mkdir(parents=True)
    (selected_dir / "cluster_1_model_1.pdb").write_text("END\n", encoding="ascii")
    stray_dir = run_dir / "5_cluster"
    stray_dir.mkdir(parents=True)
    (stray_dir / "cluster_99_model_99.pdb").write_text("END\n", encoding="ascii")

    export_dir = tmp_path / "exports"
    subprocess.run(
        [
            "python3",
            str(ROOT / "scripts" / "status_docking.py"),
            "--run-root",
            str(tmp_path),
            "--export-dir",
            str(export_dir),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    rows = list(csv.DictReader((export_dir / "docking_runs.tsv").open(encoding="utf-8"), delimiter="\t"))
    assert rows[0]["docking_status"] == "completed"
    assert rows[0]["selected_model_count"] == "1"
    assert "6_seletopclusts" in rows[0]["selected_model_path"]


def test_haddock_retry_archives_partial_run_before_clean_attempt(tmp_path: Path) -> None:
    candidate = "cand_retry"
    candidate_root = tmp_path / "docking" / "haddock" / candidate
    data_dir = candidate_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / f"{candidate}_vhh_chainA.pdb").write_text("END\n", encoding="ascii")
    (candidate_root / f"{candidate}_pvrig_8x6b_full_interface.cfg").write_text("run_dir = retry\n", encoding="ascii")
    run_dir = candidate_root / f"run_{candidate}_pvrig_8x6b_full_interface"
    run_dir.mkdir()
    (run_dir / "partial_attempt.txt").write_text("failed partial run\n", encoding="ascii")

    state_dir = tmp_path / "docking" / "state" / "haddock"
    state_dir.mkdir(parents=True)
    (state_dir / f"{candidate}.json").write_text(
        json.dumps({"candidate_id": candidate, "status": "failed", "attempt": 1}),
        encoding="utf-8",
    )
    fake_haddock = tmp_path / "fake_haddock.sh"
    fake_haddock.write_text(
        "#!/usr/bin/env bash\n"
        f"mkdir -p run_{candidate}_pvrig_8x6b_full_interface/6_seletopclusts\n"
        f"printf 'END\\n' > run_{candidate}_pvrig_8x6b_full_interface/6_seletopclusts/cluster_1_model_1.pdb\n",
        encoding="ascii",
    )
    fake_haddock.chmod(0o755)

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_haddock_one.sh"), candidate],
        env={
            "PATH": "/usr/bin:/bin",
            "RUN_ROOT": str(tmp_path),
            "HADDOCK3": str(fake_haddock),
            "BOLTZ_BIN": "/usr/bin",
            "CPU_NICE": "0",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((state_dir / f"{candidate}.json").read_text(encoding="utf-8"))
    assert state["status"] == "success"
    assert state["attempt"] == 2
    archives = list((tmp_path / "docking" / "failed_haddock_attempts" / candidate).glob("failed_before_attempt_2_*"))
    assert len(archives) == 1
    assert (archives[0] / "partial_attempt.txt").is_file()
    assert (run_dir / "6_seletopclusts" / "cluster_1_model_1.pdb").is_file()

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_build_package_materializes_manifest_restraints_and_provenance(Path(tmp) / "build")
    test_load_aware_scheduler_waits_when_load_is_at_threshold()
    with tempfile.TemporaryDirectory() as tmp:
        test_status_reports_missingness_from_atomic_state(Path(tmp) / "status")
    with tempfile.TemporaryDirectory() as tmp:
        test_status_counts_only_haddock_selected_models(Path(tmp) / "selected")
    with tempfile.TemporaryDirectory() as tmp:
        test_haddock_retry_archives_partial_run_before_clean_attempt(Path(tmp) / "retry")
    with tempfile.TemporaryDirectory() as tmp:
        test_scheduler_state_writes_are_safe_across_concurrent_schedulers(Path(tmp) / "concurrent")
    print("6 contract tests passed")
