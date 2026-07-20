from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src/run_sequence_stage0_expanded_v2_9.py"
SPEC = importlib.util.spec_from_file_location("v29_stage0", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def fixture_rows() -> list[dict[str, str]]:
    rows = []
    parents = ["P00", "P01", "P02", "P03", "P04", "P05"]
    aa = MOD.AA
    for index in range(18):
        parent = parents[index // 3]
        cdr1 = "ACDE" + aa[index % len(aa)]
        cdr2 = "FGHI" + aa[(index + 3) % len(aa)]
        cdr3 = "KLMNPQ" + aa[(index + 7) % len(aa)]
        sequence = "QVQLVESGGGLVQSGGSLRLSCAAS" + cdr1 + "WYRQAPGKERELVA" + cdr2 + "RFTISRDFSRSTMYLQMNSLKPEDTAIYYCAA" + cdr3 + "WGQGTQVTVSS"
        r8 = 0.40 + index * 0.008
        r9 = 0.42 + ((index * 7) % 18) * 0.006
        rows.append({
            "candidate_id": f"C{index:03d}",
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "sequence": sequence,
            "parent_framework_cluster": parent,
            "cdr1": cdr1,
            "cdr2": cdr2,
            "cdr3": cdr3,
            "sample_weight": "1.0",
            "R_8X6B": f"{r8:.9f}",
            "R_9E6Y": f"{r9:.9f}",
            "R_dual_min": f"{min(r8, r9):.9f}",
            "teacher_source": "FIXTURE",
            "teacher_reliability": "DUAL_1_SEED",
        })
    return rows


def make_cache(root: Path, name: str, rows: list[dict[str, str]], width: int) -> Path:
    cache = root / name
    shards = cache / "shards"
    shards.mkdir(parents=True)
    ids = [row["candidate_id"] for row in rows] + ["EXTRA_LABEL_FREE"]
    hashes = [row["sequence_sha256"] for row in rows] + ["f" * 64]
    values = torch.arange(len(ids) * width, dtype=torch.float32).reshape(len(ids), width) / 100.0
    shard = shards / "shard_00000.pt"
    torch.save({
        "metadata": {"candidate_ids": ids, "sequence_sha256": hashes},
        "embeddings": values,
    }, shard)
    receipt = {
        "schema_version": "pvrig_v6_esm_embedding_cache_v1",
        "rows": len(ids),
        "shards": [{"path": str(shard), "sha256": MOD.sha256_file(shard)}],
    }
    (cache / "embedding_cache_receipt.json").write_text(json.dumps(receipt))
    return cache


def make_fixture(root: Path, data_version: str = "D1") -> dict[str, Path | str]:
    rows = fixture_rows()
    teacher = root / f"teacher_{data_version}.tsv"
    write_tsv(teacher, rows)
    teacher_sha = MOD.sha256_file(teacher)
    train_parents = ["P00", "P01", "P02", "P03"]
    score_parents = ["P04", "P05"]
    frozen_test_parents = ["P90", "P91"]
    split = root / f"split_{data_version}.json"
    split.write_text(json.dumps({
        "schema_version": MOD.SPLIT_SCHEMA,
        "data_version": data_version,
        "split_id": f"fixture_{data_version}",
        "open_only": True,
        "frozen_test_access_count": 0,
        "sealed_truth_access_count": 0,
        "training_tsv_sha256": teacher_sha,
        "train_parents": train_parents,
        "score_parents": score_parents,
        "frozen_test_parents": frozen_test_parents,
        "train_parent_set_sha256": MOD.stable_parent_hash(train_parents),
        "score_parent_set_sha256": MOD.stable_parent_hash(score_parents),
        "frozen_test_parent_set_sha256": MOD.stable_parent_hash(frozen_test_parents),
        "expected_total_rows": 18,
        "expected_train_rows": 12,
        "expected_score_rows": 6,
    }))
    return {
        "teacher": teacher,
        "teacher_sha": teacher_sha,
        "split": split,
        "cache650": make_cache(root, "cache650", rows, 9),
        "cache3b": make_cache(root, "cache3b", rows, 13),
    }


class V29Stage0Tests(unittest.TestCase):
    def test_seed_parser_contract(self):
        self.assertEqual(MOD.parse_seeds("43,97,193"), (43, 97, 193))
        for value in ("", "43,43", "43,-1", "abc"):
            with self.assertRaises(RuntimeError):
                MOD.parse_seeds(value)

    def test_exact_min(self):
        values = np.asarray([[0.5, 0.4], [0.2, 0.7]])
        np.testing.assert_allclose(MOD.exact_min(values), [0.4, 0.2])

    def test_forbidden_paths_fail_closed(self):
        for value in ("/tmp/frozen_test/a", "/tmp/sealed/a", "/tmp/test32/a"):
            with self.assertRaises(RuntimeError):
                MOD.reject_forbidden_path(Path(value), "fixture")

    def test_variable_rows_and_extra_embedding_cache_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = make_fixture(Path(tmp), "D0")
            preflight, rows, split, cache650, cache3b, _, _ = MOD.build_preflight(
                fixture["teacher"], fixture["teacher_sha"], fixture["split"], "D0",
                fixture["cache650"], fixture["cache3b"], (43, 97, 193),
            )
            self.assertEqual(len(rows), 18)
            self.assertEqual(len(cache650), 19)
            self.assertEqual(len(cache3b), 19)
            self.assertEqual(preflight["train_rows"], 12)
            self.assertEqual(preflight["score_rows"], 6)
            self.assertEqual(split["data_version"], "D0")

    def test_data_version_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = make_fixture(Path(tmp), "D0")
            with self.assertRaisesRegex(RuntimeError, "data_version_mismatch"):
                MOD.load_rows(fixture["teacher"], fixture["split"], fixture["teacher_sha"], "D1")

    def test_parent_closure_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root, "D1")
            payload = json.loads(Path(fixture["split"]).read_text())
            payload["score_parents"] = ["P04", "P99"]
            payload["score_parent_set_sha256"] = MOD.stable_parent_hash(payload["score_parents"])
            Path(fixture["split"]).write_text(json.dumps(payload))
            with self.assertRaisesRegex(RuntimeError, "partition_parent_closure"):
                MOD.load_rows(fixture["teacher"], fixture["split"], fixture["teacher_sha"], "D1")

    def test_frozen_parent_metadata_overlap_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root, "D1")
            payload = json.loads(Path(fixture["split"]).read_text())
            payload["frozen_test_parents"] = ["P03", "P90"]
            payload["frozen_test_parent_set_sha256"] = MOD.stable_parent_hash(payload["frozen_test_parents"])
            Path(fixture["split"]).write_text(json.dumps(payload))
            with self.assertRaisesRegex(RuntimeError, "train_frozen_parent_overlap"):
                MOD.load_rows(fixture["teacher"], fixture["split"], fixture["teacher_sha"], "D1")

    def test_dry_run_is_non_destructive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root, "D1")
            output = root / "output"
            preflight = root / "preflight.json"
            command = [
                sys.executable, str(MODULE_PATH),
                "--training-tsv", str(fixture["teacher"]),
                "--expected-training-tsv-sha256", str(fixture["teacher_sha"]),
                "--split-manifest", str(fixture["split"]),
                "--expected-data-version", "D1",
                "--esm2-650m-cache", str(fixture["cache650"]),
                "--esm2-3b-cache", str(fixture["cache3b"]),
                "--output-dir", str(output),
                "--seeds", "43,97,193",
                "--dry-run",
                "--preflight-json", str(preflight),
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=True)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "PASS_PREFLIGHT")
            self.assertFalse(output.exists())
            self.assertTrue(preflight.is_file())

    def test_end_to_end_three_seed_four_model_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = make_fixture(root, "D1")
            output = root / "output"
            command = [
                sys.executable, str(MODULE_PATH),
                "--training-tsv", str(fixture["teacher"]),
                "--expected-training-tsv-sha256", str(fixture["teacher_sha"]),
                "--split-manifest", str(fixture["split"]),
                "--expected-data-version", "D1",
                "--esm2-650m-cache", str(fixture["cache650"]),
                "--esm2-3b-cache", str(fixture["cache3b"]),
                "--output-dir", str(output),
                "--seeds", "43,97,193",
                "--ridge-alphas", "1",
            ]
            result = subprocess.run(command, text=True, capture_output=True, check=True)
            self.assertEqual(json.loads(result.stdout)["status"], "PASS_MULTISEED_COMPLETE")
            summary = json.loads((output / "MULTISEED_SUMMARY.json").read_text())
            self.assertEqual(summary["seeds"], [43, 97, 193])
            self.assertEqual(summary["model_names"], list(MOD.MODEL_NAMES))
            self.assertFalse(any("MLP" in name or "MEAN" in name for name in summary["model_names"]))
            for seed in (43, 97, 193):
                seed_result = json.loads((output / f"seed_{seed}" / "RESULT.json").read_text())
                self.assertEqual(seed_result["model_names"], list(MOD.MODEL_NAMES))
                self.assertEqual(seed_result["train_rows"], 12)
                self.assertEqual(seed_result["score_rows"], 6)
                for model in MOD.MODEL_NAMES:
                    self.assertEqual(seed_result["metrics"][model]["exact_min_violation_count"], 0)


if __name__ == "__main__":
    unittest.main()
