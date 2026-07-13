from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
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

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_build_package_materializes_manifest_restraints_and_provenance(Path(tmp) / "build")
    test_load_aware_scheduler_waits_when_load_is_at_threshold()
    with tempfile.TemporaryDirectory() as tmp:
        test_status_reports_missingness_from_atomic_state(Path(tmp) / "status")
    with tempfile.TemporaryDirectory() as tmp:
        test_status_counts_only_haddock_selected_models(Path(tmp) / "selected")
    print("4 contract tests passed")
