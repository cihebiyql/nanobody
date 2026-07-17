#!/usr/bin/env python3
"""Publish V4-H H4 after the frozen H2/H3 run hit a TSV provenance bug.

This recovery is deliberately narrow: it reuses the exact frozen H1 candidates,
completed H2/H3 QC tables, and frozen H4 hash selection.  It does not rerun QC,
change a gate, replace a candidate, or read model/Docking/experimental labels.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CANONICAL_SOURCE_ROOT = Path(
    "/data1/qlyu/projects/pvrig_v4_h_qc96_h0_h3_v1_20260717"
)
CANONICAL_RECOVERY_ROOT = Path(
    "/data1/qlyu/projects/pvrig_v4_h_qc96_h2_h4_recovery_v1_1_20260717"
)
CLAIM = (
    "Sequence/developability QC-qualified prospective candidate panel only; "
    "not Docking geometry, binding, affinity, competition, experimental blocking, or Docking Gold."
)
SELECTION_SEED = "phase2_v4_h_h4_fullqc_hash_selection_v1_20260717"

SOURCE_HASHES = {
    "IMPLEMENTATION_FREEZE.json": "dab2f0dedc845fe3e415bf77bc7ca3281ed14bcaee1caf0bcacd60ca5fcd9209",
    "config/generation_config.json": "4ae7e1a4536dd09e842dd0cc8a678b4f080d04b63b42151fbeb4c5e7feb971c6",
    "scripts/run_phase2_v4_h_qc96_qc_node1.py": "f77af186ee548e68712b0e17efb634478add89582c825cadfe5f5cb0d4c67b89",
    "outputs/v4_h_h1_generation_receipt.json": "5863d6cdae14b08132cec8a3c7fec13c2b4a1096a48e8f86698470dc47dfe341",
    "outputs/v4_h_h1_generation_audit.json": "6f5d70c68144e0a6c618a5b8c9ce3297b9b2229d2289f8da2bcda668d3b109af",
    "outputs/v4_h_h1_candidates1440.tsv": "aa111562b9204aadc9b0bda4f92bc39310e07c8f9eb0d8656dcd9db0f09d4ad7",
    "outputs/v4_h_h1_candidates1440.fasta": "5d5bf7033b8040c817810abec10df212635c76d77a3cdcce3eb413d2f428bc30",
    "status/generation.complete.json": "548ea2c091b29d8ce494e1f1ce8a7aa01a3f7a41323de3571997c32235b8ac92",
    "status/qc.failed.json": "78073a919fc0a5a15c22f4299350efc0bb8581d7212924609433c350173f5dc6",
    "qc/cascade/cascade_state.json": "c44ba8c03836390bf3bc302e35a48a289bc818b5b00bdb06efdbd5114c424d7e",
    "qc/cascade/fast_merged.tsv": "1e9ddb2f2f2809a2bc4d1e054c3a00e97ba669f40c8b28377bfdf1d80ac2a37b",
    "qc/cascade/full_qc_shortlist.tsv": "1e9ddb2f2f2809a2bc4d1e054c3a00e97ba669f40c8b28377bfdf1d80ac2a37b",
    "qc/cascade/full_merged.tsv": "40d5fe960654cc0282bcaba866d745e4b7be6dee9dda85dc9d496f8e4ee5cf34",
    "qc/outputs/v4_h_h2_h3_candidate_qc_states.tsv": "1dce3fa8accd0801436c2fa274133fe756b77993720e87941f1a2267726ef09c",
    "qc/outputs/v4_h_h3_parent_capacity.tsv": "5ee50d05b83d5c072c8e5e9d97b80f6e80666399be6018c1007e525fad6aaf0e",
}
MARKER_BINDINGS = {
    "fast": (24, "ea39c5129e9615dd4f9144bc8d0a1a193e596c7b924be93e5880a55d3486c4da"),
    "full": (24, "3189da34ed5cad0d0a7fec75900b3aac881179db7251c7eed42edfa4a6db9b0a"),
}
SOURCE_H4_ABSENT = (
    "qc/outputs/qc96_manifest_v1.tsv",
    "qc/outputs/qc96_audit_v1.json",
    "qc/outputs/qc96_receipt_v1.json",
    "status/qc.complete.json",
)
CORE_MANIFEST_FIELDS = [
    "candidate_id", "sequence_sha256", "sequence", "parent_id", "parent_framework_cluster",
    "parent_queue_rank", "target_patch_id", "design_mode", "cdr1_after", "cdr2_after", "cdr3_after",
    "cdr3_length", "h4_selection_hash", "h4_selection_rank_in_stratum", "selection_stratum", "model_split",
    "tnp_supervision_state", "tnp_score", "tnp_red_flag", "tnp_yellow_flag", "full_qc_and_docking_policy",
    "claim_boundary",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        return list(reader.fieldnames or []), list(reader)


def union_fields(base: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return a deterministic base-first union for the provenance sidecar only."""
    fields = list(dict.fromkeys(base))
    seen = set(fields)
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    return fields


