import csv
import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_training_dataset.py"


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def make_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    input_dir = tmp_path / "data"
    output_dir = tmp_path / "out"
    known = tmp_path / "known.fasta"
    known.write_text(">known_positive|kp1\nEVQLKNNW\n", encoding="utf-8")
    write_tsv(
        input_dir / "candidates.tsv",
        [
            {"candidate_id": "candA", "sequence": "EVQLAAAA", "cdr3": "AAAA", "arm_id": "arm1", "backbone_group_id": "bb1", "sequence_group_id": "fam1"},
            {"candidate_id": "candB", "sequence": "EVQLCCCC", "cdr3": "CCCC", "arm_id": "arm1", "backbone_group_id": "bb1", "sequence_group_id": "fam1"},
            {"candidate_id": "known1", "sequence": "EVQLKNNW", "cdr3": "KNNW", "arm_id": "arm2", "backbone_group_id": "bb2", "sequence_group_id": "fam_known"},
        ],
    )
    write_tsv(input_dir / "rf2_metrics.tsv", [{"candidate_id": "candA", "rf2_recovery_rmsd": 1.4, "rf2_plddt": 88.0}])
    write_tsv(input_dir / "monomer_qc.tsv", [{"candidate_id": "candA", "monomer_qc_score": 0.91, "monomer_clash_score": 0.02}])
    write_tsv(input_dir / "baseline_postprocess.tsv", [{"candidate_id": "candA", "baseline_affinity_proxy": -7.2, "baseline_blocker_geometry": 0.73}])
    pdb = input_dir / "haddock_runs" / "candA" / "run_candA" / "6_seletopclusts" / "cluster_1_model_1.pdb"
    pdb.parent.mkdir(parents=True, exist_ok=True)
    pdb.write_text(
        "REMARK HADDOCK score: -42.5\n"
        "REMARK total,bonds,angles,improper,dihe,vdw,elec,air,cdih,coup,rdcs,vean,dani,xpcs,rg\n"
        "REMARK energies: -36.1,0,0,0,0,-11.0,-22.0,0.4,0,0,0,0,0,0,0\n"
        "REMARK Desolvation energy: -3.5\n"
        "REMARK buried surface area: 910.0\n"
        "ATOM      1  CA  GLY A   1       0.0   0.0   0.0  1.00 10.00           C\n",
        encoding="utf-8",
    )
    return input_dir, output_dir, known


def run_builder(input_dir: Path, output_dir: Path, known: Path, mode: str = "partial") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--mode",
            mode,
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--known-positives",
            str(known),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_partial_build_keeps_missing_and_separates_axes(tmp_path: Path) -> None:
    input_dir, output_dir, known = make_fixture(tmp_path)
    result = run_builder(input_dir, output_dir, known)
    assert result.returncode == 0, result.stderr

    expected = {
        "candidates.tsv",
        "rf2_metrics.tsv",
        "monomer_qc.tsv",
        "docking_runs.tsv",
        "docking_pose_features.tsv",
        "candidate_summary.tsv",
        "splits_by_backbone.tsv",
        "failures.tsv",
        "dataset_manifest.json",
    }
    assert expected.issubset({path.name for path in output_dir.iterdir()})

    summary = {row["candidate_id"]: row for row in read_tsv(output_dir / "candidate_summary.tsv")}
    assert summary["candA"]["binder_axis_status"] == "deferred"
    assert summary["candA"]["pose_quality_haddock_score"] == "-42.5"
    assert summary["candA"]["affinity_proxy_score"] == "-7.2"
    assert summary["candA"]["blocker_geometry_score"] == "0.73"
    assert summary["candA"]["rf2_recovery_rmsd"] == "1.4"
    assert summary["candB"]["docking_status"] == "missing"
    assert summary["known1"]["split"] == "calibration_holdout"
    assert summary["known1"]["binder_label"] == "calibration_positive"

    failures = read_tsv(output_dir / "failures.tsv")
    assert any(row["candidate_id"] == "candB" and row["failure_type"] == "missing_docking_run" for row in failures)
    manifest = json.loads((output_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["completed_docking_candidates"] == 1
    assert manifest["missingness_counts"]["missing_docking_run"] == 2


def test_haddock_remark_parser_extracts_score_and_energies(tmp_path: Path) -> None:
    input_dir, output_dir, known = make_fixture(tmp_path)
    result = run_builder(input_dir, output_dir, known)
    assert result.returncode == 0, result.stderr
    pose = read_tsv(output_dir / "docking_pose_features.tsv")[0]
    assert pose["candidate_id"] == "candA"
    assert pose["haddock_score"] == "-42.5"
    assert pose["vdw_energy"] == "-11.0"
    assert pose["electrostatic_energy"] == "-22.0"
    assert pose["desolvation_energy"] == "-3.5"
    assert pose["air_energy"] == "0.4"
    assert pose["buried_surface_area"] == "910.0"
    assert pose["haddock_remark_parse_status"] == "parsed"


def test_final_mode_requires_1000_completed_docking_candidates(tmp_path: Path) -> None:
    input_dir, output_dir, known = make_fixture(tmp_path)
    result = run_builder(input_dir, output_dir, known, mode="final")
    assert result.returncode != 0
    assert "completed docking candidates 1 < 1000" in result.stderr


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            kwargs = {"tmp_path": Path(directory)} if "tmp_path" in inspect.signature(test).parameters else {}
            test(**kwargs)
    print(f"{len(tests)} training-dataset contract tests passed")
