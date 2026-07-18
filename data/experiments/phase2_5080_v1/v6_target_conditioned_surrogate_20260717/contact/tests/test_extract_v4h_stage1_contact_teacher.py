from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src/extract_v4h_stage1_contact_teacher.py"
SPEC = importlib.util.spec_from_file_location("extract_v4h_stage1_contact_teacher", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sequence_hash(sequence: str) -> str:
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


def read_gzip_tsv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class Stage1ContactTeacherTests(unittest.TestCase):
    def build_fixture(self, base: Path) -> tuple[Path, Path, Path]:
        root = base / "raw"
        package = base / "terminal_package"
        package.mkdir(parents=True)
        sequences = {"CAND_A": "ACD", "CAND_B": "GYS", "CAND_C": "AAA"}
        candidates = []
        rankings = []
        for index, (candidate_id, sequence) in enumerate(sequences.items(), start=1):
            parent = f"CL{index}"
            candidates.append({
                "candidate_id": candidate_id,
                "sequence": sequence,
                "sequence_sha256": sequence_hash(sequence),
                "parent_framework_cluster": parent,
            })
            valid = candidate_id != "CAND_C"
            rankings.append({
                "candidate_id": candidate_id,
                "sequence_sha256": sequence_hash(sequence),
                "parent_framework_cluster": parent,
                "target_patch_id": "A_CENTER",
                "design_mode": "H3",
                "docking_evidence_tier": MOD.VALID_TIER if valid else MOD.INCOMPLETE_TIER,
                "successful_seed_count_8X6B": "1" if valid else "0",
                "successful_seed_ids_8X6B": "917" if valid else "",
                "successful_seed_count_9E6Y": "1",
                "successful_seed_ids_9E6Y": "917",
                "median_score_8X6B": "0.6" if valid else "",
                "median_score_9E6Y": "0.5",
                "R_dual_min": "0.5" if valid else "",
                "seed_dispersion_max": "0.0" if valid else "",
                "confidence_adjusted_score": "0.4" if valid else "",
                "technical_reasons": "" if valid else "8x6b:s917:FAILED_MAX_ATTEMPTS",
                "ranking_release": "stage1_seed917",
                "claim_boundary": "computational only",
                "rank": str(index),
            })
        write_tsv(root / "inputs/candidates_290.tsv", list(candidates[0]), candidates)

        jobs: list[dict[str, str]] = []
        serial = 1
        for candidate in candidates:
            for receptor in MOD.RECEPTORS:
                job_id = f"{candidate['candidate_id']}_{receptor}_917"
                job_hash = hashlib.sha256(job_id.encode()).hexdigest()
                job = {
                    "job_id": job_id,
                    "entity_type": "candidate",
                    "entity_id": candidate["candidate_id"],
                    "conformation": receptor,
                    "seed": "917",
                    "sequence_sha256": candidate["sequence_sha256"],
                    "cdr1_range": "1",
                    "cdr2_range": "2",
                    "cdr3_range": "3",
                    "vhh_chain": "A",
                    "receptor_chain": "T",
                    "job_hash": job_hash,
                }
                jobs.append(job)
                if candidate["candidate_id"] == "CAND_C" and receptor == "8x6b":
                    continue
                result_path = root / "results" / job_id / "job_result.json"
                result_path.parent.mkdir(parents=True, exist_ok=True)
                if candidate["candidate_id"] == "CAND_C":
                    # The extractor must never open the valid single receptor of an incomplete candidate.
                    result_path.write_text("not-json", encoding="utf-8")
                    continue
                pose_payloads = []
                aa3 = [next(key for key, value in MOD.AA3_TO_1.items() if value == aa) for aa in candidate["sequence"]]
                for pose_index in range(4):
                    pose = root / "runs" / job_id / f"cluster_{pose_index + 1}_model_1.pdb.gz"
                    pose.parent.mkdir(parents=True, exist_ok=True)
                    lines = []
                    for seq_index, residue in enumerate(aa3, start=1):
                        lines.append(atom_line(serial, residue, "A", seq_index, float(seq_index * 10), 0.0, 0.0))
                        serial += 1
                    lines.append(atom_line(serial, "SER", "T", 71, 10.0, 0.0, 3.0)); serial += 1
                    far = 30.0 if pose_index < 2 else 3.0
                    lines.append(atom_line(serial, "HIS", "T", 90, 30.0, 0.0, far)); serial += 1
                    with gzip.open(pose, "wt", encoding="ascii") as handle:
                        handle.writelines(lines)
                    pose_payloads.append({
                        "pose": str(pose),
                        "haddock_io": {"score": -100.0 + pose_index},
                    })
                result_path.write_text(json.dumps({
                    "state": "SUCCESS",
                    "job_id": job_id,
                    "job_hash": job_hash,
                    "entity_id": candidate["candidate_id"],
                    "dock_conformation": receptor,
                    "seed": 917,
                    "pose_scores": pose_payloads,
                }), encoding="utf-8")
        write_tsv(package / "stage1_all_seed917.tsv", list(jobs[0]), jobs)
        (root / "manifests").mkdir(parents=True, exist_ok=True)
        (root / "manifests/stage1_all_seed917.tsv").write_bytes((package / "stage1_all_seed917.tsv").read_bytes())
        write_tsv(package / "stage1_seed917_ranking.tsv", list(rankings[0]), rankings)
        (root / "release").mkdir(parents=True, exist_ok=True)
        (root / "release/stage1_seed917_ranking.tsv").write_bytes((package / "stage1_seed917_ranking.tsv").read_bytes())
        failure = [{
            "job_id": "CAND_C_8x6b_917", "entity_id": "CAND_C", "conformation": "8x6b",
            "seed": "917", "status": "FAILED_MAX_ATTEMPTS", "attempts": "2",
            "error": "HADDOCK3 produced no selected cluster models", "status_path": "status.json",
            "controller_log_path": "controller.log",
        }]
        write_tsv(package / "stage1_failures.tsv", list(failure[0]), failure)
        terminal = {
            "job_count": 6,
            "job_list_sha256": digest(package / "stage1_all_seed917.tsv"),
            "terminal_counts": {"FAILED_MAX_ATTEMPTS": 1, "SUCCESS": 5},
        }
        (package / "stage1_all_seed917.terminal.json").write_text(json.dumps(terminal), encoding="utf-8")
        core_names = [
            "stage1_all_seed917.tsv", "stage1_all_seed917.terminal.json",
            "stage1_seed917_ranking.tsv", "stage1_failures.tsv",
        ]
        file_hashes = {name: digest(package / name) for name in core_names}
        receipt = {
            "terminal_counts": terminal["terminal_counts"],
            "file_sha256": file_hashes,
            "remote_canonical_root": str(root),
        }
        (package / "stage1_local_package_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        (package / "SHA256SUMS").write_text(
            "".join(f"{file_hashes[name]}  {name}\n" for name in core_names), encoding="utf-8"
        )
        hotspots = {
            "hotspots": {
                "all_uniprot_positions": list(range(71, 94)),
                "air_anchor_uniprot_positions": list(range(71, 83)),
                "holdout_uniprot_positions": list(range(83, 94)),
            }
        }
        (root / "reports").mkdir(parents=True, exist_ok=True)
        (root / "reports/reference_normalization_summary.json").write_text(json.dumps(hotspots), encoding="utf-8")

        contract = {
            "schema_version": f"{MOD.SCHEMA_VERSION}_contract",
            "status": "FROZEN_PRE_EXTRACTION",
            "canonical_raw_root": str(root),
            "contact_definition": {
                "contact_cutoff_angstrom": 4.5,
                "top_k": 8,
                "minimum_poses": 4,
                "seed": 917,
                "receptors": list(MOD.RECEPTORS),
            },
            "expected_counts": {
                "candidates": 3, "stage1_jobs": 6, "successful_jobs": 5,
                "failed_jobs": 1, "ranking_rows": 3, "analyzable_candidates": 2,
                "technical_incomplete_candidates": 1,
            },
            "expected_sha256": {
                **file_hashes,
                "raw_candidates": digest(root / "inputs/candidates_290.tsv"),
                "raw_stage1_manifest": digest(root / "manifests/stage1_all_seed917.tsv"),
                "raw_stage1_ranking": digest(root / "release/stage1_seed917_ranking.tsv"),
                "raw_hotspots": digest(root / "reports/reference_normalization_summary.json"),
            },
        }
        contract_path = base / "contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        return root, package, contract_path

    def test_end_to_end_emits_all_candidate_states_and_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, package, contract = self.build_fixture(base)
            before = {str(path.relative_to(root)): digest(path) for path in root.rglob("*") if path.is_file()}
            output = base / "output"
            result = MOD.extract(root, package, contract, output, workers=1)
            after = {str(path.relative_to(root)): digest(path) for path in root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(result["candidate_rows"], 3)
            self.assertEqual(result["valid_candidate_rows"], 2)
            self.assertEqual(result["technical_incomplete_candidate_rows"], 1)
            self.assertEqual(result["receptor_rows"], 6)
            candidates = read_gzip_tsv(output / MOD.CANDIDATE_OUTPUT)
            incomplete = next(row for row in candidates if row["candidate_id"] == "CAND_C")
            self.assertEqual(incomplete["teacher_state"], MOD.INCOMPLETE_STATE)
            self.assertEqual(incomplete["R_dual_min"], "")
            self.assertEqual(incomplete["8x6b_pair_contact_mass"], "")
            receptors = read_gzip_tsv(output / MOD.RECEPTOR_OUTPUT)
            self.assertEqual(sum(row["teacher_state"] == MOD.INCOMPLETE_STATE for row in receptors), 2)
            self.assertTrue(read_gzip_tsv(output / MOD.PAIR_OUTPUT))
            audit = json.loads((output / MOD.AUDIT_OUTPUT).read_text())
            self.assertEqual(audit["counts"]["selected_successful_job_results_opened"], 4)
            self.assertEqual(audit["counts"]["excluded_raw_success_job_results_not_opened"], 1)
            self.assertEqual(audit["counts"]["excluded_failed_job_results_not_opened"], 1)
            self.assertEqual(audit["read_only_boundary"]["source_mutation_operations"], 0)

    def test_dry_run_validates_selected_metadata_without_creating_output_or_opening_poses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, package, contract = self.build_fixture(base)
            output = base / "not_created"
            result = MOD.extract(root, package, contract, output, workers=1, dry_run=True)
            self.assertEqual(result["status"], "PASS_READ_ONLY_DRY_RUN")
            self.assertEqual(result["selected_successful_jobs_validated"], 4)
            self.assertEqual(result["pose_coordinate_files_opened"], 0)
            self.assertFalse(output.exists())

    def test_frozen_contact_cutoff_cannot_be_changed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, package, contract = self.build_fixture(base)
            payload = json.loads(contract.read_text())
            payload["contact_definition"]["contact_cutoff_angstrom"] = 5.0
            contract.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(MOD.ContactExtractionError, "contact_cutoff_contract_changed"):
                MOD.extract(root, package, contract, base / "output", workers=1, dry_run=True)

    def test_pose_sequence_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, package, contract = self.build_fixture(base)
            result_path = root / "results/CAND_A_8x6b_917/job_result.json"
            result = json.loads(result_path.read_text())
            pose = Path(result["pose_scores"][0]["pose"])
            with gzip.open(pose, "wt", encoding="ascii") as handle:
                handle.write(atom_line(1, "GLY", "A", 1, 10.0, 0.0, 0.0))
                handle.write(atom_line(2, "CYS", "A", 2, 20.0, 0.0, 0.0))
                handle.write(atom_line(3, "ASP", "A", 3, 30.0, 0.0, 0.0))
                handle.write(atom_line(4, "SER", "T", 71, 10.0, 0.0, 3.0))
            with self.assertRaisesRegex(MOD.ContactExtractionError, "pose_vhh_sequence_mismatch"):
                MOD.extract(root, package, contract, base / "output", workers=1)


if __name__ == "__main__":
    unittest.main()
