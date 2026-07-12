from __future__ import annotations

import csv
import importlib.util
import inspect
import os
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


prepare_mod = load_module("prepare_rf2_multiseed", "scripts/prepare_rf2_multiseed.py")
parse_mod = load_module("parse_rf2_multiseed", "scripts/parse_rf2_multiseed.py")


def write_candidates(tmp_path: Path, count: int = 1024) -> Path:
    pdb_dir = tmp_path / "pdbs"
    pdb_dir.mkdir()
    rows = []
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    aa1_to_3 = {"A":"ALA","C":"CYS","D":"ASP","E":"GLU","F":"PHE","G":"GLY","H":"HIS","I":"ILE","K":"LYS","L":"LEU","M":"MET","N":"ASN","P":"PRO","Q":"GLN","R":"ARG","S":"SER","T":"THR","V":"VAL","W":"TRP","Y":"TYR"}
    for index in range(count):
        cid = f"cand_{index:04d}"
        value = index
        encoded = []
        for _ in range(4):
            encoded.append(alphabet[value % len(alphabet)])
            value //= len(alphabet)
        sequence = "AC" + "".join(encoded) + "DE"
        pdb = pdb_dir / f"{cid}.pdb"
        lines = []
        serial = 1
        for residue_id, aa in enumerate(sequence, start=1):
            lines.append(f"ATOM  {serial:5d}  CA  {aa1_to_3[aa]:>3s} H{residue_id:4d}    {residue_id:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00  0.00           C")
            serial += 1
        lines.append(f"ATOM  {serial:5d}  CA  GLY T{1:4d}    {0.0:8.3f}{1.0:8.3f}{0.0:8.3f}  1.00  0.00           C")
        lines.extend(("REMARK PDBinfo-LABEL:    1 H1", "REMARK PDBinfo-LABEL:    2 H2", "REMARK PDBinfo-LABEL:    3 H3"))
        pdb.write_text("\n".join(lines) + "\n", encoding="ascii")
        rows.append({"candidate_id": cid, "sequence": sequence, "mpnn_pdb": str(pdb), "hotspot_set": "hs", "backbone_index": str(index % 8)})
    path = tmp_path / "candidates.tsv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def score_text(interaction_pae: float = 1.0) -> str:
    return "\n".join(
        [
            f"SCORE interaction_pae: {interaction_pae}",
            "SCORE pred_lddt: 90.0",
            "SCORE target_aligned_antibody_rmsd: 0.8",
            "SCORE target_aligned_cdr_rmsd: 0.7",
            "",
        ]
    )


def test_prepare_stages_fixed_1024_across_seeds_and_gpu_without_output_collision(tmp_path: Path) -> None:
    candidates = write_candidates(tmp_path)
    batch = tmp_path / "batch"
    summary = prepare_mod.prepare(candidates, batch, [1, 2, 3, 4, 5, 7], [42, 43, 44])

    assert summary["candidate_count"] == 1024
    assert summary["manifest_rows"] == 3072
    assert summary["candidates_by_gpu"] == {"1": 171, "2": 171, "3": 171, "4": 171, "5": 170, "7": 170}

    rows = read_tsv(batch / "rf2_multiseed_manifest.tsv")
    assert len(rows) == 3072
    assert {row["seed"] for row in rows} == {"42", "43", "44"}
    first = [row for row in rows if row["candidate_id"] == "cand_0000"]
    assert len({row["expected_output_pdb"] for row in first}) == 3
    assert all(f"seed_{row['seed']}" in row["expected_output_pdb"] for row in first)
    assert all(row["rf2_failure_label_policy"] == "rf2_fail_or_missing_is_not_a_negative_sample" for row in rows)


