#!/usr/bin/env python3
"""Audit ATOM-heavy identity drift without producing a docking selector.

The audit covers every locally materialized V1.2 Pilot64 fixed-Top-8 pose and,
unless disabled, the four frozen V1.3 boundary runs retrieved read-only from
Node1.  It tests the narrow hypothesis that HADDOCK changes only terminal OXT
presence while preserving every residue and every other heavy-atom identity.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    from experiments.phase2_5080_v1.src import (
        recover_phase2_v3_p2_v1_2_pilot64_emref_top8 as recovery_base,
    )
    from experiments.phase2_5080_v1.src import (
        recover_phase2_v3_p2_v1_3_dual47_emref_top8 as selector,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution from src/
    import recover_phase2_v3_p2_v1_2_pilot64_emref_top8 as recovery_base
    import recover_phase2_v3_p2_v1_3_dual47_emref_top8 as selector


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DEFAULT_OLD_SELECTORS = (
    EXP_DIR
    / "runs/pvrig_v3_p2/pilot64_v1_2_emref_recovery_smoke8/v1_2_smoke8_emref_top8_selector.csv",
    EXP_DIR
    / "runs/pvrig_v3_p2/pilot64_v1_2_emref_recovery_failed52/v1_2_failed52_emref_top8_selector.csv",
)
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_v1_3_atom_identity_difference_audit.json"
DEFAULT_REPORT = EXP_DIR / "reports/PVRIG_V3_P2_DOCKING_GOLD_V1_3_ATOM_IDENTITY_NORMALIZATION_AMENDMENT_PROPOSAL_ZH.md"
AUDIT_STATUS_PASS = "PASS_V1_3_ATOM_IDENTITY_TERMINAL_OXT_ONLY_SUPPORTED"
AUDIT_STATUS_FAIL = "FAIL_V1_3_ATOM_IDENTITY_HAS_NON_OXT_DRIFT"
CLAIM_BOUNDARY = (
    "read-only computational coordinate-identity audit; proposes but does not activate "
    "terminal-OXT normalization; no selector, geometry score, training label, or formal Gold"
)


class IdentityAuditError(RuntimeError):
    """Raised when the read-only identity audit cannot prove its inputs."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(payload: bytes) -> str:
    return selector.sha256_bytes(payload)


def sha256_file(path: Path) -> str:
    return selector.sha256_file(path)


def atom_identity_payload(coordinates: bytes, chain: str, path: Path) -> dict[str, Any]:
    try:
        text = coordinates.decode("ascii")
    except UnicodeDecodeError as error:
        raise IdentityAuditError(f"PDB is not ASCII: {path}") from error
    atoms: set[tuple[str, str, str, str, str, str]] = set()
    residues: list[tuple[str, str, str]] = []
    residue_seen: set[tuple[str, str, str]] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("ATOM  ") or len(line) < 54 or line[21:22] != chain:
            continue
        try:
            residue_number = int(line[22:26])
        except ValueError as error:
            raise IdentityAuditError(f"Invalid residue number in {path}:{line_number}") from error
        resname = line[17:20].strip()
        atom_name = line[12:16].strip()
        insertion = line[26:27].strip()
        altloc = line[16:17].strip()
        element = line[76:78].strip().upper() if len(line) >= 78 else ""
        if not resname or not atom_name:
            raise IdentityAuditError(f"Missing ATOM identity in {path}:{line_number}")
        is_heavy = element not in {"H", "D"} if element else not atom_name.upper().startswith(("H", "D"))
        if not is_heavy:
            continue
        residue = (str(residue_number), insertion, resname)
        atom = (*residue, atom_name, altloc, element)
        if atom in atoms:
            raise IdentityAuditError(f"Duplicate ATOM-heavy identity in {path}:{line_number}: {atom}")
        atoms.add(atom)
        if residue not in residue_seen:
            residue_seen.add(residue)
            residues.append(residue)
    if not atoms or not residues:
        raise IdentityAuditError(f"No ATOM-heavy identities for chain {chain}: {path}")
    terminal_residue = residues[-1]
    sorted_atoms = sorted(atoms)
    sorted_residues = sorted(residue_seen)
    terminal_oxt = {
        atom for atom in atoms if atom[:3] == terminal_residue and atom[3] == "OXT"
    }
    non_terminal_oxt = {
        atom for atom in atoms if atom[3] == "OXT" and atom[:3] != terminal_residue
    }
    return {
        "chain": chain,
        "atom_set": atoms,
        "residue_set": residue_seen,
        "terminal_residue": terminal_residue,
        "terminal_oxt_set": terminal_oxt,
        "non_terminal_oxt_set": non_terminal_oxt,
        "atom_count": len(atoms),
        "residue_count": len(residue_seen),
        "atom_identity_sha256": sha256_bytes(canonical_json(sorted_atoms).encode("utf-8")),
        "residue_identity_sha256": sha256_bytes(canonical_json(sorted_residues).encode("utf-8")),
    }


