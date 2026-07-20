from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "build_v29_open_snapshot_v1.py"
SPEC = importlib.util.spec_from_file_location("build_v29_open_snapshot_v1", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def sequence_sha(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def score_payload(value: float) -> dict[str, object]:
    hotspot = 8 + int(round(value * 10))
    holdout = 3 + int(round(value * 5))
    total = 100 + int(round(value * 500))
    cdr3 = 20 + int(round(value * 100))
    fraction = 0.10 + value * 0.10
    return {
        "hotspot_overlap": {"full": {"count": hotspot}, "holdout": {"count": holdout}},
        "vhh_pvrl2_occlusion": {
            "residue_pair_count": total,
            "by_vhh_region_pair_count": {"cdr3": cdr3},
            "cdr3_fraction": fraction,
        },
        "overlay": {"t_ca_rmsd_a": 0.0},
        "clashes_2p5a": {"vhh_pvrig": {"residue_pair_count": 1}},
    }


def result_payload(job: dict[str, str], value: float) -> dict[str, object]:
    poses = []
    for index in range(8):
        poses.append(
            {
                "pose": f"model_{index + 1}.pdb.gz",
                "haddock_io": {"score": -100.0 + index},
                "scores": [
                    {"reference_id": "8x6b", **score_payload(value)},
                    {"reference_id": "9e6y", **score_payload(value)},
                ],
            }
        )
    return {
        "state": "SUCCESS",
        "job_id": job["job_id"],
        "job_hash": job["job_hash"],
        "entity_id": job["entity_id"],
        "entity_type": "candidate",
        "dock_conformation": job["conformation"],
        "seed": int(job["seed"]),
        "protocol_core_sha256": job["protocol_core_sha256"],
        "selected_model_count": 8,
        "pose_scores": poses,
    }


class Fixture:
    def __init__(self, base: Path) -> None:
        self.root = base / "campaign"
        self.candidates: list[dict[str, str]] = []
        self.jobs: list[dict[str, str]] = []
        self.results: dict[str, dict[str, object]] = {}

    def add_candidate(self, candidate_id: str, split: str, parent: str = "P1") -> None:
        sequence = "QVQLVESGGGLVQAGGSLRLSCAASGFTFSSYAMGWFRQAPGKEREFVAAISWSGGSTYYADSVKGRFTISRDNAKNTVYLQMNSLKPEDTAVYYCAAARGGGYWGQGTQVTVSS" + candidate_id[-1]
        # Keep the fixture sequence alphabet valid while preserving uniqueness.
        sequence = sequence[:-1] + "ACDEFGHIKLMNPQRSTVWY"[len(self.candidates)]
        self.candidates.append(
            {
                "candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": sequence_sha(sequence),
                "cdr1": "GFTFSSYA",
                "cdr2": "ISWSGGS",
                "cdr3": "AAARGGGY",
                "parent_framework_cluster": parent,
                "model_split": split,
            }
        )

    def add_success(self, candidate_id: str, conformation: str, seed: int, value: float) -> None:
        candidate = next(row for row in self.candidates if row["candidate_id"] == candidate_id)
        job_id = f"{candidate_id}_{conformation}_s{seed}"
        job = {
            "job_id": job_id,
            "entity_type": "candidate",
            "entity_id": candidate_id,
            "conformation": conformation,
            "seed": str(seed),
            "sequence_sha256": candidate["sequence_sha256"],
            "protocol_core_sha256": "a" * 64,
            "job_hash": hashlib.sha256(job_id.encode()).hexdigest(),
        }
        self.jobs.append(job)
        self.results[job_id] = result_payload(job, value)

    def materialize(self) -> None:
        write_tsv(self.root / "inputs" / "candidates_128.tsv", self.candidates)
        write_tsv(self.root / "manifests" / "docking_jobs.tsv", self.jobs)
        (self.root / "PROTOCOL_CORE_LOCK.json").write_text(
            json.dumps({"status": "CORE_LOCKED", "protocol_core_sha256": "a" * 64}) + "\n"
        )
        (self.root / "PROTOCOL_LOCK.json").write_text(
            json.dumps({"status": "LOCKED", "protocol_core_sha256": "a" * 64}) + "\n"
        )
        for job_id, result in self.results.items():
            status = self.root / "status" / "jobs" / f"{job_id}.json"
            status.parent.mkdir(parents=True, exist_ok=True)
            status.write_text(json.dumps({"status": "SUCCESS", "evidence": f"results/{job_id}/job_result.json"}) + "\n")
            result_path = self.root / "results" / job_id / "job_result.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result) + "\n")


class SnapshotTests(unittest.TestCase):
    def test_strict_same_seed_pairing_excludes_cross_seed_only_and_uses_intersection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "train")
            fixture.add_candidate("C2", "train")
            fixture.add_success("C1", "8x6b", 917, 0.2)
            fixture.add_success("C1", "9e6y", 1931, 0.9)
            fixture.add_success("C2", "8x6b", 917, 0.2)
            fixture.add_success("C2", "9e6y", 917, 0.4)
            fixture.add_success("C2", "8x6b", 1931, 0.9)
            fixture.materialize()
            output = Path(temporary) / "out"
            receipt = MODULE.build_snapshot(fixture.root, output)
            rows = read_tsv(output / "v29_open_train.tsv")
            self.assertEqual([row["candidate_id"] for row in rows], ["C2"])
            self.assertEqual(rows[0]["successful_seed_ids_8X6B"], "917")
            self.assertEqual(rows[0]["successful_seed_ids_9E6Y"], "917")
            self.assertEqual(rows[0]["paired_successful_seed_ids"], "917")
            self.assertEqual(receipt["counts"]["strict_paired_candidates"]["train"], 1)

    def test_median_over_paired_seeds_exact_min_and_reliability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "development")
            for seed, r8, r9 in ((917, 0.1, 0.8), (1931, 0.8, 0.2)):
                fixture.add_success("C1", "8x6b", seed, r8)
                fixture.add_success("C1", "9e6y", seed, r9)
            fixture.materialize()
            output = Path(temporary) / "out"
            MODULE.build_snapshot(fixture.root, output)
            row = read_tsv(output / "v29_open_development.tsv")[0]
            r8 = float(row["R_8X6B"])
            r9 = float(row["R_9E6Y"])
            self.assertAlmostEqual(float(row["R_dual_min"]), min(r8, r9), places=12)
            self.assertEqual(row["teacher_reliability"], "DUAL_2_SEED")
            self.assertEqual(float(row["sample_weight"]), 0.8)
            self.assertGreaterEqual(float(row["teacher_uncertainty"]), 0.0)

    def test_frozen_test_is_count_only_and_never_emits_label_or_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("SECRET_TEST", "frozen_test", parent="P_TEST")
            fixture.add_success("SECRET_TEST", "8x6b", 917, 0.9)
            fixture.add_success("SECRET_TEST", "9e6y", 917, 0.8)
            fixture.add_candidate("OPEN_TRAIN", "train", parent="P_OPEN")
            fixture.add_success("OPEN_TRAIN", "8x6b", 917, 0.3)
            fixture.add_success("OPEN_TRAIN", "9e6y", 917, 0.4)
            fixture.materialize()
            output = Path(temporary) / "out"
            MODULE.build_snapshot(fixture.root, output)
            all_bytes = b"".join(path.read_bytes() for path in output.iterdir() if path.is_file())
            self.assertNotIn(b"SECRET_TEST", all_bytes)
            self.assertNotIn(b"P_TEST", all_bytes)
            frozen = json.loads((output / "V29_FROZEN_TEST_COUNT_ONLY.json").read_text())
            self.assertEqual(frozen["strict_paired_candidate_count"], 1)
            self.assertNotIn("candidate_ids", frozen)
            manifest = read_tsv(output / "v29_open_paired_job_manifest.tsv")
            self.assertTrue(all(row["model_split"] != "frozen_test" for row in manifest))

    def test_invalid_candidate_sequence_hash_and_split_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "train")
            fixture.add_success("C1", "8x6b", 917, 0.3)
            fixture.add_success("C1", "9e6y", 917, 0.4)
            fixture.candidates[0]["sequence_sha256"] = "0" * 64
            fixture.materialize()
            with self.assertRaisesRegex(MODULE.SnapshotError, "sequence_sha256_mismatch"):
                MODULE.build_snapshot(fixture.root, Path(temporary) / "out")

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "outer_test")
            fixture.add_success("C1", "8x6b", 917, 0.3)
            fixture.add_success("C1", "9e6y", 917, 0.4)
            fixture.materialize()
            with self.assertRaisesRegex(MODULE.SnapshotError, "model_split_invalid"):
                MODULE.build_snapshot(fixture.root, Path(temporary) / "out")

    def test_result_lineage_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "train")
            fixture.add_success("C1", "8x6b", 917, 0.3)
            fixture.add_success("C1", "9e6y", 917, 0.4)
            fixture.results[fixture.jobs[0]["job_id"]]["seed"] = 999
            fixture.materialize()
            with self.assertRaisesRegex(MODULE.SnapshotError, "result_seed_mismatch"):
                MODULE.build_snapshot(fixture.root, Path(temporary) / "out")

    def test_output_is_immutable_and_sha256s_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.add_candidate("C1", "train")
            fixture.add_success("C1", "8x6b", 917, 0.3)
            fixture.add_success("C1", "9e6y", 917, 0.4)
            fixture.materialize()
            output = Path(temporary) / "out"
            MODULE.build_snapshot(fixture.root, output)
            for line in (output / "SHA256SUMS").read_text().splitlines():
                digest, filename = line.split("  ", 1)
                self.assertEqual(MODULE.sha256_file(output / filename), digest)
            with self.assertRaisesRegex(MODULE.SnapshotError, "output_exists"):
                MODULE.build_snapshot(fixture.root, output)


if __name__ == "__main__":
    unittest.main()
