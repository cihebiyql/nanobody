#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


planner = load("v211_coarse_planner", ROOT / "src/prepare_full10644_coarse_pose_shards_v1.py")
merger = load("v211_coarse_merger", ROOT / "src/merge_full10644_coarse_pose_shards_v1.py")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields or list(rows[0]), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


class Full10644CoarsePoseShardingTests(unittest.TestCase):
    def make_fixture(self, root: Path, count: int = 20):
        rows = []
        for index in range(count):
            monomer = root / "monomers" / f"C{index:04d}.pdb"
            monomer.parent.mkdir(parents=True, exist_ok=True)
            monomer.write_text(f"fixture-{index}\n", encoding="ascii")
            rows.append({
                "schema_version": planner.INPUT_SCHEMA,
                "candidate_id": f"C{index:04d}",
                "sequence_sha256": hashlib.sha256(f"sequence-{index}".encode()).hexdigest(),
                "parent_framework_cluster": f"P{index // 2:03d}",
                "model_split": "train" if index < count - 4 else "development",
                "asset_lane": ("V29", "V4I", "V4H", "V4D")[index % 4],
                "monomer_path": str(monomer.resolve()),
                "monomer_sha256": sha256_file(monomer),
                "monomer_chain": "A",
                "cdr1_range": "2-4",
                "cdr2_range": "6-8",
                "cdr3_range": "10-13",
                "source_manifest_sha256": hashlib.sha256(f"source-{index % 4}".encode()).hexdigest(),
                "claim_boundary": "fixture",
            })
        structure = root / "canonical10644_structure_manifest_v1.tsv"
        write_tsv(structure, rows)
        targets = []
        for name in ("target_graph_cache_v2.npz", "pvrig_8x6b_chain_b.pdb", "pvrig_9e6y_chain_a.pdb"):
            path = root / "targets" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((name + "\n").encode())
            targets.append(path)
        return structure, targets

    def fake_shard_outputs(self, plan_path: Path, shard_output_root: Path, targets: list[Path]) -> None:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for shard in plan["shards"]:
            manifest = (plan_path.parent / shard["manifest_relative_path"]).resolve()
            with manifest.open(newline="", encoding="utf-8") as handle:
                manifest_rows = list(csv.DictReader(handle, delimiter="\t"))
            feature_rows = []
            for row_index, row in enumerate(manifest_rows):
                output = {
                    "candidate_id": row["candidate_id"],
                    "monomer_sha256": row["monomer_sha256"],
                    "feature_schema": merger.FEATURE_SCHEMA,
                }
                output.update({field: f"{field_index + row_index / 1000:.9f}"
                               for field_index, field in enumerate(merger.FEATURE_FIELDS)})
                feature_rows.append(output)
            shard_dir = shard_output_root / shard["shard_id"]
            feature_path = shard_dir / "coarse_pose_features_36d.tsv"
            write_tsv(feature_path, feature_rows, list(merger.OUTPUT_FIELDS))
            receipt = {
                "schema_version": merger.FROZEN_RECEIPT_SCHEMA,
                "status": merger.FROZEN_RECEIPT_STATUS,
                "candidate_count": len(feature_rows),
                "feature_count": 36,
                "pose_count_per_receptor": 300,
                "runtime_seconds": 1.0,
                "all_features_finite": True,
                "sealed_boundary": {
                    "candidate_docking_pose_files_opened": 0,
                    "teacher_label_files_opened": 0,
                    "v4_f_files_opened": 0,
                },
                "inputs": {
                    "candidate_manifest": {"path": str(manifest), "sha256": sha256_file(manifest)},
                    "target_npz": {"path": str(targets[0].resolve()), "sha256": sha256_file(targets[0])},
                    "target_pdb8": {"path": str(targets[1].resolve()), "sha256": sha256_file(targets[1])},
                    "target_pdb9": {"path": str(targets[2].resolve()), "sha256": sha256_file(targets[2])},
                },
                "outputs": {str(feature_path.resolve()): sha256_file(feature_path)},
            }
            (shard_dir / "FEATURE_RECEIPT.json").write_text(
                json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    def test_deterministic_16_shard_merge_closes_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            structure, targets = self.make_fixture(root)
            plan_dir = root / "plan"
            result = planner.prepare(structure, sha256_file(structure), plan_dir, 20, 16)
            self.assertEqual(result["shards"], 16)
            plan_path = plan_dir / "SHARD_PLAN.json"
            plan = json.loads(plan_path.read_text())
            self.assertEqual(sum(item["candidate_count"] for item in plan["shards"]), 20)
            self.assertEqual([item["candidate_count"] for item in plan["shards"]], [2] * 4 + [1] * 12)

            shard_output_root = root / "shard_outputs"
            self.fake_shard_outputs(plan_path, shard_output_root, targets)
            output_dir = root / "merged"
            merged = merger.merge(
                plan_path,
                sha256_file(plan_path),
                shard_output_root,
                targets[0], sha256_file(targets[0]),
                targets[1], sha256_file(targets[1]),
                targets[2], sha256_file(targets[2]),
                output_dir,
                20,
            )
            self.assertEqual(merged["rows"], 20)
            self.assertEqual(merged["features"], 36)
            with (output_dir / "canonical10644_coarse_pose_features_36d_v1.tsv").open() as handle:
                output_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual([row["candidate_id"] for row in output_rows], [f"C{i:04d}" for i in range(20)])
            receipt = json.loads(
                (output_dir / "canonical10644_coarse_pose_features_36d_v1.receipt.json").read_text()
            )
            self.assertEqual(receipt["status"], merger.READY_STATUS)
            self.assertTrue(receipt["invariants"]["all_shard_and_target_hashes_verified"])

    def test_target_hash_change_fails_before_merge_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            structure, targets = self.make_fixture(root)
            plan_dir = root / "plan"
            planner.prepare(structure, sha256_file(structure), plan_dir, 20, 16)
            plan_path = plan_dir / "SHARD_PLAN.json"
            shard_output_root = root / "shard_outputs"
            self.fake_shard_outputs(plan_path, shard_output_root, targets)
            expected_target_hash = sha256_file(targets[0])
            targets[0].write_bytes(b"tampered\n")
            output_dir = root / "merged"
            with self.assertRaisesRegex(merger.MergeError, "target_sha256_mismatch:target_npz"):
                merger.merge(
                    plan_path, sha256_file(plan_path), shard_output_root,
                    targets[0], expected_target_hash,
                    targets[1], sha256_file(targets[1]),
                    targets[2], sha256_file(targets[2]),
                    output_dir, 20,
                )
            self.assertFalse(output_dir.exists())


if __name__ == "__main__":
    unittest.main()
