#!/usr/bin/env python3
"""Fail-closed audit for the P2/P3/P4 next-generation decision.

This audit deliberately keeps the V4-C fixed128 phase experiment separate from
the V4-D/V4-E open258 campaign.  It authorizes no sequence generation unless
the frozen P2/P3/P4 enrichment report itself is eligible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


EXPECTED_PHASE_COUNTS = {
    "P1": 22,
    "P2": 21,
    "P3": 24,
    "P4": 23,
    "P5": 23,
    "P6": 15,
}
EXPECTED_OPEN_SPLITS = {"OPEN_TRAIN": 226, "OPEN_DEVELOPMENT": 32}


class AuditError(RuntimeError):
    """Raised when a frozen input violates the audit contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [
            {key: "" if value is None else value for key, value in row.items()}
            for row in csv.DictReader(handle, delimiter="\t")
        ]


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AuditError(f"json_root_not_object:{path}")
    return payload


def unique_map(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            raise AuditError(f"missing_{key}:{label}")
        if value in output:
            raise AuditError(f"duplicate_{key}:{label}:{value}")
        output[value] = row
    return output


def build_audit(
    *,
    v4c_manifest: Path,
    v4d_manifest: Path,
    v4e_teacher: Path,
    evaluator: Path,
    enrichment: Path,
    enrichment_tsv: Path,
) -> dict[str, Any]:
    paths = {
        "v4c_manifest": v4c_manifest,
        "v4d_manifest": v4d_manifest,
        "v4e_teacher": v4e_teacher,
        "v3_evaluator": evaluator,
        "v3_enrichment": enrichment,
        "v3_enrichment_tsv": enrichment_tsv,
    }
    missing = [f"missing_input:{name}:{path}" for name, path in paths.items() if not path.is_file()]
    if missing:
        raise AuditError(",".join(missing))

    v4c = read_tsv(v4c_manifest)
    v4d = read_tsv(v4d_manifest)
    teacher = read_tsv(v4e_teacher)
    evaluator_payload = read_json(evaluator)
    enrichment_payload = read_json(enrichment)

    if len(v4c) != 128:
        raise AuditError(f"v4c_candidate_count_not_128:{len(v4c)}")
    phase_counts = Counter(row.get("phase", "") for row in v4c)
    if dict(phase_counts) != EXPECTED_PHASE_COUNTS:
        raise AuditError(f"v4c_phase_counts_mismatch:{dict(phase_counts)}")

    open_v4d = [
        row for row in v4d
        if row.get("model_split") in EXPECTED_OPEN_SPLITS
    ]
    open_split_counts = Counter(row.get("model_split", "") for row in open_v4d)
    if dict(open_split_counts) != EXPECTED_OPEN_SPLITS:
        raise AuditError(f"v4d_open_split_counts_mismatch:{dict(open_split_counts)}")
    if len(teacher) != 258:
        raise AuditError(f"v4e_teacher_count_not_258:{len(teacher)}")

    open_by_id = unique_map(open_v4d, "candidate_id", "v4d_open")
    teacher_by_id = unique_map(teacher, "candidate_id", "v4e_teacher")
    if set(open_by_id) != set(teacher_by_id):
        raise AuditError("v4e_teacher_candidate_set_not_equal_v4d_open")
    hash_mismatches = sorted(
        candidate_id
        for candidate_id in open_by_id
        if open_by_id[candidate_id].get("sequence_sha256")
        != teacher_by_id[candidate_id].get("sequence_sha256")
    )
    if hash_mismatches:
        raise AuditError(f"v4e_teacher_sequence_hash_mismatch:{len(hash_mismatches)}")

    v4c_ids = {row["candidate_id"] for row in v4c}
    v4c_hashes = {row["sequence_sha256"] for row in v4c}
    v4d_ids = set(open_by_id)
    v4d_hashes = {row["sequence_sha256"] for row in open_v4d}
    id_overlap = sorted(v4c_ids & v4d_ids)
    hash_overlap = sorted(v4c_hashes & v4d_hashes)
    if id_overlap or hash_overlap:
        raise AuditError(
            f"unexpected_v4c_v4d_identity_overlap:ids={len(id_overlap)}:hashes={len(hash_overlap)}"
        )

    gates = evaluator_payload.get("gates", {})
    evaluator_pass = (
        evaluator_payload.get("status") == "PASS"
        and evaluator_payload.get("unlockable") is True
        and isinstance(gates, dict)
        and bool(gates)
        and all(item.get("status") == "PASS" for item in gates.values())
    )
    if not evaluator_pass:
        raise AuditError("v3_evaluator_not_stable_pass")

    eligible_phases = enrichment_payload.get("eligible_phases", [])
    enrichment_failed_closed = (
        enrichment_payload.get("status") == "FAIL"
        and enrichment_payload.get("unlockable") is False
        and eligible_phases == []
        and enrichment_payload.get("candidate_call_counts", {}).get("total_candidates") == 128
        and enrichment_payload.get("candidate_call_counts", {}).get("evaluable_candidates") == 128
    )
    if not enrichment_failed_closed:
        raise AuditError("v3_enrichment_not_expected_fail_closed_state")

    phase_results = enrichment_payload.get("phase_results", [])
    if {row.get("phase") for row in phase_results} != {"P2", "P3", "P4"}:
        raise AuditError("v3_enrichment_phase_set_mismatch")

    return {
        "schema_version": "pvrig_p2p3p4_lineage_gate_audit_v1",
        "status": "PASS_FAIL_CLOSED_AUDIT",
        "decision": "BLOCKED_NO_RELIABLE_P2_P3_P4_ENRICHMENT",
        "new_sequence_generation_authorized": False,
        "reasons": [
            "v3_evaluator_is_stable_but_no_p2_p3_p4_phase_passed_the_frozen_enrichment_gate",
            "v4e_open258_is_a_distinct_zero_identity_overlap_campaign_without_p1_p6_labels",
            "v4e_patch_or_design_mode_must_not_be_relabelled_as_p2_p3_p4",
        ],
        "v3_fixed128": {
            "candidate_count": len(v4c),
            "phase_counts": dict(sorted(phase_counts.items())),
            "evaluator_status": evaluator_payload.get("status"),
            "evaluator_unlockable": evaluator_payload.get("unlockable"),
            "enrichment_status": enrichment_payload.get("status"),
            "eligible_phases": eligible_phases,
            "phase_results": phase_results,
        },
        "v4e_open258": {
            "candidate_count": len(teacher),
            "model_split_counts": dict(sorted(Counter(row["model_split"] for row in teacher).items())),
            "candidate_id_closure_with_v4d_open": len(teacher_by_id),
            "sequence_sha256_closure_with_v4d_open": len(teacher_by_id) - len(hash_mismatches),
            "available_design_axes": {
                "target_patch_id": dict(sorted(Counter(row["target_patch_id"] for row in teacher).items())),
                "design_mode": dict(sorted(Counter(row["design_mode"] for row in teacher).items())),
            },
        },
        "cross_campaign_identity": {
            "v4c_candidate_id_overlap_v4d_open": len(id_overlap),
            "v4c_sequence_sha256_overlap_v4d_open": len(hash_overlap),
            "p1_p6_mapping_closure_for_v4e_open258": 0,
            "mapping_denominator": 258,
        },
        "source_bindings": {
            name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for name, path in paths.items()
        },
        "claim_boundary": (
            "Computational docking-geometry campaign audit only. It does not establish binding, "
            "affinity, competition, or experimental blocking."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v4c-manifest", type=Path, required=True)
    parser.add_argument("--v4d-manifest", type=Path, required=True)
    parser.add_argument("--v4e-teacher", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--enrichment", type=Path, required=True)
    parser.add_argument("--enrichment-tsv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = build_audit(
        v4c_manifest=args.v4c_manifest,
        v4d_manifest=args.v4d_manifest,
        v4e_teacher=args.v4e_teacher,
        evaluator=args.evaluator,
        enrichment=args.enrichment,
        enrichment_tsv=args.enrichment_tsv,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "decision": payload["decision"],
        "new_sequence_generation_authorized": payload["new_sequence_generation_authorized"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