def project_rows(
    rows: Sequence[Mapping[str, Any]], fields: Sequence[str]
) -> list[dict[str, Any]]:
    """Project rows onto an exact schema, dropping non-schema provenance fields."""
    projected: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        missing = [field for field in fields if field not in row]
        if missing:
            raise RuntimeError(f"projection_missing_fields:{index}:{','.join(missing)}")
        projected.append({field: row[field] for field in fields})
    return projected


def validate_manifest_semantics(rows: Sequence[Mapping[str, Any]]) -> None:
    empty_tnp_fields = ("tnp_score", "tnp_red_flag", "tnp_yellow_flag")
    nonempty_fields = [field for field in CORE_MANIFEST_FIELDS if field not in empty_tnp_fields]
    for index, row in enumerate(rows):
        if any(str(row[field]).strip() == "" for field in nonempty_fields):
            raise RuntimeError(f"manifest_required_value_empty:{index}")
        if row["tnp_supervision_state"] != "NOT_RUN_DEFERRED_NA":
            raise RuntimeError(f"manifest_tnp_state_changed:{index}")
        if any(row[field] != "" for field in empty_tnp_fields):
            raise RuntimeError(f"manifest_tnp_na_not_empty:{index}")


def atomic_tsv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refuse_overwrite:{path}")
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=path.parent, delete=False) as handle:
        tmp = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=list(fields), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(tmp, 0o444)
    os.replace(tmp, path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refuse_overwrite:{path}")
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    fd, name = tempfile.mkstemp(dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o444)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def marker_set_digest(source_root: Path, stage: str) -> tuple[int, str]:
    paths = sorted((source_root / f"qc/cascade/{stage}_chunks").glob("chunk_*/complete.json"))
    lines = [f"{path.relative_to(source_root)}\t{sha256(path)}" for path in paths]
    digest = hashlib.sha256((("\n".join(lines) + "\n") if lines else "").encode()).hexdigest()
    return len(paths), digest


def hard_pass(row: Mapping[str, str]) -> bool:
    value = str(row.get("hard_fail", "")).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"invalid_hard_fail:{row.get('candidate_id', '')}:{value}")
    return value == "false"


