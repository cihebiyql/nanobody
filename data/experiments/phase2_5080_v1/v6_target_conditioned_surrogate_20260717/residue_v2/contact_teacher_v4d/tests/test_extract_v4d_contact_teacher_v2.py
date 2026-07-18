from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src/extract_v4d_contact_teacher_v2.py"
SPEC = importlib.util.spec_from_file_location("extract_v4d_contact_teacher_v2", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sequence_hash(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_gzip_tsv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def atom_line(serial: int, residue: str, chain: str, number: int, x: float, y: float, z: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  {residue:>3s} {chain}{number:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C\n"
    )


class V4DContactTeacherV2Tests(unittest.TestCase):
    def build_fixture(self, base: Path) -> tuple[Path, Path]:
        root = base / "raw"
        (root / "PROTOCOL_CORE_LOCK.json").parent.mkdir(parents=True, exist_ok=True)
        (root / "PROTOCOL_CORE_LOCK.json").write_text('{"protocol":"core-v1"}\n', encoding="utf-8")
        (root / "PROTOCOL_LOCK.json").write_text('{"protocol":"full-v1"}\n', encoding="utf-8")
        protocol_core_sha256 = digest(root / "PROTOCOL_CORE_LOCK.json")
        candidates = [
            {
                "candidate_id": "OPEN_FULL",
                "sequence_sha256": sequence_hash("ACD"),
                "sequence": "ACD",
                "parent_id": "P1",
                "parent_framework_cluster": "CL1",
                "model_split": "OPEN_TRAIN",
            },
            {
                "candidate_id": "OPEN_PARTIAL",
                "sequence_sha256": sequence_hash("GYS"),
                "sequence": "GYS",
                "parent_id": "P2",
                "parent_framework_cluster": "CL2",
                "model_split": "OPEN_TRAIN",
            },
            {
                "candidate_id": "SEALED_DEV",
                "sequence_sha256": sequence_hash("AAA"),
                "sequence": "AAA",
                "parent_id": "P3",
                "parent_framework_cluster": "CL3",
                "model_split": "OPEN_DEVELOPMENT",
            },
            {
                "candidate_id": "SEALED_TEST",
                "sequence_sha256": sequence_hash("CCC"),
                "sequence": "CCC",
                "parent_id": "P4",
                "parent_framework_cluster": "CL4",
                "model_split": "PROSPECTIVE_COMPUTATIONAL_TEST",
            },
        ]
        candidate_path = root / "inputs/candidates_290.tsv"
        write_tsv(candidate_path, list(candidates[0]), candidates)

        jobs: list[dict[str, str]] = []
        expected_failure = "OPEN_PARTIAL_8x6b_s3253"
        aa3 = {
            "A": "ALA", "C": "CYS", "D": "ASP", "G": "GLY", "Y": "TYR", "S": "SER",
        }
        for candidate in candidates[:2]:
            for receptor in MOD.RECEPTORS:
                for seed in MOD.EXPECTED_SEEDS:
                    job_id = f"{candidate['candidate_id']}_{receptor}_s{seed}"
                    job_hash = hashlib.sha256(job_id.encode("ascii")).hexdigest()
                    jobs.append({
                        "job_id": job_id,
                        "entity_type": "candidate",
                        "entity_id": candidate["candidate_id"],
                        "conformation": receptor,
                        "seed": str(seed),
                        "sequence_sha256": candidate["sequence_sha256"],
                        "vhh_chain": "A",
                        "receptor_chain": "T",
                        "protocol_core_sha256": protocol_core_sha256,
                        "job_hash": job_hash,
                    })
                    if job_id == expected_failure:
                        continue
                    selected_models: list[str] = []
                    pose_scores: list[dict[str, object]] = []
                    for pose_index in range(9):
                        model = f"cluster_{pose_index + 1}_model_1.pdb.gz"
                        relative = f"runs/{job_id}/haddock_run/6_seletopclusts/{model}"
                        pose_path = root / relative
                        pose_path.parent.mkdir(parents=True, exist_ok=True)
                        serial = 1
                        lines: list[str] = []
                        for index, aa in enumerate(candidate["sequence"], start=1):
                            lines.append(atom_line(serial, aa3[aa], "A", index, float((index - 1) * 10), 0.0, 0.0))
                            serial += 1
                        # The invalid best-scoring pose would contact residue 3.  It must be
                        # filtered before Top-8 and must never contribute to either target.
                        if pose_index == 0:
                            lines.append(atom_line(serial, "SER", "T", 90, 20.0, 0.0, 3.0))
                        elif pose_index % 2:
                            lines.append(atom_line(serial, "SER", "T", 71, 0.0, 0.0, 3.0))
                        else:
                            lines.append(atom_line(serial, "HIS", "T", 72, 0.0, 0.0, 3.0))
                        # The fixture itself must be byte deterministic.  gzip.open()
                        # embeds the wall-clock mtime and made the inventory hash test
                        # spuriously depend on whether the two roots were built across
                        # a one-second boundary.
                        with pose_path.open("wb") as raw_handle:
                            with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
                                compressed.write("".join(lines).encode("ascii"))
                        selected_models.append(relative)
                        native_overlay = 1.1 if pose_index == 0 else 0.4
                        pose_scores.append({
                            "pose": f"/inaccessible/offload/{model}",
                            "haddock_io": {"score": -100.0 + pose_index},
                            "scores": [
                                {"reference_id": receptor, "overlay": {"t_ca_rmsd_a": native_overlay}},
                                {
                                    "reference_id": "9e6y" if receptor == "8x6b" else "8x6b",
                                    "overlay": {"t_ca_rmsd_a": 9.9},
                                },
                            ],
                        })
                    result_path = root / "results" / job_id / "job_result.json"
                    result_path.parent.mkdir(parents=True, exist_ok=True)
                    result_path.write_text(json.dumps({
                        "state": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": job_hash,
                        "entity_type": "candidate",
                        "entity_id": candidate["candidate_id"],
                        "dock_conformation": receptor,
                        "seed": seed,
                        "protocol_core_sha256": protocol_core_sha256,
                        "selected_model_count": 9,
                        "selected_models": selected_models,
                        "pose_scores": pose_scores,
                    }), encoding="utf-8")

        # These rows are metadata only.  Their result files are deliberately poison;
        # any attempt to access sealed contact evidence must fail the test.
        for candidate in candidates[2:]:
            job_id = f"{candidate['candidate_id']}_8x6b_s917"
            jobs.append({
                "job_id": job_id,
                "entity_type": "candidate",
                "entity_id": candidate["candidate_id"],
                "conformation": "8x6b",
                "seed": "917",
                "sequence_sha256": candidate["sequence_sha256"],
                "vhh_chain": "A",
                "receptor_chain": "T",
                "protocol_core_sha256": protocol_core_sha256,
                "job_hash": hashlib.sha256(job_id.encode("ascii")).hexdigest(),
            })
            poison = root / "results" / job_id / "job_result.json"
            poison.parent.mkdir(parents=True, exist_ok=True)
            poison.write_text("SEALED-CONTACT-LABEL-MUST-NOT-BE-READ", encoding="utf-8")

        manifest_path = root / "manifests/docking_jobs.tsv"
        write_tsv(manifest_path, list(jobs[0]), jobs)
        contract = {
            "schema_version": MOD.CONTRACT_SCHEMA_VERSION,
            "status": "FROZEN_PRE_EXTRACTION",
            "canonical_raw_root": str(root),
            "allowed_model_split": "OPEN_TRAIN",
            "sealed_model_splits": ["OPEN_DEVELOPMENT", "PROSPECTIVE_COMPUTATIONAL_TEST"],
            "contact_definition": {
                "receptors": list(MOD.RECEPTORS),
                "expected_seeds": list(MOD.EXPECTED_SEEDS),
                "native_overlay_max_rmsd_angstrom": 1.0,
                "top_k_after_pose_validity_filter": 8,
                "minimum_valid_poses_per_successful_job": 4,
                "contact_cutoff_angstrom": 4.5,
                "pose_rank_weight": "normalized_1_over_log2_rank_plus_1",
                "seed_weighting": "equal_over_observed_successful_seeds",
                "pair_variance": "population",
                "uncertainty_weight": "1/(1+4*variance)",
                "residue_marginal": "pose_weighted_any_pvrig_contact_then_equal_seed_mean",
            },
            "expected_counts": {
                "open_train_candidates": 2,
                "open_train_parent_clusters": 2,
                "scheduled_open_train_jobs": 12,
                "successful_open_train_jobs": 11,
                "failed_open_train_jobs": 1,
                "complete_three_seed_candidates": 1,
                "partial_seed_candidates": 1,
                "selected_native_poses_before_filter": 99,
                "invalid_native_overlay_poses": 11,
                "valid_native_poses_after_filter": 88,
                "top_k_pose_inventory_rows": 88,
                "residue_marginal_rows": 12,
            },
            "expected_failed_job_ids": [expected_failure],
            "expected_partial_candidate": {
                "candidate_id": "OPEN_PARTIAL",
                "observed_seeds_8x6b": [917, 1931],
                "observed_seeds_9e6y": [917, 1931, 3253],
            },
            "expected_sha256": {
                "candidates": digest(candidate_path),
                "docking_jobs": digest(manifest_path),
                "protocol_core_lock": digest(root / "PROTOCOL_CORE_LOCK.json"),
                "protocol_lock": digest(root / "PROTOCOL_LOCK.json"),
            },
            "output_files": {
                "pair": MOD.PAIR_OUTPUT,
                "residue_marginal": MOD.RESIDUE_OUTPUT,
                "pose_inventory": MOD.POSE_INVENTORY_OUTPUT,
                "audit": MOD.AUDIT_OUTPUT,
                "receipt": MOD.RECEIPT_OUTPUT,
            },
        }
        contract_path = base / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return root, contract_path

    def test_end_to_end_multi_seed_targets_and_sealed_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, contract = self.build_fixture(base)
            source_before = {str(path.relative_to(root)): digest(path) for path in root.rglob("*") if path.is_file()}
            output = base / "output"
            receipt = MOD.extract(root, contract, output, workers=1)
            source_after = {str(path.relative_to(root)): digest(path) for path in root.rglob("*") if path.is_file()}
            self.assertEqual(source_before, source_after)
            self.assertEqual(receipt["status"], "COMPLETE_V4D_OPEN226_MULTI_SEED_CONTACT_TEACHER_V2")
            self.assertEqual(receipt["counts"]["teacher_candidates"], 2)
            self.assertEqual(receipt["counts"]["complete_three_seed_candidates"], 1)
            self.assertEqual(receipt["counts"]["partial_seed_candidates"], 1)
            self.assertEqual(receipt["counts"]["pose_inventory_rows"], 88)
            self.assertEqual(receipt["sealed_boundary"]["sealed_result_files_opened"], 0)

            pairs = read_gzip_tsv(output / MOD.PAIR_OUTPUT)
            residue = read_gzip_tsv(output / MOD.RESIDUE_OUTPUT)
            inventory = read_gzip_tsv(output / MOD.POSE_INVENTORY_OUTPUT)
            self.assertEqual(len(residue), 2 * 2 * 3)
            self.assertEqual(len(inventory), 88)
            self.assertNotIn("cluster_1_model_1.pdb.gz", {row["model"] for row in inventory})

            pair_71 = next(row for row in pairs if row["candidate_id"] == "OPEN_FULL" and row["receptor"] == "8x6b" and row["pvrig_uniprot_position"] == "71")
            self.assertEqual(pair_71["observed_seed_count"], "3")
            variance = float(pair_71["contact_target_variance"])
            self.assertAlmostEqual(float(pair_71["contact_uncertainty_weight"]), 1.0 / (1.0 + 4.0 * variance), places=12)

            # Every valid pose contacts VHH residue 1, split between PVRIG 71 and 72.
            # The true any-contact marginal is therefore 1.0 and is strictly greater
            # than either max-over-target pair frequency.
            marginal = next(row for row in residue if row["candidate_id"] == "OPEN_FULL" and row["receptor"] == "8x6b" and row["vhh_sequence_index"] == "1")
            self.assertAlmostEqual(float(marginal["contact_marginal_mean"]), 1.0, places=12)
            max_pair = max(float(row["contact_target_mean"]) for row in pairs if row["candidate_id"] == "OPEN_FULL" and row["receptor"] == "8x6b" and row["vhh_sequence_index"] == "1")
            self.assertGreater(float(marginal["contact_marginal_mean"]), max_pair)

            partial_rows = [row for row in residue if row["candidate_id"] == "OPEN_PARTIAL" and row["receptor"] == "8x6b"]
            self.assertTrue(partial_rows)
            self.assertEqual({row["observed_seed_count"] for row in partial_rows}, {"2"})
            self.assertEqual({row["expected_seed_count"] for row in partial_rows}, {"3"})
            self.assertEqual(receipt["counts"]["zero_imputed_failed_seeds"], 0)

            self.assertEqual(receipt["outputs"]["pose_inventory_sha256"], digest(output / MOD.POSE_INVENTORY_OUTPUT))

    def test_required_merger_fields_are_present(self) -> None:
        required_pair = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor",
            "vhh_sequence_index", "vhh_aa", "pvrig_uniprot_position", "pvrig_aa",
            "contact_target_mean", "contact_target_variance", "contact_uncertainty_weight",
            "supporting_seed_count", "observed_seed_count", "expected_seed_count",
        }
        required_residue = {
            "candidate_id", "sequence_sha256", "parent_framework_cluster", "receptor",
            "vhh_sequence_index", "vhh_aa", "contact_marginal_mean",
            "contact_marginal_variance", "contact_marginal_uncertainty_weight",
            "observed_seed_count", "expected_seed_count",
        }
        self.assertTrue(required_pair <= set(MOD.PAIR_FIELDS))
        self.assertTrue(required_residue <= set(MOD.RESIDUE_FIELDS))

    def test_changed_frozen_overlay_threshold_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, contract = self.build_fixture(base)
            payload = json.loads(contract.read_text())
            payload["contact_definition"]["native_overlay_max_rmsd_angstrom"] = 1.1
            contract.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContactTeacherError, "native_overlay_threshold_changed"):
                MOD.extract(root, contract, base / "output", workers=1)

    def test_pose_sequence_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, contract = self.build_fixture(base)
            pose = root / "runs/OPEN_FULL_8x6b_s917/haddock_run/6_seletopclusts/cluster_2_model_1.pdb.gz"
            with gzip.open(pose, "wt", encoding="ascii") as handle:
                handle.write(atom_line(1, "GLY", "A", 1, 0.0, 0.0, 0.0))
                handle.write(atom_line(2, "CYS", "A", 2, 10.0, 0.0, 0.0))
                handle.write(atom_line(3, "ASP", "A", 3, 20.0, 0.0, 0.0))
                handle.write(atom_line(4, "SER", "T", 71, 0.0, 0.0, 3.0))
            with self.assertRaisesRegex(MOD.ContactTeacherError, "pose_vhh_sequence_mismatch"):
                MOD.extract(root, contract, base / "output", workers=1)

    def test_protocol_lock_and_partial_identity_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, contract = self.build_fixture(base)
            (root / "PROTOCOL_CORE_LOCK.json").write_text('{"protocol":"tampered"}\n', encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContactTeacherError, "protocol_core_lock_sha256_mismatch"):
                MOD.extract(root, contract, base / "output", workers=1)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, contract = self.build_fixture(base)
            payload = json.loads(contract.read_text())
            payload["expected_partial_candidate"]["candidate_id"] = "OPEN_FULL"
            contract.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContactTeacherError, "partial_candidate_identity_mismatch"):
                MOD.extract(root, contract, base / "output", workers=1)

    def test_outputs_are_deterministic_across_roots(self) -> None:
        with tempfile.TemporaryDirectory() as left_temp, tempfile.TemporaryDirectory() as right_temp:
            left, right = Path(left_temp), Path(right_temp)
            left_root, left_contract = self.build_fixture(left)
            right_root, right_contract = self.build_fixture(right)
            MOD.extract(left_root, left_contract, left / "out", workers=1)
            MOD.extract(right_root, right_contract, right / "out", workers=2)
            for name in (MOD.PAIR_OUTPUT, MOD.RESIDUE_OUTPUT, MOD.POSE_INVENTORY_OUTPUT):
                self.assertEqual(digest(left / "out" / name), digest(right / "out" / name), name)


if __name__ == "__main__":
    unittest.main()