def test_parse_keeps_old_seed42_gate_separate_from_formal_multiseed_gate(tmp_path: Path) -> None:
    candidates = write_candidates(tmp_path)
    batch = tmp_path / "batch"
    prepare_mod.prepare(candidates, batch, [1, 2, 3, 4, 5, 7], [42, 43, 44])
    rows = read_tsv(batch / "rf2_multiseed_manifest.tsv")

    # Exactly 1000 seed42 outputs satisfy the enrichment readiness gate; remaining seed42 rows are missing, not negatives.
    for row in [r for r in rows if r["seed"] == "42"][:1000]:
        out = Path(row["expected_output_pdb"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(score_text(), encoding="ascii")
    # A complete 3-seed candidate passes only when at least 2/3 are moderate and one is strict.
    for seed in (43, 44):
        extra = next(r for r in rows if r["candidate_id"] == "cand_0000" and r["seed"] == str(seed))
        extra_out = Path(extra["expected_output_pdb"])
        extra_out.parent.mkdir(parents=True, exist_ok=True)
        extra_out.write_text(score_text(), encoding="ascii")
    # One candidate missing in seed42 remains pending even if one enrichment seed recovers.
    enrich = next(r for r in rows if r["candidate_id"] == "cand_1001" and r["seed"] == "43")
    out = Path(enrich["expected_output_pdb"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(score_text(), encoding="ascii")

    summary = parse_mod.parse(batch / "rf2_multiseed_manifest.tsv", tmp_path / "parsed")
    assert summary["seed42_output_count"] == 1000
    assert summary["seed42_enrichment_ready"] is True
    assert summary["failed_or_missing_are_negative_samples"] is False

    gate_rows = {row["candidate_id"]: row for row in read_tsv(tmp_path / "parsed" / "rf2_multiseed_candidate_gates.tsv")}
    assert gate_rows["cand_0000"]["old_gate_status"] == "OLD_GATE_PASS_STRICT_SEED42"
    assert gate_rows["cand_0000"]["formal_multiseed_gate_status"] == "FORMAL_MULTI_SEED_PASS_2OF3_WITH_STRICT_SUPPORT"
    assert gate_rows["cand_1001"]["old_gate_status"] == "OLD_GATE_FAIL_OR_MISSING_STRICT_SEED42"
    assert gate_rows["cand_1001"]["formal_multiseed_gate_status"] == "FORMAL_MULTI_SEED_PENDING_INCOMPLETE_SEEDS"
    metrics = read_tsv(tmp_path / "parsed" / "rf2_multiseed_metrics.tsv")
    missing = [row for row in metrics if row["rf2_status"] == "RF2_FAILED_MISSING_OUTPUT"]
    assert missing
    assert {row["rf2_failure_label_policy"] for row in missing} == {"not_negative_sample"}


def test_rf2_launcher_waits_per_lane_instead_of_requiring_all_gpus_idle() -> None:
    launcher = (ROOT / "scripts" / "run_rf2_multigpu.sh").read_text(encoding="utf-8")
    controller = (ROOT / "scripts" / "run_downstream_controller.sh").read_text(encoding="utf-8")

    assert "RF2_GPU_LANE_WAIT" in launcher
    assert "RF2_WAITING_LANES" in launcher
    assert "SHARD_BUSY=1" in launcher
    assert "wait_for_gpus" not in controller


def test_rf2_launcher_starts_free_lane_before_waiting_lane(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    staged = tmp_path / "staged"
    staged.mkdir()
    rows = []
    for gpu in (1, 2):
        shard = batch / "seeds" / "seed_42" / "shards" / f"gpu_{gpu}"
        (shard / "input").mkdir(parents=True)
        pdb = staged / f"cand_gpu{gpu}.pdb"
        pdb.write_text("END\n", encoding="ascii")
        rows.append(
            {
                "seed": "42",
                "gpu_id": str(gpu),
                "staged_pdb": str(pdb),
                "expected_output_pdb": str(shard / "output" / f"cand_gpu{gpu}_best.pdb"),
            }
        )
    manifest = batch / "rf2_multiseed_manifest.tsv"
    write_path = manifest
    write_path.parent.mkdir(parents=True, exist_ok=True)
    with write_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "gpu2_queries"
    state.write_text("0\n", encoding="ascii")
    nvidia = fake_bin / "nvidia-smi"
    nvidia.write_text(
        "#!/usr/bin/env bash\n"
        f"state={state!s}\n"
        "case \" $* \" in\n"
        "  *\" --id=2 \"*) n=$(cat \"$state\"); echo $((n+1)) > \"$state\"; "
        "if [[ $n -eq 0 ]]; then echo 13000; else echo 0; fi ;;\n"
        "  *\" --id=1 \"*) echo 0 ;;\n"
        "  *) echo '0, Fake GPU, 0, 24000, 0' ;;\n"
        "esac\n",
        encoding="ascii",
    )
    nvidia.chmod(0o755)
    rf2 = fake_bin / "rf2"
    rf2.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="ascii")
    rf2.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "RUN_ROOT": str(tmp_path),
            "BATCH_ROOT": str(batch),
            "MANIFEST": str(manifest),
            "RF2_BIN": str(rf2),
            "GPU_IDS": "1,2",
            "SEEDS": "42",
            "MAX_LOAD1": "99999",
            "MAX_GPU_USED_MB": "12000",
            "GPU_WAIT_SECONDS": "0",
            "LOAD_WAIT_SECONDS": "0",
        }
    )
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "run_rf2_multigpu.sh")],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "launched seed_42/gpu_1" in result.stdout
    assert "RF2_WAITING_LANES seed=42 gpus=2" in result.stdout
    assert "launched seed_42/gpu_2" in result.stdout
    assert "launched_shards=2" in result.stdout


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        with tempfile.TemporaryDirectory() as directory:
            kwargs = {"tmp_path": Path(directory)} if "tmp_path" in inspect.signature(test).parameters else {}
            test(**kwargs)
    print(f"{len(tests)} RF2 contract tests passed")