def compute_h4_capacity(
    candidates: Sequence[Mapping[str, str]], full_by_id: Mapping[str, Mapping[str, str]],
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[str(row["parent_framework_cluster"])].append(row)
    capacity: list[dict[str, Any]] = []
    ready: list[tuple[int, str]] = []
    for parent, rows in grouped.items():
        queue_rank = {int(row["parent_queue_rank"]) for row in rows}
        if len(queue_rank) != 1:
            raise RuntimeError(f"parent_queue_rank_inconsistent:{parent}")
        strata: dict[tuple[str, str], list[Mapping[str, str]]] = defaultdict(list)
        full_pass_count = 0
        for row in rows:
            cid = str(row["candidate_id"])
            full = full_by_id.get(cid)
            if full is not None and hard_pass(full):
                full_pass_count += 1
                strata[(str(row["target_patch_id"]), str(row["design_mode"]))].append(row)
        counts = {
            (patch, mode): len(strata.get((patch, mode), []))
            for patch in ("A_CENTER", "B_LOWER", "C_CROSS")
            for mode in ("H3", "H1H3")
        }
        is_ready = full_pass_count >= 24 and len(strata) == 6 and min(counts.values()) >= 4
        rank = next(iter(queue_rank))
        state = "QC_CAPACITY_READY" if is_ready else "INSUFFICIENT_QC_CAPACITY"
        if is_ready:
            ready.append((rank, parent))
        capacity.append({
            "parent_queue_rank": rank,
            "parent_framework_cluster": parent,
            "full_qc_hard_pass_count": full_pass_count,
            **{f"full_pass_{patch}_{mode}": counts[(patch, mode)] for patch, mode in counts},
            "capacity_state": state,
        })
    capacity.sort(key=lambda row: int(row["parent_queue_rank"]))
    ready.sort()
    return capacity, ready


def h4_select(
    candidates: Sequence[Mapping[str, str]], full_by_id: Mapping[str, Mapping[str, str]], seed: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in candidates:
        grouped[str(row["parent_framework_cluster"])].append(row)
    capacity, ready = compute_h4_capacity(candidates, full_by_id)
    if len(ready) < 4:
        raise RuntimeError(f"FAIL_V4_H_INSUFFICIENT_QC_QUALIFIED_PARENT_CAPACITY:{len(ready)}")
    selected_parents = {parent for _, parent in ready[:4]}
    selected: list[dict[str, Any]] = []
    for parent in sorted(selected_parents, key=lambda value: next(rank for rank, item in ready if item == value)):
        parent_rows = grouped[parent]
        for patch in ("A_CENTER", "B_LOWER", "C_CROSS"):
            for mode in ("H3", "H1H3"):
                rows = [
                    dict(row) for row in parent_rows
                    if row["target_patch_id"] == patch and row["design_mode"] == mode
                    and hard_pass(full_by_id[str(row["candidate_id"])])
                ]
                for row in rows:
                    row["h4_selection_hash"] = sha256_text(
                        "|".join((seed, str(row["candidate_id"]), str(row["sequence_sha256"])))
                    )
                rows.sort(key=lambda row: (row["h4_selection_hash"], row["candidate_id"]))
                if len(rows) < 4:
                    raise RuntimeError(f"selected_parent_stratum_lt4:{parent}:{patch}:{mode}")
                for rank, row in enumerate(rows[:4], 1):
                    row["h4_selection_rank_in_stratum"] = rank
                    row["selection_stratum"] = f"{parent}|{patch}|{mode}"
                    row["model_split"] = "V4_H_QC96_PROSPECTIVE_HOLDOUT"
                    row["tnp_supervision_state"] = "NOT_RUN_DEFERRED_NA"
                    row["tnp_score"] = ""
                    row["tnp_red_flag"] = ""
                    row["tnp_yellow_flag"] = ""
                    row["full_qc_and_docking_policy"] = (
                        "frozen_after_label_free_full_qc;no_model_reselection;no_replacement;"
                        "independent_dual_receptor_docking_only_after_prediction_freeze"
                    )
                    row["claim_boundary"] = CLAIM
                    selected.append(row)
    selected.sort(key=lambda row: (
        int(row["parent_queue_rank"]), row["target_patch_id"], row["design_mode"],
        int(row["h4_selection_rank_in_stratum"]),
    ))
    if len(selected) != 96 or len({row["candidate_id"] for row in selected}) != 96:
        raise RuntimeError("h4_96_id_closure_failed")
    if Counter(row["parent_framework_cluster"] for row in selected) != Counter({parent: 24 for parent in selected_parents}):
        raise RuntimeError("h4_4x24_parent_closure_failed")
    strata = Counter(row["selection_stratum"] for row in selected)
    if len(strata) != 24 or set(strata.values()) != {4}:
        raise RuntimeError("h4_24x4_stratum_closure_failed")
    return selected, capacity


class Recovery:
    def __init__(self, source_root: Path, recovery_root: Path, enforce_canonical: bool = True):
        self.source = source_root.resolve()
        self.recovery = recovery_root.resolve()
        self.enforce_canonical = enforce_canonical

    def validate(self) -> dict[str, Any]:
        if self.enforce_canonical and (
            self.source != CANONICAL_SOURCE_ROOT or self.recovery != CANONICAL_RECOVERY_ROOT
        ):
            raise RuntimeError("noncanonical_recovery_paths")
        if self.source == self.recovery or self.source in self.recovery.parents or self.recovery in self.source.parents:
            raise RuntimeError("source_recovery_path_overlap")
        for rel, expected in SOURCE_HASHES.items():
            path = self.source / rel
            if not path.is_file() or path.is_symlink() or sha256(path) != expected:
                raise RuntimeError(f"source_hash_mismatch:{rel}")
        for stage, expected in MARKER_BINDINGS.items():
            if marker_set_digest(self.source, stage) != expected:
                raise RuntimeError(f"{stage}_marker_set_mismatch")
        if any((self.source / rel).exists() for rel in SOURCE_H4_ABSENT):
            raise RuntimeError("source_h4_outputs_no_longer_absent")

        old_failure = json.loads((self.source / "status/qc.failed.json").read_text())
        if old_failure.get("status") != "FAIL_V4_H_H2_H3_OR_H4" or "fields not in fieldnames" not in old_failure.get("error", ""):
            raise RuntimeError("unexpected_old_failure")
        receipt = json.loads((self.source / "outputs/v4_h_h1_generation_receipt.json").read_text())
        if receipt.get("status") != "PASS_V4_H_H1_1440_EXACT_UNIQUE_GENERATED":
            raise RuntimeError("h1_receipt_not_pass")
        if receipt.get("outputs", {}).get("v4_h_h1_candidates1440.tsv") != SOURCE_HASHES["outputs/v4_h_h1_candidates1440.tsv"]:
            raise RuntimeError("h1_receipt_manifest_hash_mismatch")
        if receipt.get("outputs", {}).get("v4_h_h1_candidates1440.fasta") != SOURCE_HASHES["outputs/v4_h_h1_candidates1440.fasta"]:
            raise RuntimeError("h1_receipt_fasta_hash_mismatch")
        config = json.loads((self.source / "config/generation_config.json").read_text())
        if config.get("qc", {}).get("h4_selection_seed") != SELECTION_SEED:
            raise RuntimeError("selection_seed_mismatch")
        if any(int(value) != 0 for value in config.get("label_path_access", {}).values()):
            raise RuntimeError("label_path_access_nonzero")

        source_fields, candidates = read_tsv(self.source / "outputs/v4_h_h1_candidates1440.tsv")
        _, fast = read_tsv(self.source / "qc/cascade/fast_merged.tsv")
        _, shortlist = read_tsv(self.source / "qc/cascade/full_qc_shortlist.tsv")
        _, full = read_tsv(self.source / "qc/cascade/full_merged.tsv")
        if len(candidates) != 1440 or len({row["candidate_id"] for row in candidates}) != 1440:
            raise RuntimeError("h1_candidate_closure_failed")
        source_by = {row["candidate_id"]: row for row in candidates}
        for label, rows in (("fast", fast), ("shortlist", shortlist), ("full", full)):
            if len(rows) != 1440 or {row["candidate_id"] for row in rows} != set(source_by):
                raise RuntimeError(f"{label}_id_closure_failed")
            if any(
                row["sequence"] != source_by[row["candidate_id"]]["sequence"]
                or sha256_text(row["sequence"]) != source_by[row["candidate_id"]]["sequence_sha256"]
                for row in rows
            ):
                raise RuntimeError(f"{label}_sequence_closure_failed")
        if sum(hard_pass(row) for row in fast) != 1440:
            raise RuntimeError("fast_pass_count_changed")
        if sum(hard_pass(row) for row in full) != 1320 or sum(not hard_pass(row) for row in full) != 120:
            raise RuntimeError("full_attrition_changed")
        full_by = {row["candidate_id"]: row for row in full}
        selected, capacity = h4_select(candidates, full_by, SELECTION_SEED)
        return {
            "source_fields": source_fields,
            "candidates": candidates,
            "full_by": full_by,
            "selected": selected,
            "capacity": capacity,
            "ready_parents": [
                row["parent_framework_cluster"] for row in capacity if row["capacity_state"] == "QC_CAPACITY_READY"
            ],
            "label_path_access": config["label_path_access"],
        }

    def run(self) -> dict[str, Any]:
        context = self.validate()
        if self.recovery.exists() and any(self.recovery.iterdir()):
            raise RuntimeError("recovery_root_not_empty")
        self.recovery.mkdir(parents=True, exist_ok=True)
        lock_path = self.recovery / "recovery.lock"
        lock = lock_path.open("x")
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        selected = context["selected"]
        manifest_fields = list(CORE_MANIFEST_FIELDS)
        manifest_rows = project_rows(selected, CORE_MANIFEST_FIELDS)
        validate_manifest_semantics(manifest_rows)
        manifest_path = self.recovery / "qc96_manifest_v1.tsv"
        atomic_tsv(manifest_path, manifest_rows, manifest_fields)
        fields, replay = read_tsv(manifest_path)
        if fields != CORE_MANIFEST_FIELDS or len(replay) != 96:
            raise RuntimeError("manifest_replay_closure_failed")
        if any(set(row) != set(CORE_MANIFEST_FIELDS) for row in replay):
            raise RuntimeError("manifest_schema_expansion_detected")

        provenance_fields = union_fields(context["source_fields"], selected)
        provenance_path = self.recovery / "qc96_selected_source_provenance_v1.tsv"
        atomic_tsv(provenance_path, selected, provenance_fields)
        provenance_replay_fields, provenance_replay = read_tsv(provenance_path)
        if provenance_replay_fields != provenance_fields or len(provenance_replay) != 96:
            raise RuntimeError("provenance_sidecar_replay_closure_failed")
        source_by = {row["candidate_id"]: row for row in context["candidates"]}
        for row in provenance_replay:
            original = source_by[row["candidate_id"]]
            if any(row.get(field, "") != original.get(field, "") for field in context["source_fields"]):
                raise RuntimeError(f"provenance_replay_mismatch:{row['candidate_id']}")

        selected_parents = sorted(
            {row["parent_framework_cluster"] for row in replay},
            key=lambda parent: min(int(row["parent_queue_rank"]) for row in replay if row["parent_framework_cluster"] == parent),
        )
        audit = {
            "schema_version": "phase2_v4_h_qc96_h2_h4_manifest_recovery_audit_v1_1",
            "status": "PASS_V4_H_QC96_FROZEN_AFTER_LABEL_FREE_FULL_QC",
            "recovery_status": "PASS_V4_H_QC96_H4_MANIFEST_RECOVERED",
            "recovery_scope": (
                "H4_CORE_MANIFEST_EXPLICIT_PROJECTION_PLUS_SEPARATE_PROVENANCE_SIDECAR_ONLY"
            ),
            "source_root": str(self.source),
            "supersedes_v1_pre_scientific_failure_receipt_sha256": (
                "00c9645821158c0b48784261f9ed32f64479ab0696376f5e55f64830791be439"
            ),
            "source_hashes": SOURCE_HASHES,
            "source_marker_bindings": {
                stage: {"count": value[0], "set_sha256": value[1]} for stage, value in MARKER_BINDINGS.items()
            },
            "old_failure_preserved": {
                "path": str(self.source / "status/qc.failed.json"),
                "sha256": SOURCE_HASHES["status/qc.failed.json"],
            },
            "input_rows": 1440,
            "fast_hard_pass": 1440,
            "full_rows": 1440,
            "full_hard_pass": 1320,
            "full_hard_fail": 120,
            "qc_capacity_ready_parent_count": len(context["ready_parents"]),
            "selected_rows": 96,
            "selected_parent_count": 4,
            "selected_parents": selected_parents,
            "selected_per_parent": 24,
            "selected_per_stratum": 4,
            "selection_seed": SELECTION_SEED,
            "no_qc_rerun": True,
            "no_gate_change": True,
            "no_candidate_change": True,
            "no_replacement": True,
            "no_model_or_docking_reselection": True,
            "tnp_run": False,
            "tnp_policy": "DEFERRED_THREE_STATE_NA_NO_IMPUTATION",
            "manifest_field_count": len(CORE_MANIFEST_FIELDS),
            "manifest_fields": CORE_MANIFEST_FIELDS,
            "formal_manifest_schema_expanded": False,
            "source_provenance_fields_preserved_in_sidecar": context["source_fields"],
            "provenance_sidecar_fields": provenance_fields,
            "label_path_access": context["label_path_access"],
            "outputs": {
                "qc96_manifest_v1.tsv": sha256(manifest_path),
                "qc96_selected_source_provenance_v1.tsv": sha256(provenance_path),
            },
            "claim_boundary": CLAIM,
        }
        audit_path = self.recovery / "qc96_audit_v1.json"
        atomic_json(audit_path, audit)
        receipt = {
            **audit,
            "schema_version": "phase2_v4_h_qc96_h2_h4_manifest_recovery_receipt_v1_1",
            "recovery_status": "PASS_V4_H_QC96_H4_MANIFEST_RECOVERY_VALIDATED",
            "published_at_utc": now(),
            "audit_sha256": sha256(audit_path),
            "receipt_publication_order": "LAST_AFTER_SOURCE_HASH_ID_SEQUENCE_SELECTION_AND_PROVENANCE_REPLAY_CLOSURE",
        }
        receipt_path = self.recovery / "qc96_receipt_v1.json"
        atomic_json(receipt_path, receipt)
        complete = {
            "schema_version": "phase2_v4_h_qc96_h2_h4_manifest_recovery_terminal_v1_1",
            "status": receipt["status"],
            "recovery_status": receipt["recovery_status"],
            "finished_at_utc": now(),
            "manifest_sha256": sha256(manifest_path),
            "audit_sha256": sha256(audit_path),
            "receipt_sha256": sha256(receipt_path),
            "claim_boundary": CLAIM,
        }
        atomic_json(self.recovery / "recovery.complete.json", complete)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
        return complete


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=CANONICAL_SOURCE_ROOT)
    parser.add_argument("--recovery-root", type=Path, default=CANONICAL_RECOVERY_ROOT)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    recovery = Recovery(args.source_root, args.recovery_root, enforce_canonical=True)
    if args.preflight:
        context = recovery.validate()
        result = {
            "status": "PASS_V4_H_H2_H4_RECOVERY_V1_1_PREFLIGHT",
            "selected_rows": len(context["selected"]),
            "selected_ids_sha256": sha256_text("\n".join(row["candidate_id"] for row in context["selected"]) + "\n"),
            "ready_parent_count": len(context["ready_parents"]),
            "source_root": str(recovery.source),
            "recovery_root": str(recovery.recovery),
            "claim_boundary": CLAIM,
        }
    else:
        result = recovery.run()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
