#!/usr/bin/env python3
"""Stage a frozen Full-QC290 dual-conformation docking project on node23."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from pathlib import Path


AA3_TO_1 = {
    "ALA": "A",
    "ARG": "R",
    "ASN": "N",
    "ASP": "D",
    "CYS": "C",
    "GLN": "Q",
    "GLU": "E",
    "GLY": "G",
    "HIS": "H",
    "ILE": "I",
    "LEU": "L",
    "LYS": "K",
    "MET": "M",
    "PHE": "F",
    "PRO": "P",
    "SER": "S",
    "THR": "T",
    "TRP": "W",
    "TYR": "Y",
    "VAL": "V",
}

EXPECTED_CANDIDATES = 290
EXPECTED_CONTROLS = 47
EXPECTED_CANDIDATE_JOBS = EXPECTED_CANDIDATES * 2 * 3
EXPECTED_CONTROL_JOBS = EXPECTED_CONTROLS * 2 * 3
EXPECTED_TOTAL_JOBS = EXPECTED_CANDIDATE_JOBS + EXPECTED_CONTROL_JOBS
PROTOCOL_ID = "pvrig_v4_d_fullqc290_dual_redocking_20260715"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def pdb_sequence_and_stats(path: Path, chain: str = "A") -> tuple[str, int, list[int]]:
    residues: list[tuple[int, str, str]] = []
    seen: set[tuple[int, str]] = set()
    atom_count = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("ATOM  ") or len(line) < 54 or line[21] != chain:
            continue
        resname = line[17:20].strip().upper()
        if resname not in AA3_TO_1:
            continue
        atom_count += 1
        key = (int(line[22:26]), line[26])
        if key not in seen:
            seen.add(key)
            residues.append((key[0], key[1], resname))
    if not residues:
        raise RuntimeError(f"no standard residues in chain {chain}: {path}")
    return (
        "".join(AA3_TO_1[resname] for _number, _icode, resname in residues),
        atom_count,
        [number for number, _icode, _resname in residues],
    )


def copy_runtime_template(source: Path, destination: Path) -> None:
    if destination.exists():
        raise RuntimeError(f"destination already exists: {destination}")
    destination.mkdir(parents=True)
    for directory in ("config", "scripts", "tests"):
        shutil.copytree(source / directory, destination / directory)
    for directory in ("source", "normalized", "control_monomers"):
        shutil.copytree(source / "inputs" / directory, destination / "inputs" / directory)
    shutil.copy2(
        source / "inputs/calibration_controls_47.tsv",
        destination / "inputs/calibration_controls_47.tsv",
    )
    (destination / "reports").mkdir()
    shutil.copy2(
        source / "reports/reference_normalization_summary.json",
        destination / "reports/reference_normalization_summary.json",
    )
    for directory in (
        "inputs/candidate_monomers",
        "manifests",
        "status/jobs",
        "logs",
        "runs",
        "results",
        "failed_attempts",
    ):
        (destination / directory).mkdir(parents=True, exist_ok=True)


def freeze_candidates(
    destination: Path,
    split_manifest: Path,
    split_audit: Path,
    teacher_root: Path,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows = read_tsv(split_manifest)
    if len(rows) != EXPECTED_CANDIDATES:
        raise RuntimeError(f"expected {EXPECTED_CANDIDATES} split rows, found {len(rows)}")
    if len({row["candidate_id"] for row in rows}) != EXPECTED_CANDIDATES:
        raise RuntimeError("candidate IDs are not unique")
    if len({row["sequence_sha256"] for row in rows}) != EXPECTED_CANDIDATES:
        raise RuntimeError("candidate sequences are not unique")

    candidate_path = destination / "inputs/candidates_290.tsv"
    write_tsv(candidate_path, rows, list(rows[0]))
    shutil.copy2(split_manifest, destination / "inputs/fullqc290_split_manifest.tsv")
    shutil.copy2(split_audit, destination / "inputs/fullqc290_split_audit.json")

    monomer_rows: list[dict[str, str]] = []
    for row in rows:
        candidate_id = row["candidate_id"]
        matches = list(
            teacher_root.glob(
                f"shard_*/monomer/{candidate_id}/{candidate_id}_nanobodybuilder2_chainA.pdb"
            )
        )
        if len(matches) != 1:
            raise RuntimeError(f"expected one source monomer for {candidate_id}, found {len(matches)}")
        source = matches[0]
        frozen = destination / "inputs/candidate_monomers" / f"{candidate_id}.pdb"
        shutil.copy2(source, frozen)
        sequence, atom_count, residue_numbers = pdb_sequence_and_stats(frozen)
        if sequence != row["sequence"]:
            raise RuntimeError(f"monomer sequence mismatch: {candidate_id}")
        if hashlib.sha256(sequence.encode("utf-8")).hexdigest() != row["sequence_sha256"]:
            raise RuntimeError(f"candidate sequence hash mismatch: {candidate_id}")
        monomer_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence_sha256": row["sequence_sha256"],
                "source_remote_path": str(source),
                "frozen_monomer_path": str(frozen.relative_to(destination)),
                "source_chain": "A",
                "sha256": sha256_file(frozen),
                "size_bytes": str(frozen.stat().st_size),
                "atom_count": str(atom_count),
                "residue_count": str(len(residue_numbers)),
                "first_residue": str(min(residue_numbers)),
                "last_residue": str(max(residue_numbers)),
            }
        )
    monomer_fields = [
        "candidate_id",
        "sequence_sha256",
        "source_remote_path",
        "frozen_monomer_path",
        "source_chain",
        "sha256",
        "size_bytes",
        "atom_count",
        "residue_count",
        "first_residue",
        "last_residue",
    ]
    write_tsv(
        destination / "inputs/candidate_monomers_manifest.tsv",
        monomer_rows,
        monomer_fields,
    )
    return rows, monomer_rows


def replace_text(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        if old not in text:
            raise RuntimeError(f"expected patch token absent in {path}: {old!r}")
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def configure_protocol(destination: Path, candidate_rows: list[dict[str, str]]) -> str:
    config_path = destination / "config/protocol_spec.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    train_candidates = sorted(
        row["candidate_id"] for row in candidate_rows if row["model_split"] == "OPEN_TRAIN"
    )
    if not train_candidates:
        raise RuntimeError("OPEN_TRAIN split is empty")
    smoke_candidate = train_candidates[0]
    config["schema_version"] = 2
    config["protocol_id"] = PROTOCOL_ID
    config["status"] = "PRELOCK_VALIDATION_REQUIRED"
    config["evidence_boundary"] = (
        "prospective_parent_cluster_split_independent_dual_conformation_computational_geometry_"
        "not_binding_affinity_competition_docking_gold_or_functional_blocking"
    )
    config["candidate_panel"] = {
        "panel_id": "fullqc_complete290_parent_cluster_split_v1",
        "expected_count": EXPECTED_CANDIDATES,
        "selection_algorithm": "full_qc_hard_pass_complete_abnativ_before_dual_docking",
        "split_manifest": "inputs/fullqc290_split_manifest.tsv",
        "split_audit": "inputs/fullqc290_split_audit.json",
        "group_unit": "parent_framework_cluster",
        "split_counts": {
            "OPEN_TRAIN": 226,
            "OPEN_DEVELOPMENT": 32,
            "PROSPECTIVE_COMPUTATIONAL_TEST": 32,
        },
        "monomer_freeze_manifest": "inputs/candidate_monomers_manifest.tsv",
        "monomer_source_policy": "290_existing_NanoBodyBuilder2_PDBs_copied_and_hash_verified",
    }
    config["docking"]["expected_candidate_jobs"] = EXPECTED_CANDIDATE_JOBS
    config["docking"]["expected_control_jobs"] = EXPECTED_CONTROL_JOBS
    config["docking"]["expected_total_jobs"] = EXPECTED_TOTAL_JOBS
    config["docking"]["smoke_candidate_id"] = smoke_candidate
    config["scheduler"]["max_parallel"] = 12
    config["scheduler"]["resource_policy"] = (
        "node23_up_to_12_parallel_jobs_x_4_cores_targeting_at_most_75_percent_of_64_logical_CPUs"
    )
    write_json(config_path, config)
    return smoke_candidate


def patch_runtime(destination: Path, smoke_candidate: str) -> None:
    replace_text(
        destination / "scripts/build_docking_jobs.py",
        {
            "Build the frozen 1050-job": "Build the frozen 2022-job",
            "inputs/candidates_128.tsv": "inputs/candidates_290.tsv",
            "candidate panel expected 128 rows": "candidate panel expected 290 rows",
            "fixed128 panel": "fullqc290 panel",
        },
    )
    replace_text(
        destination / "scripts/aggregate_results.py",
        {"inputs/candidates_128.tsv": "inputs/candidates_290.tsv"},
    )
    replace_text(
        destination / "scripts/validate_protocol.py",
        {
            "all 1050 docking jobs": "all 2022 docking jobs",
            'Counter({"control": 282, "candidate": 768})': 'Counter({"control": 282, "candidate": 1740})',
        },
    )

    freeze_path = destination / "scripts/freeze_protocol.py"
    text = freeze_path.read_text(encoding="utf-8")
    new_lists = '''CORE_FILES = [
    "config/protocol_spec.json",
    "config/blocker_judgment_rules_v2.json",
    "inputs/source/8X6B.pdb",
    "inputs/source/9E6Y.pdb",
    "inputs/source/PVRIG_hotspot_set_v1.csv",
    "inputs/normalized/8x6b_pvrig_receptor.pdb",
    "inputs/normalized/8x6b_TL_reference.pdb",
    "inputs/normalized/9e6y_pvrig_receptor.pdb",
    "inputs/normalized/9e6y_TL_reference.pdb",
    "inputs/normalized/interface_hotspots_uniprot.tsv",
    "inputs/candidates_290.tsv",
    "inputs/fullqc290_split_manifest.tsv",
    "inputs/fullqc290_split_audit.json",
    "inputs/candidate_monomers_manifest.tsv",
    "inputs/calibration_controls_47.tsv",
    "reports/fullqc290_candidate_freeze_summary.json",
    "scripts/common.py",
    "scripts/prepare_references.py",
    "scripts/score_pose.py",
]

FINAL_FILES = [
    "config/evaluator_stability_gate.json",
    "manifests/docking_jobs.tsv",
    "manifests/smoke_jobs.tsv",
    "scripts/build_docking_jobs.py",
    "scripts/freeze_protocol.py",
    "scripts/orchestrate_smoke_then_full.py",
    "scripts/run_job.py",
    "scripts/run_controller.py",
    "scripts/status.py",
    "scripts/aggregate_results.py",
    "scripts/validate_protocol.py",
    "tests/test_job_manifest_and_controller.py",
    "tests/test_protocol_freeze.py",
    "tests/test_references_scoring.py",
    "tests/test_stability_gate.py",
]
'''
    text, count = re.subn(
        r"CORE_FILES = \[.*?\]\n\nFINAL_FILES = \[.*?\]\n",
        new_lists,
        text,
        count=1,
        flags=re.S,
    )
    if count != 1:
        raise RuntimeError("failed to replace freeze_protocol file lists")
    text = text.replace("inputs/candidates_128.tsv", "inputs/candidates_290.tsv")
    text = text.replace("len(monomers) != 128", "len(monomers) != 290")
    text = text.replace("expected 128 frozen candidate monomers", "expected 290 frozen candidate monomers")
    text = text.replace(
        '"reports/EVALUATOR_STABLE.json and reports/P2_P3_P4_ENRICHMENT.json must both match "\n            "this protocol lock and have status PASS"',
        '"reports/EVALUATOR_STABLE.json must match this protocol lock and have status PASS; "\n            "model release remains governed by the local V4-D preregistration"',
    )
    freeze_path.write_text(text, encoding="utf-8")

    orchestrator = destination / "scripts/orchestrate_smoke_then_full.py"
    text = orchestrator.read_text(encoding="utf-8")
    old = '''    enrichment = read_json(root / "reports/P2_P3_P4_ENRICHMENT.json", {})
    if full.returncode != 0 or aggregate.returncode != 0:
        final_status = "COMPLETE_REVIEW_REQUIRED"
    elif enrichment.get("status") == "PASS":
        final_status = "COMPLETE_ENRICHMENT_SUPPORTED"
    else:
        final_status = "COMPLETE_GENERATION_LOCKED_NO_RELIABLE_ENRICHMENT"
    write_json(
        root / "status/orchestrator.json",
        {
            "status": final_status,
            "full_controller_returncode": full.returncode,
            "aggregate_returncode": aggregate.returncode,
            "smoke_validation": "reports/SMOKE_VALIDATION.json",
            "evaluator": "reports/EVALUATOR_STABLE.json",
            "enrichment": "reports/P2_P3_P4_ENRICHMENT.json",
            "enrichment_status": enrichment.get("status", "MISSING"),
            "eligible_phases": enrichment.get("eligible_phases", []),
        },
    )
'''
    new = '''    evaluator = read_json(root / "reports/EVALUATOR_STABLE.json", {})
    if full.returncode != 0 or aggregate.returncode != 0:
        final_status = "COMPLETE_REVIEW_REQUIRED"
    elif evaluator.get("status") == "PASS" and evaluator.get("unlockable") is True:
        final_status = "COMPLETE_EVALUATOR_PASS"
    else:
        final_status = "COMPLETE_EVALUATOR_NOT_RELEASED"
    write_json(
        root / "status/orchestrator.json",
        {
            "status": final_status,
            "full_controller_returncode": full.returncode,
            "aggregate_returncode": aggregate.returncode,
            "smoke_validation": "reports/SMOKE_VALIDATION.json",
            "evaluator": "reports/EVALUATOR_STABLE.json",
            "evaluator_status": evaluator.get("status", "MISSING"),
            "evaluator_unlockable": evaluator.get("unlockable", False),
        },
    )
'''
    if old not in text:
        raise RuntimeError("orchestrator aggregation block changed upstream")
    orchestrator.write_text(text.replace(old, new), encoding="utf-8")

    test_job = destination / "tests/test_job_manifest_and_controller.py"
    replace_text(
        test_job,
        {
            "range(1, 129)": "range(1, 291)",
            "PVRIG_RFAb_v2_P2_qkg_L_bb006_mpn00": smoke_candidate,
            "inputs/candidates_128.tsv": "inputs/candidates_290.tsv",
            "freezes_1050_unique_rows": "freezes_2022_unique_rows",
            "len(rows), 1050": "len(rows), 2022",
            'len({row["job_id"] for row in rows}), 1050': 'len({row["job_id"] for row in rows}), 2022',
            'row["entity_type"] == "candidate" for row in rows[282:]), 768': 'row["entity_type"] == "candidate" for row in rows[282:]), 1740',
        },
    )
    replace_text(
        destination / "tests/test_protocol_freeze.py",
        {'"candidate_panel": {"expected_count": 128}': '"candidate_panel": {"expected_count": 290}'},
    )
    stability_test = destination / "tests/test_stability_gate.py"
    stability_text = stability_test.read_text(encoding="utf-8")
    stability_text = stability_text.replace("1050", "2022")
    stability_text = stability_text.replace("inputs/candidates_128.tsv", "inputs/candidates_290.tsv")
    stability_test.write_text(stability_text, encoding="utf-8")

    for obsolete in (
        destination / "tests/test_candidate_panel.py",
        destination / "tests/test_enrichment_gate.py",
    ):
        obsolete.unlink(missing_ok=True)


def write_readme(destination: Path) -> None:
    (destination / "README.md").write_text(
        "# PVRIG V4-D Full-QC290 independent dual-conformation docking\n\n"
        "This project freezes 290 Full-QC/complete-AbNatiV candidates before any new "
        "independent 8X6B/9E6Y docking label is generated. The split is parent-cluster "
        "disjoint: 226 OPEN_TRAIN, 32 OPEN_DEVELOPMENT, and 32 "
        "PROSPECTIVE_COMPUTATIONAL_TEST.\n\n"
        "The complete run contains 1740 candidate jobs and 282 protocol-regression control "
        "jobs. Controls are never training examples. Outputs are computational geometry "
        "evidence only, not binding, affinity, competition, Docking Gold, or experimental "
        "blocking labels.\n\n"
        "The V1.3 failure remains frozen and is not repaired by this project.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--split-audit", type=Path, required=True)
    parser.add_argument("--teacher-root", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_project.resolve()
    destination = args.destination.resolve()
    split_manifest = args.split_manifest.resolve()
    split_audit = args.split_audit.resolve()
    teacher_root = args.teacher_root.resolve()
    copy_runtime_template(source, destination)
    candidates, monomers = freeze_candidates(
        destination,
        split_manifest,
        split_audit,
        teacher_root,
    )
    smoke_candidate = configure_protocol(destination, candidates)
    patch_runtime(destination, smoke_candidate)
    write_readme(destination)

    summary_path = destination / "reports/fullqc290_candidate_freeze_summary.json"
    write_json(
        summary_path,
        {
            "status": "PASS_CANDIDATES_AND_MONOMERS_FROZEN",
            "protocol_id": PROTOCOL_ID,
            "candidate_count": len(candidates),
            "candidate_manifest": "inputs/candidates_290.tsv",
            "candidate_manifest_sha256": sha256_file(destination / "inputs/candidates_290.tsv"),
            "split_manifest_sha256": sha256_file(destination / "inputs/fullqc290_split_manifest.tsv"),
            "split_audit_sha256": sha256_file(destination / "inputs/fullqc290_split_audit.json"),
            "monomer_count": len(monomers),
            "monomer_manifest_sha256": sha256_file(
                destination / "inputs/candidate_monomers_manifest.tsv"
            ),
            "all_monomer_sequences_exact": True,
            "expected_candidate_jobs": EXPECTED_CANDIDATE_JOBS,
            "expected_control_jobs": EXPECTED_CONTROL_JOBS,
            "expected_total_jobs": EXPECTED_TOTAL_JOBS,
            "smoke_candidate_id": smoke_candidate,
            "claim_boundary": (
                "computational_dual_docking_geometry_only_not_binding_affinity_competition_"
                "docking_gold_or_experimental_blocking"
            ),
        },
    )
    print(
        json.dumps(
            {
                "status": "PASS_STAGED",
                "destination": str(destination),
                "candidate_count": len(candidates),
                "monomer_count": len(monomers),
                "expected_total_jobs": EXPECTED_TOTAL_JOBS,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
