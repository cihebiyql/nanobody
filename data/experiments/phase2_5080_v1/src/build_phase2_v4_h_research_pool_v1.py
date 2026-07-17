#!/usr/bin/env python3
"""Build the provenance-closed V4-H research pool from the completed 1,440 run.

This is a research-routing artifact. It does not change the frozen formal QC96
holdout and it never edits or repairs a source sequence in place.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


STANDARD_AA = set("ACDEFGHIKLMNPQRSTVWY")
CLAIM_BOUNDARY = (
    "Research routing for computational PVRIG-PVRL2 blocker-like geometry only; "
    "not binding, affinity, competition, experimental blocking, or Docking Gold."
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"empty_rows:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_fasta(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")


def unique_by(rows: list[dict[str, str]], key: str, label: str) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = row.get(key, "")
        if not value:
            raise RuntimeError(f"missing_{key}:{label}")
        if value in result:
            raise RuntimeError(f"duplicate_{key}:{label}:{value}")
        result[value] = row
    return result


def research_state(
    candidate: dict[str, str], state: dict[str, str], full: dict[str, str]
) -> tuple[str, str]:
    source_state = state["full_qc_state"]
    if source_state == "HARD_PASS":
        return "RESEARCH_READY", "source_full_qc_hard_pass"
    if (
        source_state == "HARD_FAIL"
        and state["parent_framework_cluster"] == "C0371"
        and full["official_validator_failed_reason"] == "missing_n_terminal"
    ):
        return (
            "QUARANTINE_REPAIRABLE_PARENT_N_TERMINUS",
            "C0371_family_requires_new_versioned_N_terminal_review_or_repair",
        )
    return "QUARANTINE_OTHER_QC", full.get("reason_summary", "source_full_qc_hard_fail")


def build(source_mirror: Path, outdir: Path) -> dict[str, object]:
    inputs = {
        "candidates": source_mirror / "candidates1440.tsv",
        "candidate_qc_states": source_mirror / "candidate_qc_states.tsv",
        "full_merged": source_mirror / "full_merged.tsv",
        "generation_receipt": source_mirror / "generation_receipt.json",
        "formal_qc96_receipt": source_mirror / "formal_qc96_receipt.json",
    }
    for label, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"missing_input:{label}:{path}")

    candidates = read_tsv(inputs["candidates"])
    states = unique_by(read_tsv(inputs["candidate_qc_states"]), "candidate_id", "states")
    full = unique_by(read_tsv(inputs["full_merged"]), "candidate_id", "full")
    candidate_by_id = unique_by(candidates, "candidate_id", "candidates")

    if len(candidates) != 1440:
        raise RuntimeError(f"candidate_count:{len(candidates)}")
    if set(candidate_by_id) != set(states) or set(candidate_by_id) != set(full):
        raise RuntimeError("candidate_state_full_id_set_mismatch")

    seen_sequences: set[str] = set()
    output_rows: list[dict[str, object]] = []
    for candidate in candidates:
        candidate_id = candidate["candidate_id"]
        sequence = candidate["sequence"].strip().upper()
        digest = sha256_text(sequence)
        if not sequence or set(sequence) - STANDARD_AA:
            raise RuntimeError(f"invalid_sequence:{candidate_id}")
        if digest != candidate["sequence_sha256"]:
            raise RuntimeError(f"sequence_sha256_mismatch:{candidate_id}")
        if sequence in seen_sequences:
            raise RuntimeError(f"duplicate_sequence:{candidate_id}")
        seen_sequences.add(sequence)

        state = states[candidate_id]
        full_row = full[candidate_id]
        if state["sequence_sha256"] != digest or full_row["sequence"] != sequence:
            raise RuntimeError(f"cross_artifact_sequence_mismatch:{candidate_id}")
        if state["parent_framework_cluster"] != candidate["parent_framework_cluster"]:
            raise RuntimeError(f"cross_artifact_parent_mismatch:{candidate_id}")

        pool_state, routing_reason = research_state(candidate, state, full_row)
        output_rows.append(
            {
                "candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": digest,
                "sequence_length": len(sequence),
                "parent_id": candidate["parent_id"],
                "parent_framework_cluster": candidate["parent_framework_cluster"],
                "parent_queue_rank": candidate["parent_queue_rank"],
                "target_patch_id": candidate["target_patch_id"],
                "design_mode": candidate["design_mode"],
                "cdr1_after": candidate["cdr1_after"],
                "cdr2_after": candidate["cdr2_after"],
                "cdr3_after": candidate["cdr3_after"],
                "cdr3_length": candidate["cdr3_length"],
                "source_full_qc_state": state["full_qc_state"],
                "official_validator_pass": full_row["official_validator_pass"],
                "official_validator_failed_reason": full_row[
                    "official_validator_failed_reason"
                ],
                "source_reason_summary": full_row["reason_summary"],
                "source_recommendation": full_row["recommendation"],
                "AbNatiV_VHH_score": full_row["AbNatiV_VHH_score"],
                "GRAVY": full_row["GRAVY"],
                "pI": full_row["pI"],
                "instability_index": full_row["instability_index"],
                "developability_score": full_row["developability_score"],
                "novelty_margin_flag": full_row["novelty_margin_flag"],
                "research_pool_state": pool_state,
                "research_routing_reason": routing_reason,
                "monomer_structure_eligible": str(pool_state == "RESEARCH_READY").lower(),
                "docking_eligible_after_monomer_qc": str(
                    pool_state == "RESEARCH_READY"
                ).lower(),
                "sequence_repaired": "false",
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )

    ready = [r for r in output_rows if r["research_pool_state"] == "RESEARCH_READY"]
    quarantine = [r for r in output_rows if r["research_pool_state"] != "RESEARCH_READY"]
    state_counts = Counter(str(r["research_pool_state"]) for r in output_rows)
    if state_counts != {
        "RESEARCH_READY": 1320,
        "QUARANTINE_REPAIRABLE_PARENT_N_TERMINUS": 120,
    }:
        raise RuntimeError(f"unexpected_research_state_counts:{dict(state_counts)}")

    outputs = outdir / "outputs"
    write_tsv(outputs / "research_pool1440_manifest.tsv", output_rows)
    write_tsv(outputs / "research_ready1320.tsv", ready)
    write_fasta(outputs / "research_ready1320.fasta", ready)
    write_tsv(outputs / "quarantine_c0371_120.tsv", quarantine)
    write_fasta(outputs / "quarantine_c0371_120.fasta", quarantine)

    audit: dict[str, object] = {
        "schema_version": "phase2_v4_h_research_pool_v1",
        "status": "PASS_RESEARCH_POOL_1320_READY_120_VERSIONED_REPAIR_QUARANTINE",
        "built_at_utc": now(),
        "input_candidate_count": len(output_rows),
        "exact_unique_sequence_count": len(seen_sequences),
        "research_pool_state_counts": dict(sorted(state_counts.items())),
        "ready_parent_counts": dict(
            sorted(Counter(str(r["parent_framework_cluster"]) for r in ready).items())
        ),
        "ready_patch_counts": dict(
            sorted(Counter(str(r["target_patch_id"]) for r in ready).items())
        ),
        "ready_design_mode_counts": dict(
            sorted(Counter(str(r["design_mode"]) for r in ready).items())
        ),
        "quarantine_parent_counts": dict(
            sorted(Counter(str(r["parent_framework_cluster"]) for r in quarantine).items())
        ),
        "quarantine_failed_reason_counts": dict(
            sorted(
                Counter(
                    str(r["official_validator_failed_reason"]) for r in quarantine
                ).items()
            )
        ),
        "formal_qc96_boundary": (
            "The frozen 96 is a prospective formal holdout subset and is not the "
            "research-pool size or a cap on downstream monomer/docking work."
        ),
        "c0371_policy": {
            "source_sequence_mutated": False,
            "source_hash_reused_for_repair": False,
            "disposition": "quarantine pending evidence-based, versioned N-terminal review/repair",
            "release_requirement": (
                "new candidate IDs, new sequence SHA256 values, explicit donor/rule provenance, "
                "and exact sequence/structure validation"
            ),
        },
        "input_hashes": {name: sha256_file(path) for name, path in inputs.items()},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path = outdir / "research_pool_audit_v1.json"
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    output_paths = sorted(p for p in outputs.iterdir() if p.is_file())
    receipt = {
        "schema_version": "phase2_v4_h_research_pool_receipt_v1",
        "status": audit["status"],
        "published_at_utc": now(),
        "audit_sha256": sha256_file(audit_path),
        "output_hashes": {
            str(path.relative_to(outdir)): sha256_file(path) for path in output_paths
        },
        "input_hashes": audit["input_hashes"],
        "claim_boundary": CLAIM_BOUNDARY,
    }
    receipt_path = outdir / "research_pool_receipt_v1.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-mirror", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source_mirror, args.outdir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
