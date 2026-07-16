#!/usr/bin/env python3
"""Build the unified FullQC290 + Dual128 candidate evidence master."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_ROOT = EXP_DIR.parents[2]
DEFAULT_OUT = EXP_DIR / "prepared/pvrig_candidate_evidence_master_v1"
DEFAULT_FULLQC = (
    EXP_DIR
    / "runs/pvrig_teacher_formal_v1/teacher500_full_qc_node23_accel_v1/"
    "teacher500_full_qc_complete290_lineage.csv"
)
DEFAULT_V4D_SPLIT = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
DEFAULT_DUAL = EXP_DIR / "data_splits/pvrig_v4_c/dual128_candidates_source.tsv"
DEFAULT_PRIOR = EXP_DIR / "prepared/pvrig_v4_c/dual128_generic_prior.csv"
DEFAULT_DUAL_SUPPORT = (
    WORKSPACE_ROOT
    / "pvrig_v3_dual_conformation_redocking_20260714/reports/"
    "dual128_candidate_support_summary.tsv"
)
DEFAULT_V4D_MONOMERS = DEFAULT_OUT / "sources/v4d_candidate_monomers_manifest.tsv"
DEFAULT_DUAL_MONOMERS = DEFAULT_OUT / "sources/dual128_candidate_monomers_manifest.tsv"

CLAIM_BOUNDARY = (
    "Evidence table separates QC, weak binding prior, structure and computational "
    "dual-receptor geometry; it does not report binder probability, affinity/Kd, "
    "competition, or experimental blocking."
)

FIELDS = (
    "candidate_id", "sequence", "sequence_sha256", "source_cohort", "source_rank",
    "parent_id", "parent_framework_cluster", "scaffold_id", "arm_id", "phase",
    "design_mode", "target_patch_id", "h3_regime", "backbone_group_id",
    "backbone_index", "mpnn_index", "cdr1", "cdr2", "cdr3", "cdr3_length",
    "near_cdr3_family_id", "fast_gate_tier", "fast_hard_fail", "full_qc_status",
    "official_validator_pass", "anarci_status", "imgt_chain_type",
    "max_positive_cdr_identity", "exact_positive_id", "leakage_status",
    "abnativ_status", "abnativ_vhh_score", "qc_recommendation",
    "developability_score", "expression_purity_risk_score", "gravy", "pi",
    "instability_index", "net_charge_ph7", "unusual_cysteine",
    "n_glycosylation_motif", "deamidation_risk_count", "oxidation_risk_count",
    "isomerization_risk_count", "clipping_risk_count", "max_cdr_hydrophobic_run",
    "tnp_status", "tnp_flags", "generic_prior_status", "generic_binding_prior",
    "generic_prior_uncertainty", "generic_prior_disagreement",
    "generic_prior_claim_boundary", "monomer_status", "monomer_sha256",
    "monomer_residue_count", "monomer_sequence_match", "structure_crosscheck_status",
    "geometry_campaign", "geometry_status", "geometry_support_class",
    "supporting_seeds_8x6b", "supporting_seeds_9e6y", "successful_seeds_8x6b",
    "successful_seeds_9e6y", "r_8x6b", "r_9e6y", "r_dual_mean", "r_dual_min",
    "r_dual_gap", "geometry_uncertainty", "native_cross_agreement",
    "model_pair_consensus", "full_sequence_cluster", "cdr3_cluster", "angle_family",
    "shortlist_eligibility", "final_submission_eligibility", "shortlist_blockers",
    "claim_boundary",
)

FIELD_AXIS = {
    **{name: "identity_lineage" for name in FIELDS[:21]},
    **{name: "hard_qc" for name in FIELDS[21:33]},
    **{name: "developability" for name in FIELDS[33:49]},
    **{name: "binding_contact_weak_prior" for name in FIELDS[49:54]},
    **{name: "monomer_structure" for name in FIELDS[54:59]},
    **{name: "dual_receptor_geometry" for name in FIELDS[59:73]},
    **{name: "diversity" for name in FIELDS[73:76]},
    **{name: "portfolio_governance" for name in FIELDS[76:]},
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_rows(path: Path, delimiter: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


def indexed(rows: list[dict[str, str]], key: str = "candidate_id") -> dict[str, dict[str, str]]:
    result = {row[key]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"duplicate {key} values")
    return result


def parse_design_indices(candidate_id: str) -> tuple[str, str, str]:
    match = re.search(r"_(bb\d+)_(mpn\d+)$", candidate_id)
    if not match:
        return "", "", ""
    backbone = match.group(1)
    mpnn = match.group(2)
    prefix = candidate_id[: match.start()]
    return f"{prefix}_{backbone}", backbone[2:], mpnn[3:]


def normalized_levenshtein(a: str, b: str) -> float:
    if not a and not b:
        return 0.0
    previous = list(range(len(b) + 1))
    for i, aa in enumerate(a, start=1):
        current = [i]
        for j, bb in enumerate(b, start=1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (aa != bb))
            )
        previous = current
    return previous[-1] / max(len(a), len(b))


def assign_cdr3_clusters(rows: list[dict[str, str]], threshold: float = 0.2) -> dict[str, int]:
    parents = list(range(len(rows)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parents[max(root_left, root_right)] = min(root_left, root_right)

    for left, row in enumerate(rows):
        for right in range(left):
            if normalized_levenshtein(row["cdr3"], rows[right]["cdr3"]) <= threshold:
                union(left, right)

    members: dict[int, list[int]] = {}
    for index in range(len(rows)):
        members.setdefault(find(index), []).append(index)
    sizes: dict[str, int] = {}
    for indices in members.values():
        identity = "\n".join(sorted(rows[index]["sequence_sha256"] for index in indices))
        cluster_id = f"cdr3cc_{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
        sizes[cluster_id] = len(indices)
        for index in indices:
            rows[index]["cdr3_cluster"] = cluster_id
    return sizes


def blank_row() -> dict[str, str]:
    return {field: "" for field in FIELDS}


def fullqc_row(
    row: dict[str, str],
    split: dict[str, str],
    monomer: dict[str, str],
) -> dict[str, str]:
    output = blank_row()
    output.update(
        {
            "candidate_id": row["candidate_id"],
            "sequence": row["vhh_sequence"],
            "sequence_sha256": row["sequence_sha256"],
            "source_cohort": "FULLQC290_PRIMARY",
            "source_rank": row.get("selection_rank", ""),
            "parent_id": row.get("parent_id", ""),
            "parent_framework_cluster": row.get("parent_framework_cluster", ""),
            "design_mode": row.get("design_mode", ""),
            "target_patch_id": row.get("target_patch_id", ""),
            "backbone_index": row.get("backbone_index", ""),
            "mpnn_index": row.get("mpnn_index", ""),
            "cdr1": row.get("cdr1_after", ""),
            "cdr2": row.get("cdr2_after", ""),
            "cdr3": row.get("cdr3_after", ""),
            "cdr3_length": row.get("cdr3_length", ""),
            "fast_gate_tier": row.get("fast_gate_tier", ""),
            "fast_hard_fail": row.get("hard_fail", ""),
            "full_qc_status": "COMPLETE_HARD_PASS_ABNATIV_COMPLETE",
            "official_validator_pass": row.get("full_qc_official_validator_pass", ""),
            "anarci_status": row.get("full_qc_ANARCI_status", ""),
            "imgt_chain_type": row.get("full_qc_imgt_chain_type", ""),
            "max_positive_cdr_identity": row.get("max_positive_cdr_identity", ""),
            "exact_positive_id": row.get("exact_positive_id", ""),
            "leakage_status": row.get("leakage_status", ""),
            "abnativ_status": "SCORED",
            "abnativ_vhh_score": row.get("full_qc_AbNatiV_VHH_score", ""),
            "qc_recommendation": row.get("full_qc_recommendation", ""),
            "developability_score": row.get("full_qc_developability_score", ""),
            "expression_purity_risk_score": row.get("full_qc_expression_purity_risk_score", ""),
            "gravy": row.get("full_qc_GRAVY", ""),
            "pi": row.get("full_qc_pI", ""),
            "instability_index": row.get("full_qc_instability_index", ""),
            "net_charge_ph7": row.get("full_qc_net_charge_pH7", ""),
            "unusual_cysteine": row.get("full_qc_has_unusual_cysteine", ""),
            "n_glycosylation_motif": row.get("full_qc_has_N_glycosylation_motif", ""),
            "deamidation_risk_count": row.get("full_qc_deamidation_risk_count", ""),
            "oxidation_risk_count": row.get("full_qc_oxidation_risk_count", ""),
            "isomerization_risk_count": row.get("full_qc_isomerization_risk_count", ""),
            "clipping_risk_count": row.get("full_qc_clipping_risk_count", ""),
            "max_cdr_hydrophobic_run": row.get("max_cdr_hydrophobic_run", ""),
            "tnp_status": "NOT_RUN",
            "tnp_flags": row.get("full_qc_TNP_flags", ""),
            "generic_prior_status": "AVAILABLE_WEAK_PRIOR",
            "generic_binding_prior": row.get("generic_binding_prior", ""),
            "generic_prior_uncertainty": row.get("model_uncertainty", ""),
            "generic_prior_disagreement": row.get("model_disagreement", ""),
            "generic_prior_claim_boundary": row.get("model_claim_boundary", ""),
            "monomer_status": "FROZEN_NBB2_SEQUENCE_VERIFIED",
            "monomer_sha256": monomer["sha256"],
            "monomer_residue_count": monomer["residue_count"],
            "monomer_sequence_match": "true",
            "structure_crosscheck_status": "PENDING_SECOND_MONOMER_METHOD",
            "geometry_campaign": "V4D_FULLQC290_2022_JOB",
            "geometry_status": "RUNNING_PENDING_CANDIDATE_AGGREGATE",
            "full_sequence_cluster": row.get("parent_framework_cluster", ""),
            "cdr3_cluster": "",
            "angle_family": "PENDING_V4D_POSE_AGGREGATE",
            "shortlist_eligibility": "ELIGIBLE_PRIMARY_PENDING_V4D_GEOMETRY",
            "final_submission_eligibility": "PENDING_V4D_GEOMETRY_AND_PORTFOLIO_FREEZE",
            "shortlist_blockers": "",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    )
    if split["sequence_sha256"] != output["sequence_sha256"]:
        raise ValueError(f"FullQC/split sequence mismatch: {output['candidate_id']}")
    return output


def dual_row(
    row: dict[str, str],
    prior: dict[str, str],
    support: dict[str, str],
    monomer: dict[str, str],
) -> dict[str, str]:
    backbone_group, backbone_index, mpnn_index = parse_design_indices(row["candidate_id"])
    output = blank_row()
    output.update(
        {
            "candidate_id": row["candidate_id"],
            "sequence": row["sequence"],
            "sequence_sha256": row["sequence_sha256"],
            "source_cohort": "DUAL128_SECONDARY",
            "source_rank": row.get("panel_rank", ""),
            "scaffold_id": row.get("scaffold_id", ""),
            "arm_id": row.get("arm_id", ""),
            "phase": support.get("phase", ""),
            "h3_regime": row.get("h3_regime", ""),
            "backbone_group_id": row.get("backbone_group_id", backbone_group),
            "backbone_index": backbone_index,
            "mpnn_index": mpnn_index,
            "cdr1": row.get("cdr1", ""),
            "cdr2": row.get("cdr2", ""),
            "cdr3": row.get("cdr3", ""),
            "cdr3_length": str(len(row.get("cdr3", ""))),
            "near_cdr3_family_id": row.get("near_cdr3_family_id", ""),
            "fast_gate_tier": prior.get("fast_gate_tier", ""),
            "fast_hard_fail": row.get("qc_hard_fail", ""),
            "full_qc_status": "NOT_RUN_EQUIVALENT_FULLQC290_SCHEMA",
            "max_positive_cdr_identity": prior.get("max_positive_cdr_identity", ""),
            "leakage_status": "NO_EXACT_SEQUENCE_OVERLAP_WITH_FULLQC290_OR_CONTROLS",
            "abnativ_status": "NOT_AVAILABLE_EQUIVALENT_SCHEMA",
            "qc_recommendation": row.get("qc_recommendation", ""),
            "tnp_status": "NOT_RUN",
            "generic_prior_status": "AVAILABLE_WEAK_PRIOR",
            "generic_binding_prior": prior.get("generic_binding_prior", ""),
            "generic_prior_uncertainty": prior.get("model_uncertainty", ""),
            "generic_prior_disagreement": prior.get("model_disagreement", ""),
            "generic_prior_claim_boundary": prior.get("model_claim_boundary", ""),
            "monomer_status": "FROZEN_V3_SEQUENCE_VERIFIED",
            "monomer_sha256": monomer["sha256"],
            "monomer_residue_count": monomer["residue_count"],
            "monomer_sequence_match": "true",
            "structure_crosscheck_status": "NBB2_GEOMETRY_VALIDATED_30_SUBSET_ONLY",
            "geometry_campaign": "DUAL128_V3_1050_JOB",
            "geometry_status": "AVAILABLE_DISCRETE_MULTI_SEED_SUPPORT",
            "geometry_support_class": support.get("support_class", ""),
            "supporting_seeds_8x6b": support.get("supporting_seeds_8x6b", ""),
            "supporting_seeds_9e6y": support.get("supporting_seeds_9e6y", ""),
            "successful_seeds_8x6b": support.get("successful_seeds_8x6b", ""),
            "successful_seeds_9e6y": support.get("successful_seeds_9e6y", ""),
            "full_sequence_cluster": row.get("backbone_group_id", backbone_group),
            "cdr3_cluster": row.get("near_cdr3_family_id", ""),
            "angle_family": "PENDING_COMMON_SCHEMA_POSE_CLUSTERING",
            "shortlist_eligibility": "INELIGIBLE_PENDING_EQUIVALENT_FULL_QC_AND_LINEAGE",
            "final_submission_eligibility": "INELIGIBLE_CURRENT_EVIDENCE_SCHEMA",
            "shortlist_blockers": "EQUIVALENT_FULL_QC_MISSING;COMPLETE_DESIGN_LINEAGE_MISSING",
            "claim_boundary": CLAIM_BOUNDARY,
        }
    )
    for source in (prior, support, monomer):
        if source["sequence_sha256"] != output["sequence_sha256"]:
            raise ValueError(f"Dual128 sequence mismatch: {output['candidate_id']}")
    return output


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def write_schema(path: Path) -> None:
    fields = []
    for name in FIELDS:
        fields.append(
            {
                "name": name,
                "axis": FIELD_AXIS[name],
                "storage_type": "string",
                "missing_policy": "empty means not available or not yet generated; status fields explain why",
            }
        )
    payload = {
        "schema_version": "pvrig_candidate_evidence_master_v1",
        "primary_key": "candidate_id",
        "sequence_identity_key": "sequence_sha256",
        "field_count": len(FIELDS),
        "fields": fields,
        "geometry_continuous_fields_pending_v4d": [
            "r_8x6b", "r_9e6y", "r_dual_mean", "r_dual_min", "r_dual_gap",
            "geometry_uncertainty", "native_cross_agreement", "model_pair_consensus",
        ],
        "fullqc290_cdr3_cluster": {
            "algorithm": "single_link_connected_components",
            "distance": "Levenshtein_distance/max_length",
            "maximum_distance": 0.2,
            "cluster_id": "sha256(sorted member sequence_sha256) prefix",
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def run(args: argparse.Namespace) -> dict[str, Any]:
    full_rows = read_rows(args.fullqc, ",")
    split = indexed(read_rows(args.v4d_split, "\t"))
    dual_rows = read_rows(args.dual, "\t")
    prior = indexed(read_rows(args.dual_prior, ","))
    support = indexed(read_rows(args.dual_support, "\t"))
    v4d_monomers = indexed(read_rows(args.v4d_monomers, "\t"))
    dual_monomers = indexed(read_rows(args.dual_monomers, "\t"))
    full = indexed(full_rows)
    dual = indexed(dual_rows)

    expected_sets = {
        "fullqc_split": set(full) == set(split) == set(v4d_monomers),
        "dual_sources": set(dual) == set(prior) == set(support) == set(dual_monomers),
        "cross_cohort_id_overlap_zero": not (set(full) & set(dual)),
    }
    if not all(expected_sets.values()):
        raise ValueError(f"source closure failed: {expected_sets}")

    rows = [fullqc_row(row, split[row["candidate_id"]], v4d_monomers[row["candidate_id"]]) for row in full_rows]
    cdr3_cluster_sizes = assign_cdr3_clusters(rows)
    rows += [dual_row(row, prior[row["candidate_id"]], support[row["candidate_id"]], dual_monomers[row["candidate_id"]]) for row in dual_rows]
    if len(rows) != 418 or len({row["candidate_id"] for row in rows}) != 418:
        raise ValueError("evidence master must contain 418 unique candidate IDs")
    if len({row["sequence_sha256"] for row in rows}) != 418:
        raise ValueError("evidence master sequences are not unique")
    for row in rows:
        if sha256_text(row["sequence"]) != row["sequence_sha256"]:
            raise ValueError(f"sequence hash mismatch: {row['candidate_id']}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    master_path = args.outdir / "candidate_evidence_master.tsv"
    schema_path = args.outdir / "candidate_evidence_schema.json"
    audit_path = args.outdir / "candidate_evidence_lineage_audit.json"
    write_tsv(master_path, rows)
    write_schema(schema_path)

    full_out = [row for row in rows if row["source_cohort"] == "FULLQC290_PRIMARY"]
    dual_out = [row for row in rows if row["source_cohort"] == "DUAL128_SECONDARY"]
    audit = {
        "schema_version": "pvrig_candidate_evidence_lineage_audit_v1",
        "status": "PASS_INITIAL_MASTER_V4D_GEOMETRY_PENDING",
        "row_count": len(rows),
        "cohort_counts": dict(Counter(row["source_cohort"] for row in rows)),
        "source_closure": expected_sets,
        "sequence_hash_verified_count": len(rows),
        "unique_candidate_id_count": len({row["candidate_id"] for row in rows}),
        "unique_sequence_sha256_count": len({row["sequence_sha256"] for row in rows}),
        "fullqc290": {
            "rows": len(full_out),
            "model_split_counts": dict(Counter(split[row["candidate_id"]]["model_split"] for row in full_out)),
            "parent_cluster_count": len({row["parent_framework_cluster"] for row in full_out}),
            "patch_counts": dict(Counter(row["target_patch_id"] for row in full_out)),
            "design_mode_counts": dict(Counter(row["design_mode"] for row in full_out)),
            "cdr3_cluster_count": len(cdr3_cluster_sizes),
            "maximum_cdr3_cluster_size": max(cdr3_cluster_sizes.values()),
            "full_qc_complete_count": sum(row["full_qc_status"] == "COMPLETE_HARD_PASS_ABNATIV_COMPLETE" for row in full_out),
            "generic_prior_available_count": sum(bool(row["generic_binding_prior"]) for row in full_out),
            "frozen_monomer_count": sum(bool(row["monomer_sha256"]) for row in full_out),
            "v4d_geometry_pending_count": sum(row["geometry_status"].startswith("RUNNING_PENDING") for row in full_out),
        },
        "dual128": {
            "rows": len(dual_out),
            "support_class_counts": dict(Counter(row["geometry_support_class"] for row in dual_out)),
            "generic_prior_available_count": sum(bool(row["generic_binding_prior"]) for row in dual_out),
            "frozen_monomer_count": sum(bool(row["monomer_sha256"]) for row in dual_out),
            "equivalent_full_qc_missing_count": sum(row["full_qc_status"].startswith("NOT_RUN") for row in dual_out),
            "current_shortlist_eligible_count": sum(row["shortlist_eligibility"].startswith("ELIGIBLE") for row in dual_out),
        },
        "sources": {
            name: {"path": str(path), "sha256": sha256_file(path)}
            for name, path in {
                "fullqc290_lineage": args.fullqc,
                "v4d_split": args.v4d_split,
                "dual128_source": args.dual,
                "dual128_generic_prior": args.dual_prior,
                "dual128_support": args.dual_support,
                "v4d_monomers": args.v4d_monomers,
                "dual128_monomers": args.dual_monomers,
            }.items()
        },
        "outputs": {
            "master": {"path": str(master_path), "sha256": sha256_file(master_path)},
            "schema": {"path": str(schema_path), "sha256": sha256_file(schema_path)},
        },
        "next_update": "merge fresh V4-D candidate continuous geometry after terminal evaluator PASS",
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fullqc", type=Path, default=DEFAULT_FULLQC)
    parser.add_argument("--v4d-split", type=Path, default=DEFAULT_V4D_SPLIT)
    parser.add_argument("--dual", type=Path, default=DEFAULT_DUAL)
    parser.add_argument("--dual-prior", type=Path, default=DEFAULT_PRIOR)
    parser.add_argument("--dual-support", type=Path, default=DEFAULT_DUAL_SUPPORT)
    parser.add_argument("--v4d-monomers", type=Path, default=DEFAULT_V4D_MONOMERS)
    parser.add_argument("--dual-monomers", type=Path, default=DEFAULT_DUAL_MONOMERS)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main() -> int:
    audit = run(parse_args())
    print(json.dumps({"status": audit["status"], "rows": audit["row_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
