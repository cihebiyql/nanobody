from __future__ import annotations

import csv
import importlib.util
import inspect
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def pdb_ca_line(serial: int, chain: str, residue: int, x: float, y: float, z: float = 0.0) -> str:
    return f"ATOM  {serial:5d}  CA  SER {chain}{residue:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"


def test_scaffold_refreeze_contract_requires_vtvss_preflight_and_sha_manifest() -> None:
    controller = (ROOT / "scripts" / "run_generation_controller.sh").read_text(encoding="utf-8")
    scaffold = (ROOT / "scripts" / "make_scaffold_variants.py").read_text(encoding="utf-8")

    assert "endswith(\"VTVSS\")" in scaffold
    assert "unexpected scaffold FR4 terminus" in scaffold
    assert "sha256_file(original)" in scaffold
    assert '"source_sha256": sha256_file(args.source)' in scaffold
    assert "lacks canonical VTVSS FR4" in controller
    assert "fr2_hallmark_score" in controller and "hydrophobic_5_count" in controller


def test_generation_status_does_not_report_global_complete_from_controller_marker(tmp_path: Path) -> None:
    arms = [
        {"arm_id": "arm_a", "gpu_id": "1", "target_backbones": "2", "seqs_per_backbone": "3"},
        {"arm_id": "arm_b", "gpu_id": "2", "target_backbones": "2", "seqs_per_backbone": "3"},
    ]
    write_tsv(tmp_path / "config" / "generation_arms.tsv", arms)
    (tmp_path / "status").mkdir()
    (tmp_path / "status" / "generation_controller.complete").write_text("synthetic global marker\n", encoding="ascii")

    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "status_generation.py"), "--run-root", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)

    assert payload["state_counts"] == {"pending": 2}
    assert payload["backbone_pdb_count"] == 0
    assert payload["sequence_pdb_count"] == 0


def test_partial_rf_outputs_do_not_overwrite_existing_frozen_candidates(tmp_path: Path) -> None:
    write_tsv(
        tmp_path / "config" / "generation_arms.tsv",
        [
            {
                "arm_id": "arm_partial",
                "gpu_id": "1",
                "patch_id": "patch",
                "scaffold_id": "qrg",
                "scaffold_lane": "primary_vhhified",
                "h3_regime": "short",
                "target_backbones": "2",
                "seqs_per_backbone": "2",
            }
        ],
    )
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "leakage_reference.fasta").write_text(">known\nEVQLV\n", encoding="ascii")
    arm_root = tmp_path / "generation" / "arms" / "arm_partial"
    (arm_root / "backbones").mkdir(parents=True)
    (arm_root / "sequences").mkdir()
    (arm_root / "complete.json").write_text('{"state":"complete"}\n', encoding="ascii")
    sentinel = "candidate_id\tsequence\nKEEP_ME\tEVQLV\n"
    candidates = tmp_path / "data" / "candidates.tsv"
    candidates.parent.mkdir()
    candidates.write_text(sentinel, encoding="utf-8")

    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "collect_and_freeze_candidates.py"), "--run-root", str(tmp_path), "--target", "1"],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "expected 2 backbones, found 0" in result.stderr
    assert candidates.read_text(encoding="utf-8") == sentinel


def test_haddock_retry_terminal_status_allows_failed_retry_until_max_attempts() -> None:
    sched = load_module("run_haddock_load_aware", "scripts/run_haddock_load_aware.py")
    original_pid_alive = sched.pid_alive
    try:
        sched.pid_alive = lambda _pid: True
        assert sched.terminal_status({"status": "failed", "attempt": 1}, retry_failed=True, max_attempts=2) is None
        assert sched.terminal_status({"status": "failed", "attempt": 2}, retry_failed=True, max_attempts=2) == "failed"
        assert sched.terminal_status({"status": "failed", "attempt": 1}, retry_failed=False, max_attempts=2) == "failed"
        assert sched.terminal_status({"status": "running", "pid": 12345}, retry_failed=True, max_attempts=2) == "running"
        assert sched.terminal_status({"status": "missing"}, retry_failed=True, max_attempts=2) == "missing"
    finally:
        sched.pid_alive = original_pid_alive