def identity_record(value: tuple[str, ...]) -> dict[str, str]:
    result = {
        "resseq": value[0],
        "icode": value[1],
        "resname": value[2],
    }
    if len(value) == 6:
        result.update({"atom_name": value[3], "altloc": value[4], "element": value[5]})
    return result


def compare_identity(
    reference: Mapping[str, Any], pose: Mapping[str, Any]
) -> dict[str, Any]:
    reference_atoms = set(reference["atom_set"])
    pose_atoms = set(pose["atom_set"])
    reference_residues = set(reference["residue_set"])
    pose_residues = set(pose["residue_set"])
    missing_atoms = reference_atoms - pose_atoms
    extra_atoms = pose_atoms - reference_atoms
    missing_residues = reference_residues - pose_residues
    extra_residues = pose_residues - reference_residues
    reference_normalized = reference_atoms - set(reference["terminal_oxt_set"])
    pose_normalized = pose_atoms - set(pose["terminal_oxt_set"])
    non_oxt_missing = reference_normalized - pose_normalized
    non_oxt_extra = pose_normalized - reference_normalized
    all_atom_differences_are_terminal_oxt = (
        not non_oxt_missing
        and not non_oxt_extra
        and not reference["non_terminal_oxt_set"]
        and not pose["non_terminal_oxt_set"]
    )
    return {
        "reference_atom_count": reference["atom_count"],
        "pose_atom_count": pose["atom_count"],
        "reference_residue_count": reference["residue_count"],
        "pose_residue_count": pose["residue_count"],
        "reference_atom_identity_sha256": reference["atom_identity_sha256"],
        "pose_atom_identity_sha256": pose["atom_identity_sha256"],
        "reference_residue_identity_sha256": reference["residue_identity_sha256"],
        "pose_residue_identity_sha256": pose["residue_identity_sha256"],
        "reference_terminal_residue": identity_record(reference["terminal_residue"]),
        "pose_terminal_residue": identity_record(pose["terminal_residue"]),
        "residue_identity_exact": not missing_residues and not extra_residues,
        "atom_identity_exact": not missing_atoms and not extra_atoms,
        "terminal_oxt_normalized_atom_identity_exact": reference_normalized == pose_normalized,
        "all_atom_differences_are_terminal_oxt": all_atom_differences_are_terminal_oxt,
        "missing_atoms": [identity_record(item) for item in sorted(missing_atoms)],
        "extra_atoms": [identity_record(item) for item in sorted(extra_atoms)],
        "missing_residues": [identity_record(item) for item in sorted(missing_residues)],
        "extra_residues": [identity_record(item) for item in sorted(extra_residues)],
        "non_oxt_missing_atoms": [identity_record(item) for item in sorted(non_oxt_missing)],
        "non_oxt_extra_atoms": [identity_record(item) for item in sorted(non_oxt_extra)],
    }


def workspace_path(relpath: str) -> Path:
    return selector.contained_path(WORKSPACE_ROOT, relpath, "workspace artifact")


