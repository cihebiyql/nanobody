from __future__ import annotations

import csv
import importlib.util
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
    for index in range(count):
        cid = f"cand_{index:04d}"
        pdb = pdb_dir / f"{cid}.pdb"
        pdb.write_text(f"REMARK source {cid}\n", encoding="ascii")
        rows.append({"candidate_id": cid, "sequence": "ACDE", "mpnn_pdb": str(pdb), "hotspot_set": "hs", "backbone_index": str(index % 8)})
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
    # One candidate missing in seed42 can still be recovered by enrichment, proving formal gate separation.
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
    assert gate_rows["cand_0000"]["formal_multiseed_gate_status"] == "FORMAL_MULTI_SEED_PASS_PRIMARY_SEED42"
    assert gate_rows["cand_1001"]["old_gate_status"] == "OLD_GATE_FAIL_OR_MISSING_STRICT_SEED42"
    assert gate_rows["cand_1001"]["formal_multiseed_gate_status"] == "FORMAL_MULTI_SEED_PASS_ENRICHMENT_SEED"
    metrics = read_tsv(tmp_path / "parsed" / "rf2_multiseed_metrics.tsv")
    missing = [row for row in metrics if row["rf2_status"] == "RF2_FAILED_MISSING_OUTPUT"]
    assert missing
    assert {row["rf2_failure_label_policy"] for row in missing} == {"not_negative_sample"}
