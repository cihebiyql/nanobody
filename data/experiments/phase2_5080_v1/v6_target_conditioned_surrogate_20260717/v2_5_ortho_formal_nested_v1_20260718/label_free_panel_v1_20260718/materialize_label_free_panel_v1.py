#!/usr/bin/env python3
"""Materialize the exact five-column open1507 label-free replay panel."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path


FIELDS = ["candidate_id", "sequence", "sequence_sha256", "parent_framework_cluster", "outer_fold"]
AA = set("ACDEFGHIKLMNPQRSTVWY")


class PanelError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PanelError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(temporary, path)


def materialize(source: Path, output_dir: Path, expected_source_sha256: str) -> dict:
    normalized = str(source).lower().replace("-", "_")
    require("v4_f" not in normalized and "test32" not in normalized, "sealed_source_forbidden")
    require(source.is_file() and not source.is_symlink(), "source_missing_or_symlink")
    observed = sha256_file(source)
    require(observed == expected_source_sha256, f"source_sha256:{observed}")
    require(not output_dir.exists(), "output_dir_exists")

    with source.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        require(reader.fieldnames is not None and set(FIELDS) <= set(reader.fieldnames), "source_fields_missing")
        rows = []
        seen = set()
        parent_fold: dict[str, int] = {}
        for raw in reader:
            row = {field: raw[field].strip() for field in FIELDS}
            candidate_id = row["candidate_id"]
            sequence = row["sequence"]
            require(candidate_id and candidate_id not in seen, f"candidate_duplicate:{candidate_id}")
            require(sequence and set(sequence) <= AA, f"sequence_invalid:{candidate_id}")
            require(hashlib.sha256(sequence.encode()).hexdigest() == row["sequence_sha256"], f"sequence_hash:{candidate_id}")
            fold = int(row["outer_fold"])
            require(0 <= fold < 5, f"outer_fold:{candidate_id}")
            parent = row["parent_framework_cluster"]
            require(parent, f"parent_empty:{candidate_id}")
            if parent in parent_fold:
                require(parent_fold[parent] == fold, f"parent_cross_fold:{parent}")
            parent_fold[parent] = fold
            seen.add(candidate_id)
            row["outer_fold"] = str(fold)
            rows.append(row)

    require(len(rows) == 1507, f"row_count:{len(rows)}")
    require(len(parent_fold) == 31, f"parent_count:{len(parent_fold)}")
    require(set(parent_fold.values()) == set(range(5)), "outer_fold_coverage")

    output_dir.mkdir(parents=True)
    panel = output_dir / "open1507_label_free_replay_panel.tsv"
    with panel.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with panel.open(newline="") as handle:
        require(csv.DictReader(handle, delimiter="\t").fieldnames == FIELDS, "output_schema_not_exact")

    receipt = {
        "schema_version": "pvrig_v2_5_open1507_label_free_replay_panel_v1",
        "status": "PASS_EXACT_FIVE_COLUMN_LABEL_FREE_PANEL",
        "source": {"path": str(source), "sha256": observed},
        "output": {"path": str(panel), "sha256": sha256_file(panel), "fields": FIELDS},
        "rows": len(rows),
        "parents": len(parent_fold),
        "outer_folds": 5,
        "teacher_fields_emitted": 0,
        "v4_f_test32_access_count": 0,
        "claim_boundary": "Label-free sequence/parent/fold replay index only; no Docking teacher or experimental truth.",
    }
    atomic_json(output_dir / "PANEL_RECEIPT.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = materialize(args.source, args.output_dir, args.expected_source_sha256)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
