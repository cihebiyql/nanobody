from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src/extract_open_train_docking_contacts.py"
SPEC = importlib.util.spec_from_file_location("extract_open_train_docking_contacts", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def sha(sequence: str) -> str:
    return hashlib.sha256(sequence.encode("ascii")).hexdigest()


def atom_line(serial: int, residue: str, chain: str, number: int, x: float, y: float, z: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  {residue:>3s} {chain}{number:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C\n"
    )


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ContactExtractionTests(unittest.TestCase):
    def build_campaign(self, root: Path) -> tuple[Path, list[str]]:
        sequence_by_id = {"CAND_A": "ACD", "CAND_B": "GYS"}
        candidates = []
        for index, (candidate_id, sequence) in enumerate(sequence_by_id.items(), start=1):
            candidates.append({
                "candidate_id": candidate_id,
                "sequence_sha256": sha(sequence),
                "sequence": sequence,
                "parent_id": f"P{index}",
                "parent_framework_cluster": f"CL{index}",
                "original_formal_split": "train",
                "model_split": "OPEN_TRAIN",
            })
        candidates.extend([
            {
                "candidate_id": "SEALED_DEV", "sequence_sha256": sha("AAA"), "sequence": "AAA",
                "parent_id": "PD", "parent_framework_cluster": "CLD", "original_formal_split": "train",
                "model_split": "OPEN_DEVELOPMENT",
            },
            {
                "candidate_id": "SEALED_TEST", "sequence_sha256": sha("CCC"), "sequence": "CCC",
                "parent_id": "PT", "parent_framework_cluster": "CLT", "original_formal_split": "test",
                "model_split": "PROSPECTIVE_COMPUTATIONAL_TEST",
            },
        ])
        candidate_fields = list(candidates[0])
        write_tsv(root / "inputs/candidates_290.tsv", candidate_fields, candidates)

        jobs: list[dict[str, str]] = []
        job_ids: list[str] = []
        serial = 1
        for candidate in candidates[:2]:
            for receptor in MOD.RECEPTORS:
                for seed in MOD.EXPECTED_SEEDS:
                    job_id = f"{candidate['candidate_id']}_{receptor}_{seed}"
                    job_hash = hashlib.sha256(job_id.encode()).hexdigest()
                    job = {
                        "job_id": job_id,
                        "entity_type": "candidate",
                        "entity_id": candidate["candidate_id"],
                        "conformation": receptor,
                        "seed": str(seed),
                        "sequence_sha256": candidate["sequence_sha256"],
                        "cdr1_range": "1",
                        "cdr2_range": "2",
                        "cdr3_range": "3",
                        "vhh_chain": "A",
                        "receptor_chain": "T",
                        "job_hash": job_hash,
                    }
                    jobs.append(job)
                    job_ids.append(job_id)
                    pose_payloads = []
                    pose_dir = root / "runs" / job_id
                    pose_dir.mkdir(parents=True, exist_ok=True)
                    aa3 = [next(key for key, value in MOD.AA3_TO_1.items() if value == aa) for aa in candidate["sequence"]]
                    for pose_index in range(4):
                        pose = pose_dir / f"cluster_{pose_index + 1}_model_1.pdb.gz"
                        lines = []
                        for seq_index, residue in enumerate(aa3, start=1):
                            lines.append(atom_line(serial, residue, "A", seq_index, float(seq_index * 10), 0.0, 0.0))
                            serial += 1
                        # Position 71 contacts residue 1 in every pose. Position 90 contacts residue 3 in half.
                        lines.append(atom_line(serial, "SER", "T", 71, 10.0, 0.0, 3.0)); serial += 1
                        far = 30.0 if pose_index < 2 else 3.0
                        lines.append(atom_line(serial, "HIS", "T", 90, 30.0, 0.0, far)); serial += 1
                        with gzip.open(pose, "wt", encoding="ascii") as handle:
                            handle.writelines(lines)
                        pose_payloads.append({
                            "pose": str(pose),
                            "haddock_io": {"score": -100.0 + pose_index},
                            "scores": [{"reference_id": "8x6b"}, {"reference_id": "9e6y"}],
                        })
                    result = {
                        "state": "SUCCESS",
                        "job_id": job_id,
                        "job_hash": job_hash,
                        "entity_id": candidate["candidate_id"],
                        "dock_conformation": receptor,
                        "seed": seed,
                        "pose_scores": pose_payloads,
                    }
                    result_path = root / "results" / job_id / "job_result.json"
                    result_path.parent.mkdir(parents=True, exist_ok=True)
                    result_path.write_text(json.dumps(result), encoding="utf-8")
        write_tsv(root / "manifests/docking_jobs.tsv", list(jobs[0]), jobs)
        hotspot_payload = {
            "hotspots": {
                "all_uniprot_positions": list(range(71, 94)),
                "air_anchor_uniprot_positions": list(range(71, 83)),
                "holdout_uniprot_positions": list(range(83, 94)),
            }
        }
        hotspot_path = root / "reports/reference_normalization_summary.json"
        hotspot_path.parent.mkdir(parents=True, exist_ok=True)
        hotspot_path.write_text(json.dumps(hotspot_payload), encoding="utf-8")
        # These are deliberately invalid and must never be opened by the extractor.
        for sealed in ("SEALED_DEV", "SEALED_TEST"):
            invalid = root / "results" / f"{sealed}_8x6b_917" / "job_result.json"
            invalid.parent.mkdir(parents=True, exist_ok=True)
            invalid.write_text("not-json", encoding="utf-8")
        contract = root / "contract.json"
        contract.write_text("{}\n", encoding="utf-8")
        return contract, job_ids

    def test_end_to_end_emits_candidate_contact_features_and_keeps_sealed_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            contract, _job_ids = self.build_campaign(root)
            output = Path(temporary) / "output"
            result = MOD.extract(
                root, contract, output, workers=1, expected_candidates=2, enforce_production_hashes=False
            )
            self.assertEqual(result["candidate_rows"], 2)
            self.assertEqual(result["receptor_rows"], 4)
            self.assertEqual(result["job_status_counts"], {"SUCCESS": 12})
            audit = json.loads((output / MOD.AUDIT_OUTPUT).read_text())
            self.assertEqual(audit["sealed_boundary"]["forbidden_candidate_pose_files_opened"], 0)
            with (output / MOD.CANDIDATE_OUTPUT).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 2)
            self.assertGreater(float(rows[0]["8x6b_pair_contact_mass"]), 0.0)
            self.assertIn("dual_pvrig_profile_jsd", rows[0])

    def test_one_failed_seed_is_not_imputed_and_two_successful_seeds_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            contract, _job_ids = self.build_campaign(root)
            failed = root / "results/CAND_A_8x6b_3253/job_result.json"
            failed.unlink()
            output = Path(temporary) / "output"
            result = MOD.extract(
                root, contract, output, workers=1, expected_candidates=2, enforce_production_hashes=False
            )
            self.assertEqual(result["job_status_counts"], {"MISSING_OR_FAILED": 1, "SUCCESS": 11})
            with (output / MOD.RECEPTOR_OUTPUT).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            row = next(value for value in rows if value["candidate_id"] == "CAND_A" and value["receptor"] == "8x6b")
            self.assertEqual(row["successful_seed_count"], "2")

    def test_fewer_than_two_successful_seeds_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            contract, _job_ids = self.build_campaign(root)
            (root / "results/CAND_A_8x6b_3253/job_result.json").unlink()
            (root / "results/CAND_A_8x6b_1931/job_result.json").unlink()
            with self.assertRaisesRegex(MOD.ContactExtractionError, "too_few_successful_seeds"):
                MOD.extract(
                    root, contract, Path(temporary) / "output", workers=1,
                    expected_candidates=2, enforce_production_hashes=False,
                )

    def test_pose_sequence_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            contract, _job_ids = self.build_campaign(root)
            result = json.loads((root / "results/CAND_A_8x6b_917/job_result.json").read_text())
            pose = Path(result["pose_scores"][0]["pose"])
            with gzip.open(pose, "wt", encoding="ascii") as handle:
                handle.write(atom_line(1, "GLY", "A", 1, 10.0, 0.0, 0.0))
                handle.write(atom_line(2, "CYS", "A", 2, 20.0, 0.0, 0.0))
                handle.write(atom_line(3, "ASP", "A", 3, 30.0, 0.0, 0.0))
                handle.write(atom_line(4, "SER", "T", 71, 10.0, 0.0, 3.0))
            with self.assertRaisesRegex(MOD.ContactExtractionError, "pose_vhh_sequence_mismatch"):
                MOD.extract(
                    root, contract, Path(temporary) / "output", workers=1,
                    expected_candidates=2, enforce_production_hashes=False,
                )


if __name__ == "__main__":
    unittest.main()
