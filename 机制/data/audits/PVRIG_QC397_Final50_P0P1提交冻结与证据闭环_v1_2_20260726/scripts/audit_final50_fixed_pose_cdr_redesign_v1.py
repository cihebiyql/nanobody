#!/usr/bin/env python3
"""Prove that Final50 fixed-pose ProteinMPNN candidates designed H1/H2/H3.

The audit is fail-closed: every fixed_pose_mpnn Final50 row must resolve to one
frozen generation record, one H1/H2/H3 task, and a generated PDB.  The worker
and RFantibody mask implementation are hashed so "all three CDRs redesigned"
means all residues labelled H1/H2/H3 were designable, while framework and
target residues were fixed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--joined-tsv", required=True, type=Path)
    parser.add_argument("--generation-root", required=True, type=Path)
    parser.add_argument("--rfantibody-root", required=True, type=Path)
    parser.add_argument("--output-tsv", required=True, type=Path)
    parser.add_argument("--receipt-json", required=True, type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_gzip_tsv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("refusing to write empty fixed-pose audit")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=list(rows[0]),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    frozen_candidates = sorted(
        (args.generation_root / "data").glob(
            "fixed_pose_candidates_frozen*.tsv.gz"
        )
    )
    assert len(frozen_candidates) == 1, (
        f"expected exactly one fixed-pose freeze TSV, found {frozen_candidates}"
    )
    frozen_path = frozen_candidates[0]
    tasks_path = args.generation_root / "inputs/fixed_pose_mpnn_tasks.tsv"
    parent_cdr_path = args.generation_root / "inputs/positive11_cdr_imgt.tsv"
    worker_path = args.generation_root / "scripts/run_fixed_pose_mpnn_worker.sh"
    mask_code_path = (
        args.rfantibody_root
        / "src/rfantibody/proteinmpnn/sample_features.py"
    )
    for path in (
        args.joined_tsv,
        frozen_path,
        tasks_path,
        parent_cdr_path,
        worker_path,
        mask_code_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)

    joined = [
        row for row in read_tsv(args.joined_tsv)
        if row["route"] == "fixed_pose_mpnn"
    ]
    assert len(joined) == 15
    frozen_rows = read_gzip_tsv(frozen_path)
    frozen_by_hash = {row["sequence_sha256"]: row for row in frozen_rows}
    assert len(frozen_by_hash) == len(frozen_rows)
    task_by_pose = {row["pose_id"]: row for row in read_tsv(tasks_path)}
    parents = {row["record_id"]: row for row in read_tsv(parent_cdr_path)}

    worker_text = worker_path.read_text(encoding="utf-8")
    mask_text = mask_code_path.read_text(encoding="utf-8")
    assert "-loop_string H1,H2,H3" in worker_text
    assert "loop_string2fixed_res(args.loop_string)" in (
        args.rfantibody_root / "scripts/proteinmpnn_interface_design.py"
    ).read_text(encoding="utf-8")
    assert "create a dict of residues which should be designed by ProteinMPNN" in (
        mask_text
    )
    assert 'loopH += self.pose.cdr_dict[loop]' in mask_text
    assert "idxH.remove(res)" in mask_text

    output_rows: list[dict[str, Any]] = []
    for joined_row in joined:
        source = frozen_by_hash[joined_row["sequence_sha256"]]
        assert source["sequence"] == joined_row["sequence"]
        assert source["candidate_id"] in joined_row["candidate_id"]
        assert source["route_id"] == "fixed_pose_mpnn"
        assert source["designed_regions"] == "cdr1,cdr2,cdr3"
        task = task_by_pose[source["pose_id"]]
        assert task["loop_string"] == "H1,H2,H3"
        assert task["cdr_label_status"] == "EXACT_SEQUENCE_MATCH_3_OF_3"
        assert task["source_candidate_id"] == source["source_candidate_id"]
        parent = parents[source["parent_id"]]
        output_pdb = Path(source["output_pdb"])
        assert output_pdb.is_file()
        assert source["fast_qc_status"] == "PASS"

        cdr_diffs = {}
        for index in (1, 2, 3):
            after = source[f"cdr{index}_after"]
            before = parent[f"cdr{index}"]
            assert after
            assert before
            assert after != before
            cdr_diffs[f"cdr{index}_parent"] = before
            cdr_diffs[f"cdr{index}_after"] = after
            cdr_diffs[f"cdr{index}_changed_from_parent"] = "true"

        evidence_payload = {
            "joined_candidate_id": joined_row["candidate_id"],
            "source_generation_candidate_id": source["candidate_id"],
            "pose_id": source["pose_id"],
            "designed_regions": source["designed_regions"],
            "loop_string": task["loop_string"],
            "cdr_label_status": task["cdr_label_status"],
            "sequence_sha256": source["sequence_sha256"],
            "output_pdb_sha256": sha256(output_pdb),
            **cdr_diffs,
        }
        evidence_sha256 = hashlib.sha256(
            json.dumps(
                evidence_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        output_rows.append(
            {
                "submission_id": joined_row["submission_id"],
                "candidate_id": joined_row["candidate_id"],
                "source_generation_candidate_id": source["candidate_id"],
                "pose_id": source["pose_id"],
                "parent_id": source["parent_id"],
                "designed_regions": source["designed_regions"],
                "loop_string": task["loop_string"],
                "cdr_label_status": task["cdr_label_status"],
                "cdr1_fully_redesigned": "true",
                "cdr2_fully_redesigned": "true",
                "cdr3_fully_redesigned": "true",
                **cdr_diffs,
                "sequence_sha256": source["sequence_sha256"],
                "output_pdb": str(output_pdb),
                "output_pdb_sha256": sha256(output_pdb),
                "audit_verdict": "PASS_ALL_THREE_CDRS_REDESIGNED",
                "mask_semantics": (
                    "H1/H2/H3 residues are designable; non-loop VHH residues "
                    "and target chain are fixed by loop_string2fixed_res"
                ),
                "evidence_path": (
                    f"{frozen_path};{tasks_path};{worker_path};"
                    f"{mask_code_path};{output_pdb}"
                ),
                "evidence_sha256": evidence_sha256,
            }
        )

    output_rows.sort(key=lambda row: row["submission_id"])
    assert len({row["candidate_id"] for row in output_rows}) == 15
    write_tsv(args.output_tsv, output_rows)

    receipt = {
        "schema_version": "pvrig_final50_fixed_pose_cdr_redesign_audit_v1",
        "state": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "records": 15,
        "verdict_counts": {
            "PASS_ALL_THREE_CDRS_REDESIGNED": 15,
        },
        "inputs": {
            str(path): sha256(path)
            for path in (
                args.joined_tsv,
                frozen_path,
                tasks_path,
                parent_cdr_path,
                worker_path,
                mask_code_path,
            )
        },
        "output": {
            str(args.output_tsv): sha256(args.output_tsv),
        },
        "assertions": {
            "current_final50_fixed_pose_membership_exact_15": True,
            "all_records_resolve_to_frozen_generation_row": True,
            "all_tasks_use_H1_H2_H3_loop_mask": True,
            "mask_implementation_marks_all_H1_H2_H3_residues_designable": True,
            "all_output_pdbs_exist": True,
            "all_three_output_cdrs_differ_from_parent_15_of_15": True,
        },
        "claim_boundary": (
            "Proves the ProteinMPNN design mask covered all H1/H2/H3 residues "
            "and the frozen output came from that run. It does not prove binding, "
            "blocking, expression, purity, Kd, or IC50."
        ),
    }
    args.receipt_json.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_json.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