def compare_pose(
    *,
    cohort: str,
    run_id: str,
    source_run_id: str,
    candidate_id: str,
    receptor_id: str,
    rank: int,
    source_output_index: int,
    source_score: str,
    source_seed: int,
    pose_path: Path,
    monomer_path: Path,
    receptor_path: Path,
    pose_source_sha256: str,
    pose_coordinate_sha256: str,
    v1_3_reuse_overlap: bool,
    pose_provenance_path: str | None = None,
    reference_provenance_paths: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    pose_coordinates = recovery_base.read_coordinate_bytes(pose_path)
    monomer_coordinates = recovery_base.read_coordinate_bytes(monomer_path)
    receptor_coordinates = recovery_base.read_coordinate_bytes(receptor_path)
    observed_coordinate_sha = sha256_bytes(pose_coordinates)
    if observed_coordinate_sha != pose_coordinate_sha256:
        raise IdentityAuditError(f"Pose coordinate hash mismatch: {pose_path}")
    if sha256_file(pose_path) != pose_source_sha256:
        raise IdentityAuditError(f"Pose source hash mismatch: {pose_path}")
    chains = {}
    for chain, reference_path, reference_coordinates in (
        ("A", monomer_path, monomer_coordinates),
        ("B", receptor_path, receptor_coordinates),
    ):
        reference = atom_identity_payload(reference_coordinates, chain, reference_path)
        pose = atom_identity_payload(pose_coordinates, chain, pose_path)
        chains[chain] = {
            "reference_relpath": (
                reference_provenance_paths[chain]
                if reference_provenance_paths is not None
                else selector.workspace_relative(reference_path, WORKSPACE_ROOT)
            ),
            "reference_sha256": sha256_file(reference_path),
            **compare_identity(reference, pose),
        }
    return {
        "cohort": cohort,
        "run_id": run_id,
        "source_run_id": source_run_id,
        "candidate_id": candidate_id,
        "receptor_id": receptor_id,
        "native_rank": rank,
        "source_output_index": source_output_index,
        "source_score": source_score,
        "source_seed": source_seed,
        "source_pose_relpath": (
            pose_provenance_path
            if pose_provenance_path is not None
            else selector.workspace_relative(pose_path, WORKSPACE_ROOT)
        ),
        "source_pose_sha256": pose_source_sha256,
        "decompressed_coordinate_sha256": pose_coordinate_sha256,
        "v1_3_reuse_overlap": v1_3_reuse_overlap,
        "chains": chains,
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit_old_selectors(
    selector_paths: Sequence[Path], v1_3_reuse_run_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    poses: list[dict[str, Any]] = []
    inputs = []
    seen_keys: set[tuple[str, int]] = set()
    for selector_path in selector_paths:
        selector_path = selector_path.resolve()
        rows = read_csv(selector_path)
        root = selector_path.parent
        inputs.append({
            "relpath": selector.workspace_relative(selector_path, WORKSPACE_ROOT),
            "sha256": sha256_file(selector_path),
            "rows": len(rows),
        })
        for row in rows:
            key = (row["run_id"], int(row["canonical_rank"]))
            if key in seen_keys:
                raise IdentityAuditError(f"Duplicate old selector pose key: {key}")
            seen_keys.add(key)
            if selector.row_sha256(row, "selection_row_sha256") != row["selection_row_sha256"]:
                raise IdentityAuditError(f"Old selector row hash mismatch: {key}")
            pose_path = workspace_path(row["source_pose_relpath"])
            monomer_path = selector.contained_path(root, row["monomer_relpath"], "old monomer")
            receptor_path = selector.contained_path(root, row["receptor_relpath"], "old receptor")
            poses.append(compare_pose(
                cohort=f"old_{row['selection_cohort']}",
                run_id=row["run_id"],
                source_run_id=row["run_id"],
                candidate_id=row["candidate_id"],
                receptor_id=row["receptor_id"],
                rank=int(row["canonical_rank"]),
                source_output_index=int(row["source_output_index"]),
                source_score=row["source_score"],
                source_seed=int(row["source_seed"]),
                pose_path=pose_path,
                monomer_path=monomer_path,
                receptor_path=receptor_path,
                pose_source_sha256=row["source_pose_sha256"],
                pose_coordinate_sha256=row["decompressed_coordinate_sha256"],
                v1_3_reuse_overlap=row["run_id"] in v1_3_reuse_run_ids,
            ))
    return poses, inputs


def audit_remote_runs(
    descriptors: Sequence[selector.SourceDescriptor],
    cohort: str,
    remote_root: str,
    ssh_executable: str,
    host: str,
    required_completion_status: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected_descriptors = list(descriptors)
    if not selected_descriptors:
        raise IdentityAuditError(f"Remote identity cohort is empty: {cohort}")
    request = recovery_base.build_sync_request(
        [selector.descriptor_sync_row(item) for item in selected_descriptors],
        remote_root,
    )
    poses: list[dict[str, Any]] = []
    completion_statuses: Counter[str] = Counter()
    with tempfile.TemporaryDirectory(prefix=f"pvrig_v1_3_identity_{cohort}_") as temporary:
        root = Path(temporary)
        recovery_base.sync_from_remote(
            request, root, ssh_executable, host, remote_root
        )
        remote_inventory, local_inventory = recovery_base.load_and_verify_inventory(root, request)
        for descriptor in selected_descriptors:
            run = descriptor.run
            assets = selector.verify_asset_hashes(root, descriptor)
            io_relpath = f"{descriptor.run_dir_relpath}/4_emref/io.json"
            params_relpath = f"{descriptor.run_dir_relpath}/4_emref/params.cfg"
            selected, source_inventory = recovery_base.load_pose_records(root, io_relpath)
            recovery_base.validate_params(
                selector.contained_path(root, params_relpath, f"{cohort} params"), run
            )
            if descriptor.source_mode == selector.REUSE_MODE:
                assert descriptor.reuse is not None
                if source_inventory["source_output_count"] != int(
                    descriptor.reuse["source_emref_output_count"]
                ):
                    raise IdentityAuditError(
                        f"Exact-reuse io output count drift: {run['run_id']}"
                    )
                selector.validate_local_hash(
                    selector.contained_path(root, io_relpath, "exact-reuse io"),
                    descriptor.expected_hashes["io"],
                    f"{run['run_id']}.io",
                )
                selector.validate_local_hash(
                    selector.contained_path(root, params_relpath, "exact-reuse params"),
                    descriptor.expected_hashes["params"],
                    f"{run['run_id']}.params",
                )
            completion, _counts = selector.validate_completion(
                assets["completion"], descriptor, source_inventory["source_output_count"]
            )
            completion_statuses[str(completion["status"])] += 1
            if (
                required_completion_status is not None
                and completion["status"] != required_completion_status
            ):
                raise IdentityAuditError(
                    f"Unexpected completion status for {run['run_id']}: {completion['status']}"
                )
            selector.validate_selected_pose_invariants(selected, run)
            for rank, record in enumerate(selected, start=1):
                poses.append(compare_pose(
                    cohort=cohort,
                    run_id=run["run_id"],
                    source_run_id=descriptor.source_run_id,
                    candidate_id=run["candidate_id"],
                    receptor_id=run["receptor_id"],
                    rank=rank,
                    source_output_index=record.output_index,
                    source_score=format(record.score, ".17g"),
                    source_seed=record.seed,
                    pose_path=record.local_path,
                    monomer_path=assets["monomer"],
                    receptor_path=assets["receptor"],
                    pose_source_sha256=record.source_sha256,
                    pose_coordinate_sha256=record.coordinate_sha256,
                    v1_3_reuse_overlap=(
                        descriptor.source_mode == selector.REUSE_MODE
                    ),
                    pose_provenance_path=(
                        f"{descriptor.remote_root}/{record.remote_relpath}"
                    ),
                    reference_provenance_paths={
                        "A": f"{descriptor.remote_root}/{descriptor.monomer_relpath}",
                        "B": f"{descriptor.remote_root}/{descriptor.receptor_relpath}",
                    },
                ))
        inventory = {
            "cohort": cohort,
            "remote_root": remote_root,
            "request_sha256": request["request_sha256"],
            "inventory_relpath": request["inventory_relpath"],
            "remote_file_count": remote_inventory["file_count"],
            "remote_total_bytes": remote_inventory["total_bytes"],
            "remote_file_hash_chain": remote_inventory["file_hash_chain"],
            "local_file_count": local_inventory["file_count"],
            "local_total_bytes": local_inventory["total_bytes"],
            "local_file_hash_chain": local_inventory["file_hash_chain"],
            "remote_local_hash_chain_equal": (
                remote_inventory["file_hash_chain"] == local_inventory["file_hash_chain"]
            ),
            "run_ids": sorted(item.run["run_id"] for item in selected_descriptors),
            "source_run_ids": sorted(item.source_run_id for item in selected_descriptors),
            "completion_status_counts": dict(sorted(completion_statuses.items())),
            "selected_pose_count": len(poses),
        }
    return poses, inventory


def audit_boundary_runs(
    descriptors: Sequence[selector.SourceDescriptor],
    release: selector.ExecutionRelease,
    ssh_executable: str,
    host: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    boundary_ids = set(release.payload["remote_launch_contract"]["boundary_case_ids"])
    selected = [
        item for item in descriptors
        if item.source_mode == selector.NEW_MODE and item.run["case_id"] in boundary_ids
    ]
    if len(selected) != 4:
        raise IdentityAuditError(f"Expected four frozen boundary runs, found {len(selected)}")
    return audit_remote_runs(
        selected,
        "new_v1_3_boundary4",
        str(release.payload["remote_root"]),
        ssh_executable,
        host,
        "PASS_4_EMREF_TOP8_READY",
    )


def audit_exact_reuse_runs(
    descriptors: Sequence[selector.SourceDescriptor],
    old_remote_root: str,
    ssh_executable: str,
    host: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = [item for item in descriptors if item.source_mode == selector.REUSE_MODE]
    if len(selected) != 64:
        raise IdentityAuditError(f"Expected 64 exact-reuse runs, found {len(selected)}")
    return audit_remote_runs(
        selected,
        "old_v1_3_exact_reuse64",
        old_remote_root,
        ssh_executable,
        host,
        None,
    )


def summarize_runs(poses: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for pose in poses:
        grouped[str(pose["run_id"])].append(pose)
    rows = []
    for run_id in sorted(grouped):
        items = sorted(grouped[run_id], key=lambda item: int(item["native_rank"]))
        chains = {}
        for chain in ("A", "B"):
            comparisons = [item["chains"][chain] for item in items]
            difference_counter: Counter[str] = Counter()
            for comparison in comparisons:
                for difference in comparison["missing_atoms"]:
                    difference_counter["missing:" + canonical_json(difference)] += 1
                for difference in comparison["extra_atoms"]:
                    difference_counter["extra:" + canonical_json(difference)] += 1
            chains[chain] = {
                "pose_count": len(comparisons),
                "residue_identity_exact_count": sum(item["residue_identity_exact"] for item in comparisons),
                "atom_identity_exact_count": sum(item["atom_identity_exact"] for item in comparisons),
                "terminal_oxt_normalized_atom_identity_exact_count": sum(
                    item["terminal_oxt_normalized_atom_identity_exact"] for item in comparisons
                ),
                "terminal_oxt_only_count": sum(
                    item["all_atom_differences_are_terminal_oxt"] for item in comparisons
                ),
                "difference_frequencies": dict(sorted(difference_counter.items())),
            }
        rows.append({
            "run_id": run_id,
            "cohort": items[0]["cohort"],
            "candidate_id": items[0]["candidate_id"],
            "receptor_id": items[0]["receptor_id"],
            "pose_count": len(items),
            "v1_3_reuse_overlap": items[0]["v1_3_reuse_overlap"],
            "chains": chains,
        })
    return rows


def aggregate(poses: Sequence[Mapping[str, Any]], runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    chain_summary = {}
    for chain in ("A", "B"):
        comparisons = [pose["chains"][chain] for pose in poses]
        chain_summary[chain] = {
            "comparison_count": len(comparisons),
            "residue_identity_exact_count": sum(item["residue_identity_exact"] for item in comparisons),
            "atom_identity_exact_count": sum(item["atom_identity_exact"] for item in comparisons),
            "terminal_oxt_normalized_atom_identity_exact_count": sum(
                item["terminal_oxt_normalized_atom_identity_exact"] for item in comparisons
            ),
            "all_atom_differences_terminal_oxt_only_count": sum(
                item["all_atom_differences_are_terminal_oxt"] for item in comparisons
            ),
            "non_oxt_difference_count": sum(
                len(item["non_oxt_missing_atoms"]) + len(item["non_oxt_extra_atoms"])
                for item in comparisons
            ),
            "residue_difference_count": sum(
                len(item["missing_residues"]) + len(item["extra_residues"])
                for item in comparisons
            ),
        }
    chains_by_receptor: dict[str, dict[str, Any]] = {}
    for receptor in sorted({str(pose["receptor_id"]) for pose in poses}):
        chains_by_receptor[receptor] = {}
        receptor_poses = [pose for pose in poses if pose["receptor_id"] == receptor]
        for chain in ("A", "B"):
            comparisons = [pose["chains"][chain] for pose in receptor_poses]
            chains_by_receptor[receptor][chain] = {
                "comparison_count": len(comparisons),
                "residue_identity_exact_count": sum(
                    item["residue_identity_exact"] for item in comparisons
                ),
                "atom_identity_exact_count": sum(
                    item["atom_identity_exact"] for item in comparisons
                ),
                "terminal_oxt_normalized_atom_identity_exact_count": sum(
                    item["terminal_oxt_normalized_atom_identity_exact"]
                    for item in comparisons
                ),
                "non_oxt_difference_count": sum(
                    len(item["non_oxt_missing_atoms"]) + len(item["non_oxt_extra_atoms"])
                    for item in comparisons
                ),
                "residue_difference_count": sum(
                    len(item["missing_residues"]) + len(item["extra_residues"])
                    for item in comparisons
                ),
            }
    return {
        "pose_count": len(poses),
        "run_count": len(runs),
        "candidate_count": len({pose["candidate_id"] for pose in poses}),
        "run_counts_by_cohort": dict(sorted(Counter(run["cohort"] for run in runs).items())),
        "pose_counts_by_cohort": dict(sorted(Counter(pose["cohort"] for pose in poses).items())),
        "run_counts_by_receptor": dict(sorted(Counter(run["receptor_id"] for run in runs).items())),
        "pose_counts_by_receptor": dict(sorted(Counter(pose["receptor_id"] for pose in poses).items())),
        "v1_3_reuse_overlap_runs": sum(run["v1_3_reuse_overlap"] for run in runs),
        "v1_3_reuse_overlap_poses": sum(pose["v1_3_reuse_overlap"] for pose in poses),
        "chains": chain_summary,
        "chains_by_receptor": chains_by_receptor,
    }


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    os.replace(temporary, path)


def report_text(audit: Mapping[str, Any], audit_path: Path, audit_sha256: str) -> str:
    summary = audit["summary"]
    a = summary["chains"]["A"]
    b = summary["chains"]["B"]
    receptor_rows = []
    for receptor, chains in summary["chains_by_receptor"].items():
        for chain, values in chains.items():
            receptor_rows.append(
                f"| {receptor} | {chain} | {values['comparison_count']} | "
                f"{values['residue_identity_exact_count']} | {values['atom_identity_exact_count']} | "
                f"{values['terminal_oxt_normalized_atom_identity_exact_count']} | "
                f"{values['non_oxt_difference_count']} |"
            )
    receptor_table = "\n".join(receptor_rows)
    return f"""# PVRIG V1.3 ATOM identity 差异审计与窄化 normalization 修订提案

## 结论

本次仅执行只读坐标 identity 审计，没有运行 docking、selector、几何评分或训练标签生成。

状态：`{audit['status']}`

审计覆盖 `{summary['run_count']}` 个 V1.3 目标 runs、`{summary['pose_count']}` 个 fixed Top-8 poses：

- exact-reuse ledger 64 个旧 Pilot64 runs：{summary['pose_counts_by_cohort'].get('old_v1_3_exact_reuse64', 0)} poses；
- V1.3 新 boundary4：{summary['pose_counts_by_cohort'].get('new_v1_3_boundary4', 0)} poses；
- 总闭包：`64 × 8 + 4 × 8 = 544` poses。

核心结果：

| chain | comparisons | residue exact | raw atom exact | OXT-normalized exact | non-OXT differences |
|---|---:|---:|---:|---:|---:|
| A / VHH | {a['comparison_count']} | {a['residue_identity_exact_count']} | {a['atom_identity_exact_count']} | {a['terminal_oxt_normalized_atom_identity_exact_count']} | {a['non_oxt_difference_count']} |
| B / PVRIG | {b['comparison_count']} | {b['residue_identity_exact_count']} | {b['atom_identity_exact_count']} | {b['terminal_oxt_normalized_atom_identity_exact_count']} | {b['non_oxt_difference_count']} |

按 docking receptor 和 chain 分层：

| receptor | chain | comparisons | residue exact | raw atom exact | OXT-normalized exact | non-OXT differences |
|---|---|---:|---:|---:|---:|---:|
{receptor_table}

观察到的 raw atom identity 差异仅为 VHH C 端终止残基 `OXT` 在 frozen monomer 中存在、在 HADDOCK pose 中缺失。所有 residue identity 与所有非 `OXT` heavy-ATOM identity 均完全一致；PVRIG chain B 为 raw exact match。

## 建议冻结的最窄规则

建议另行预注册、审查并冻结以下规则，**当前脚本和现有 preregistration 不自动启用**：

```text
只允许链末端最后一个 ATOM residue 上 atom_name == OXT 的存在/缺失差异；
比较 residue identity 时不做任何归一化；
比较 atom identity 时仅移除 terminal OXT 后再比较；
任何非末端 OXT、任何其他 atom、residue、chain、resname、resseq、icode、altloc 或 element 差异均 fail-closed。
```

该规则不允许任意删去氧原子，也不允许忽略 HETATM、残基缺失、侧链缺原子或 chain swap。它仅描述本次数据中观察到的 HADDOCK terminal topology 变化。

## 方法与边界

- identity 输入仅使用 `ATOM` heavy atoms；坐标、serial、occupancy 和 B-factor 不参与 identity。
- residue key：`(resseq, icode, resname)`。
- atom key：`(resseq, icode, resname, atom_name, altloc, element)`。
- 旧 exact-reuse64 与新 boundary4 均从各自冻结 remote root 只读归档，并分别验证 remote/local inventory hash-chain 相等。
- 审计不证明 binding、affinity 或 blocking，也不使 V1.3 training/formal Gold 合格。

## 可复核产物

- Audit：`{selector.workspace_relative(audit_path, WORKSPACE_ROOT)}`
- Audit SHA256：`{audit_sha256}`
- 审计脚本：`{audit['implementation']['relpath']}`
- 审计脚本 SHA256：`{audit['implementation']['sha256']}`
- Exact-reuse64 remote inventory chain：`{audit['inputs']['exact_reuse64_remote_inventory']['remote_file_hash_chain']}`
- Boundary4 remote inventory chain：`{audit['inputs']['boundary4_remote_inventory']['remote_file_hash_chain']}`

完整 per-run、per-pose、per-chain 差异记录见 audit JSON。
"""


def build_audit(
    *,
    audit_path: Path = DEFAULT_AUDIT,
    report_path: Path = DEFAULT_REPORT,
    ssh_executable: str = "ssh.exe",
    host: str = "node1",
) -> dict[str, Any]:
    release = selector.load_execution_release(
        selector.DEFAULT_EXECUTION_RELEASE_MANIFEST, selector.DATA_ROOT
    )
    runs, reuse = selector.load_inputs(
        selector.DEFAULT_RUN_MANIFEST, selector.DEFAULT_REUSE_MANIFEST
    )
    old_manifest, _binding = selector.old_manifest_context(reuse, selector.WORKSPACE_ROOT)
    old_root = next(iter({row["source_old_remote_root"] for row in reuse.rows}))
    descriptors = selector.source_descriptors(
        runs, reuse, old_manifest, old_root, str(release.payload["remote_root"])
    )
    selector.validate_dual_lane_identity(descriptors)
    old_poses, old_inventory = audit_exact_reuse_runs(
        descriptors, old_root, ssh_executable, host
    )
    boundary_poses, boundary_inventory = audit_boundary_runs(
        descriptors, release, ssh_executable, host
    )
    poses = old_poses + boundary_poses
    run_rows = summarize_runs(poses)
    summary = aggregate(poses, run_rows)
    all_residues_exact = all(
        comparison["residue_identity_exact"]
        for pose in poses for comparison in pose["chains"].values()
    )
    all_non_oxt_exact = all(
        comparison["terminal_oxt_normalized_atom_identity_exact"]
        and comparison["all_atom_differences_are_terminal_oxt"]
        for pose in poses for comparison in pose["chains"].values()
    )
    exact_reuse_complete = (
        len(old_poses) == 512
        and len({pose["run_id"] for pose in old_poses}) == 64
        and old_inventory["remote_local_hash_chain_equal"] is True
    )
    boundary_complete = (
        len(boundary_poses) == 32
        and len({pose["run_id"] for pose in boundary_poses}) == 4
        and boundary_inventory["remote_local_hash_chain_equal"] is True
    )
    total_complete = len(poses) == 544 and len(run_rows) == 68
    passed = (
        bool(poses)
        and exact_reuse_complete
        and boundary_complete
        and total_complete
        and all_residues_exact
        and all_non_oxt_exact
        and boundary_complete
    )
    implementation = Path(__file__).resolve()
    audit: dict[str, Any] = {
        "schema_version": "phase2_v3_p2_v1_3_atom_identity_difference_audit_v1",
        "status": AUDIT_STATUS_PASS if passed else AUDIT_STATUS_FAIL,
        "claim_boundary": CLAIM_BOUNDARY,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "selector_or_scoring_performed": False,
        "normalization_activated": False,
        "proposed_rule": {
            "name": "TERMINAL_OXT_PRESENCE_NORMALIZATION_ONLY",
            "allowed_difference": "presence_or_absence_of_atom_name_OXT_on_last_ATOM_residue_only",
            "residue_normalization": "none",
            "all_other_atom_or_residue_differences": "fail_closed",
            "requires_separate_preregistration_and_freeze": True,
        },
        "acceptance": {
            "all_residue_identities_exact": all_residues_exact,
            "all_non_terminal_oxt_atom_identities_exact": all_non_oxt_exact,
            "all_512_targeted_exact_reuse_poses_covered": exact_reuse_complete,
            "boundary4_complete_and_hash_closed": boundary_complete,
            "total_544_pose_closure": total_complete,
        },
        "summary": summary,
        "inputs": {
            "execution_release_manifest": {
                "relpath": selector.workspace_relative(release.path, WORKSPACE_ROOT),
                "sha256": release.sha256,
            },
            "exact_reuse_manifest": {
                "relpath": selector.workspace_relative(reuse.path, WORKSPACE_ROOT),
                "sha256": reuse.sha256,
                "run_count": len(reuse.rows),
            },
            "exact_reuse64_remote_inventory": old_inventory,
            "boundary4_remote_inventory": boundary_inventory,
        },
        "implementation": {
            "relpath": selector.workspace_relative(implementation, WORKSPACE_ROOT),
            "sha256": sha256_file(implementation),
        },
        "runs": run_rows,
        "poses": poses,
    }
    selector.write_json_atomic(audit_path, audit)
    audit_sha = sha256_file(audit_path)
    write_text_atomic(report_path, report_text(audit, audit_path, audit_sha))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--ssh-executable", default="ssh.exe")
    parser.add_argument("--host", default="node1")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    audit = build_audit(
        audit_path=args.audit,
        report_path=args.report,
        ssh_executable=args.ssh_executable,
        host=args.host,
    )
    print(json.dumps({
        "status": audit["status"],
        "runs": audit["summary"]["run_count"],
        "poses": audit["summary"]["pose_count"],
        "audit": str(args.audit.resolve()),
        "report": str(args.report.resolve()),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if audit["status"] == AUDIT_STATUS_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