def test_chain_b_mapping_refs_can_override_mobile_chain_to_t(tmp_path: Path) -> None:
    align = load_module("align_pdb_by_chain", "scripts/postprocess_helpers/align_pdb_by_chain.py")
    mobile = tmp_path / "mobile.pdb"
    reference = tmp_path / "reference.pdb"
    mapping = tmp_path / "PVRIG_hotspot_set_v1.csv"
    mobile.write_text(
        "\n".join(
            [
                pdb_ca_line(1, "T", 33, 0.0, 0.0),
                pdb_ca_line(2, "T", 34, 1.0, 0.0),
                pdb_ca_line(3, "T", 101, 2.0, 0.0),
                "END",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    reference.write_text(
        "\n".join(
            [
                pdb_ca_line(1, "B", 33, 10.0, 0.0),
                pdb_ca_line(2, "B", 34, 11.0, 0.0),
                pdb_ca_line(3, "B", 101, 12.0, 0.0),
                "END",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    write_csv(
        mapping,
        [
            {"pdb_8x6b_ref": "B:33S"},
            {"pdb_8x6b_ref": "B:34S"},
            {"pdb_8x6b_ref": "B:101S"},
        ],
    )

    mobile_points, reference_points, skipped = align.mapped_fit_points(
        mobile,
        reference,
        mapping,
        "pdb_8x6b_ref",
        "pdb_8x6b_ref",
        "CA",
        mobile_chain_override="T",
        reference_chain_override="B",
    )

    assert len(mobile_points) == 3
    assert len(reference_points) == 3
    assert skipped == 0


def test_dual_baseline_aggregator_preserves_failed_candidates(tmp_path: Path) -> None:
    candidate_rows = [
        {"candidate_id": "cand_ok", "restraint_policy": "synthetic_restraints"},
        {"candidate_id": "cand_failed", "restraint_policy": "synthetic_restraints"},
    ]
    write_tsv(tmp_path / "docking" / "manifests" / "docking_candidates.tsv", candidate_rows)
    state_dir = tmp_path / "docking" / "state" / "postprocess"
    state_dir.mkdir(parents=True)
    (state_dir / "cand_ok.json").write_text('{"status":"success"}\n', encoding="ascii")
    (state_dir / "cand_failed.json").write_text(
        '{"status":"failed","message":"synthetic 9E6Y baseline failed","attempt":2}\n',
        encoding="ascii",
    )
    reports = tmp_path / "docking" / "postprocessed" / "cand_ok" / "reports"
    classification = [
        {
            "model": "cluster_1_model_1",
            "haddock_rank": "1",
            "haddock_score": "-42.5",
            "blocker_class": "BLOCKER_LIKE_A",
        }
    ]
    write_csv(reports / "cand_ok_8x6b_blocker_classification.csv", classification)
    write_csv(reports / "cand_ok_9e6y_blocker_classification.csv", classification)
    write_csv(
        reports / "cand_ok_8x6b_9e6y_consensus.csv",
        [
            {
                "model": "cluster_1_model_1",
                "consensus_class": "CONSENSUS_BLOCKER_LIKE_A",
                "baseline_count": "2",
                "best_haddock_rank": "1",
            }
        ],
    )

    result = subprocess.run(
        ["python3", str(ROOT / "scripts" / "aggregate_dual_baseline.py"), "--run-root", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    summary = json.loads(result.stdout)
    failures = read_tsv(tmp_path / "data" / "postprocess_failures.tsv")
    baseline_rows = {row["candidate_id"]: row for row in read_tsv(tmp_path / "data" / "baseline_postprocess.tsv")}

    assert summary["status_counts"] == {"failed": 1, "success": 1}
    assert failures == [
        {
            "candidate_id": "cand_failed",
            "stage": "dual_baseline_postprocess",
            "status": "failed",
            "reason": "synthetic 9E6Y baseline failed",
            "attempt": "2",
        }
    ]
    assert baseline_rows["cand_failed"]["postprocess_status"] == "failed"


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            kwargs = {"tmp_path": Path(directory)} if "tmp_path" in inspect.signature(test).parameters else {}
            test(**kwargs)
    print(f"{len(tests)} controller contract tests passed")
