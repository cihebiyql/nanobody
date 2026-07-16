#!/usr/bin/env python3
"""Validate the honest three-state TNP plus IgFold100 Deep-QC delivery."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


EXPECTED_STATES = {
    "VALID_TNP": 85,
    "TNP_NUMBERING_HARD_FAIL_NA": 7,
    "UPSTREAM_L2_HARD_FAIL_NA": 8,
}
TNP_NUMERIC_FIELDS = ("tnp_PSH", "tnp_PPC", "tnp_PNC")
TNP_FLAG_FIELDS = (
    "tnp_L_flag", "tnp_L3_flag", "tnp_C_flag",
    "tnp_PSH_flag", "tnp_PPC_flag", "tnp_PNC_flag",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_path(root: Path, text: str) -> Path:
    path = (root / text).resolve()
    require(path == root or root in path.parents, f"unsafe delivery path: {text}")
    return path


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def validate_tnp_rows(rows: list[dict[str, str]]) -> dict[str, int]:
    require(len(rows) == 100, f"unexpected TNP row count: {len(rows)}")
    ids = [row.get("id", "") for row in rows]
    require(len(set(ids)) == 100 and all(ids), "TNP ID closure failed")
    states = Counter(row.get("tnp_supervision_state", "") for row in rows)
    require(dict(states) == EXPECTED_STATES, f"TNP state partition mismatch: {dict(states)}")
    for row in rows:
        state = row["tnp_supervision_state"]
        values = [row.get(field, "") for field in TNP_NUMERIC_FIELDS]
        flags = [row.get(field, "") for field in TNP_FLAG_FIELDS]
        if state == "VALID_TNP":
            require(all(value not in {"", "NA", "N/A", "nan", "NaN"} for value in values),
                    f"valid TNP numeric value missing: {row['id']}")
            try:
                parsed = [float(value) for value in values]
            except ValueError as exc:
                raise ValueError(f"valid TNP numeric parse failed: {row['id']}") from exc
            require(all(math.isfinite(value) for value in parsed), f"valid TNP non-finite value: {row['id']}")
            require(all(flags), f"valid TNP flags missing: {row['id']}")
        else:
            require(all(value == "" for value in values), f"NA TNP numeric imputation forbidden: {row['id']}")
            require(all(value == "" for value in flags), f"NA TNP flag imputation forbidden: {row['id']}")
            require(row.get("tnp_result_json_sha256", "") != "" or state == "UPSTREAM_L2_HARD_FAIL_NA",
                    f"TNP numbering failure lacks null-JSON provenance: {row['id']}")
    return dict(states)


def validate_delivery(root: Path, exp: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    receipt = json.loads((root / "reports/deepqc_delivery_receipt_v1.json").read_text())
    require(receipt.get("status") == "PASS_DEEPQC100_DELIVERY_READY", "bad DeepQC receipt status")
    require(
        receipt.get("candidate_count") == 100
        and receipt.get("tnp_row_count") == 100
        and receipt.get("igfold_row_count") == 100
        and receipt.get("igfold_pdb_count") == 100,
        "bad DeepQC receipt counts",
    )
    require(receipt.get("tnp_state_counts") == EXPECTED_STATES, "receipt TNP state counts mismatch")
    manifest = root / "reports/delivery_file_manifest.tsv"
    require(sha256_file(manifest) == receipt.get("delivery_manifest_sha256"), "DeepQC manifest hash mismatch")
    rows = read_tsv(manifest)
    require(len(rows) == 111, f"unexpected DeepQC delivery manifest rows: {len(rows)}")
    for row in rows:
        target = safe_path(root, row["path"])
        require(target.is_file() and not target.is_symlink(), f"DeepQC file missing or symlink: {row['path']}")
        require(
            target.stat().st_size == int(row["bytes"]) and sha256_file(target) == row["sha256"],
            f"DeepQC file mismatch: {row['path']}",
        )
    tnp_rows = read_tsv(root / "reports/tnp_summary.tsv")
    state_counts = validate_tnp_rows(tnp_rows)
    igfold_rows = read_tsv(root / "reports/igfold_summary.tsv")
    require(len(igfold_rows) == 100 and len({row.get("id", "") for row in igfold_rows}) == 100,
            "IgFold summary closure failed")
    require({row["id"] for row in tnp_rows} == {row["id"] for row in igfold_rows},
            "TNP/IgFold ID parity failed")
    require(all(row.get("igfold_status") == "VALID_MONOMER_PREDICTION" for row in igfold_rows),
            "IgFold state mismatch")
    if exp is not None:
        exp = exp.resolve()
        expected = {
            "run_deepqc_sha256": exp / "prepared/pvrig_pre_shortlist100_deepqc_v1/run_deepqc.sh",
            "deepqc_config_sha256": exp / "prepared/pvrig_pre_shortlist100_deepqc_v1/deepqc_config.json",
            "input_audit_sha256": exp / "prepared/pvrig_pre_shortlist100_deepqc_v1/input_audit.json",
            "input_fasta_sha256": exp / "prepared/pvrig_pre_shortlist100_deepqc_v1/inputs/pre_shortlist100.fasta",
        }
        for field, path in expected.items():
            require(sha256_file(path) == receipt.get(field), f"DeepQC pinned source mismatch: {field}")
    return {
        "status": "PASS_THREE_STATE_TNP_IGFOLD100_DELIVERY",
        "candidate_count": 100,
        "tnp_state_counts": state_counts,
        "igfold_pdb_count": 100,
    }

