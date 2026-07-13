#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v3_p2_docking_gold.py")
SPEC = importlib.util.spec_from_file_location("p2_docking_gold", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DockingGoldMathTests(unittest.TestCase):
    def test_pose_relevance_mapping_is_count_based(self) -> None:
        self.assertEqual(MOD.pose_relevance(2, 0, 0), 4)
        self.assertEqual(MOD.pose_relevance(1, 1, 0), 3)
        self.assertEqual(MOD.pose_relevance(0, 1, 1), 2)
        self.assertEqual(MOD.pose_relevance(0, 0, 1), 1)
        self.assertEqual(MOD.pose_relevance(0, 0, 0), 0)

    def test_pose_weight_and_receptor_score(self) -> None:
        self.assertAlmostEqual(MOD.pose_weight(1, 2), 0.5)
        rows = [
            {"pose_weight": 0.5, "relevance": 4},
            {"pose_weight": 0.25, "relevance": 2},
        ]
        self.assertAlmostEqual(MOD.weighted_receptor_score(rows), 10 / 3)

    def test_stable_tier_uses_max_per_unique_cluster_without_losing_duplicates(self) -> None:
        # The final duplicate for c1 is deliberately lower; max(c1) must remain 4.
        self.assertEqual(MOD.stable_tier([("8x6b:c1", 4), ("9e6y:c1", 3), ("8x6b:c1", 1)]), ("G2", 3, 2))
        self.assertEqual(MOD.stable_tier([("c1", 4), ("c2", 4)]), ("G1", 4, 2))
        self.assertEqual(MOD.stable_tier([("c1", 4), ("c2", 2)]), ("G3", 2, 2))
        self.assertEqual(MOD.stable_tier([("c1", 4)]), ("G5", 0, 1))

    def test_spearman_uses_average_ranks_for_ties(self) -> None:
        self.assertAlmostEqual(MOD.spearman_with_ties([1, 1, 2, 3], [1, 2, 2, 3]), 5 / 6)
        self.assertEqual(MOD.spearman_with_ties([1, 1, 2], [1, 1, 2]), 1.0)
        self.assertIsNone(MOD.spearman_with_ties([1, 1, 1], [1, 2, 3]))

    def test_weighted_kappa_is_five_level_and_preregistered_quadratic(self) -> None:
        tiers = ["G1", "G2", "G3", "G4", "G5"]
        self.assertEqual(MOD.weighted_cohen_kappa(tiers, tiers, "quadratic"), 1.0)
        self.assertAlmostEqual(MOD.weighted_cohen_kappa(tiers, list(reversed(tiers)), "quadratic"), -1.0)
        self.assertAlmostEqual(MOD.weighted_cohen_kappa(tiers, list(reversed(tiers)), "linear"), -0.5)

    def test_pilot_gate_requires_every_prefrozen_threshold(self) -> None:
        passed = MOD.pilot_gate(64, 32, 0, False, False, 0.70, 0.60, True)
        self.assertEqual(passed["status"], "PASS_DOCKING_GOLD_VALIDATED")
        failed = MOD.pilot_gate(64, 32, 0, False, False, 0.6999, 0.60, True)
        self.assertEqual(failed["status"], "FAIL_DOCKING_GOLD_NOT_VALIDATED")
        self.assertIn("repeat_R_gold_spearman_ge_0_70", failed["failed_gates"])
        relaxed = MOD.pilot_gate(64, 32, 0, False, True, 0.70, 0.60, True)
        self.assertNotIn("per_candidate_failure_tolerance_override_false", relaxed["failed_gates"])
        self.assertIn("tolerance_relaxation_false", relaxed["failed_gates"])


class DockingGoldEvidenceTests(unittest.TestCase):
    def make_protocol_evidence(self, root: Path, flat_params: bool = False) -> dict[str, str]:
        run_id = "P2PILOT_001__8x6b__main"
        run_root = root / "runs" / run_id
        run_dir = run_root / f"run_{run_id}"
        config = run_root / f"{run_id}.cfg"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "[topoaa]\niniseed = 917\n"
            "[rigidbody]\niniseed = 917\ntolerance = 5\nsampling = 40\n"
            "[seletop]\nselect = 10\n"
            "[flexref]\ntolerance = 20\n"
            "[emref]\ntolerance = 20\n",
            encoding="utf-8",
        )
        params = run_dir / "1_rigidbody/params.cfg"
        params.parent.mkdir(parents=True, exist_ok=True)
        prefix = "" if flat_params else "[rigidbody]\n"
        params.write_text(prefix + "iniseed = 917\ntolerance = 5\nsampling = 40\n", encoding="utf-8")
        (run_dir / "3_flexref").mkdir(parents=True, exist_ok=True)
        (run_dir / "3_flexref/params.cfg").write_text("[flexref]\ntolerance = 20\n", encoding="utf-8")
        (run_dir / "4_emref").mkdir(parents=True, exist_ok=True)
        (run_dir / "4_emref/params.cfg").write_text("[emref]\ntolerance = 20\n", encoding="utf-8")
        stage_counts = {"topoaa": 2, "rigidbody": 38, "seletop": 10, "flexref": 8, "emref": 8, "final": 8}
        stage_paths = {
            "topoaa": "0_topoaa/io.json",
            "rigidbody": "1_rigidbody/io.json",
            "seletop": "2_seletop/io.json",
            "flexref": "3_flexref/io.json",
            "emref": "4_emref/io.json",
            "final": "6_seletopclusts/io.json",
        }
        for stage, relative in stage_paths.items():
            path = run_dir / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            outputs = (
                [{"seed": seed} for seed in range(918, 956)]
                if stage == "rigidbody"
                else [{} for _ in range(stage_counts[stage])]
            )
            path.write_text(json.dumps({"output": outputs}), encoding="utf-8")
        selected = run_dir / "6_seletopclusts"
        for index in range(1, 9):
            cluster = 1 if index <= 4 else 2
            model = index if index <= 4 else index - 4
            (selected / f"cluster_{cluster}_model_{model}.pdb.gz").write_bytes(b"model\n")
        completion = run_root / f"{run_id}.complete.json"
        completion.write_text(
            json.dumps(
                {
                    "protocol_id": "DG_A_PILOT64_V1_1",
                    "run_id": run_id,
                    "status": "PASS_DOCKING_OUTPUT_COMPLETE",
                    "iniseed": 917,
                    "pose_count": 8,
                    "cluster_count": 2,
                    "stage_output_counts": stage_counts,
                    "config_sha256": sha(config),
                    "monomer_sha256": "m" * 64,
                    "receptor_sha256": "r" * 64,
                    "per_candidate_failure_tolerance_override": False,
                    "tolerance_relaxed": False,
                    "haddock3_version_contract": "2025.11.0",
                    "exit_code": 0,
                }
            ),
            encoding="utf-8",
        )
        return {
            "run_id": run_id,
            "protocol_id": "DG_A_PILOT64_V1_1",
            "pilot_id": "P2PILOT_001",
            "source_candidate_id": "candidate_1",
            "receptor_id": "8x6b",
            "seed_role": "main",
            "iniseed": "917",
            "topoaa_iniseed": "917",
            "rigidbody_iniseed": "917",
            "rigidbody_seed_start": "918",
            "rigidbody_seed_end": "957",
            "rigidbody_sampling": "40",
            "rigidbody_tolerance": "5",
            "flexref_tolerance": "20",
            "emref_tolerance": "20",
            "per_candidate_failure_tolerance_override": "false",
            "tolerance_relaxed": "false",
            "config_relpath": str(config.relative_to(root)),
            "config_sha256": sha(config),
            "completion_relpath": str(completion.relative_to(root)),
            "run_dir_relpath": str(run_dir.relative_to(root)),
            "monomer_sha256": "m" * 64,
            "receptor_sha256": "r" * 64,
            "haddock3_version_contract": "2025.11.0",
        }

    def test_protocol_checks_synced_config_completion_params_and_runtime_seed_set(self) -> None:
        for flat in (False, True):
            with self.subTest(flat_params=flat), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                row = self.make_protocol_evidence(root, flat_params=flat)
                evidence, errors = MOD.run_protocol_checks(row, root)
                self.assertEqual(errors, [])
                self.assertTrue(all(evidence["checks"].values()))
                self.assertEqual(evidence["runtime_rigidbody_output_count"], 38)
                self.assertEqual(evidence["runtime_rigidbody_seed_start"], 918)
                self.assertEqual(evidence["runtime_rigidbody_seed_end"], 955)
                self.assertEqual(evidence["runtime_stage_output_counts"], {
                    "topoaa": 2, "rigidbody": 38, "seletop": 10,
                    "flexref": 8, "emref": 8, "final": 8,
                })

    def test_protocol_check_rejects_relaxation_and_wrong_runtime_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = self.make_protocol_evidence(root)
            row["per_candidate_failure_tolerance_override"] = "true"
            io_path = root / row["run_dir_relpath"] / "1_rigidbody/io.json"
            payload = json.loads(io_path.read_text(encoding="utf-8"))
            payload["output"][0]["seed"] = 999
            io_path.write_text(json.dumps(payload), encoding="utf-8")
            evidence, errors = MOD.run_protocol_checks(row, root)
            self.assertFalse(
                evidence["checks"]["manifest_no_per_candidate_failure_tolerance_override"]
            )
            self.assertFalse(evidence["checks"]["runtime_rigidbody_seed_set"])
            self.assertTrue(errors)

    def make_postprocessed_run(
        self,
        root: Path,
        row: dict[str, str],
        sync_root: Path,
        run_manifest_sha256: str,
    ) -> list[dict[str, object]]:
        run_id = row["run_id"]
        run_root = root / run_id
        reports = run_root / "reports"
        models = [f"cluster_{1 if index <= 4 else 2}_model_{index if index <= 4 else index-4}" for index in range(1, 9)]
        class_pairs = [
            ("BLOCKER_LIKE_A", "BLOCKER_LIKE_A"),
            ("BLOCKER_LIKE_A", "BLOCKER_PLAUSIBLE_B"),
            ("BLOCKER_PLAUSIBLE_B", "BLOCKER_PLAUSIBLE_B"),
            ("BINDER_LIKE_C", "BINDER_LIKE_C"),
            ("EVIDENCE_INFERENCE_ONLY_E", "EVIDENCE_INFERENCE_ONLY_E"),
            ("BLOCKER_LIKE_A", "BLOCKER_LIKE_A"),
            ("BLOCKER_PLAUSIBLE_B", "BINDER_LIKE_C"),
            ("BINDER_LIKE_C", "EVIDENCE_INFERENCE_ONLY_E"),
        ]
        class_rows: dict[str, list[dict[str, object]]] = {baseline: [] for baseline in MOD.RECEPTORS}
        mechanism_rows: dict[str, list[dict[str, object]]] = {baseline: [] for baseline in MOD.RECEPTORS}
        consensus_rows: list[dict[str, object]] = []
        canonical_rows: list[dict[str, object]] = []
        for rank, (model, pair) in enumerate(zip(models, class_pairs), 1):
            counts = {value: pair.count(value) for value in MOD.VALID_BLOCKER_CLASSES}
            for baseline, blocker_class in zip(MOD.RECEPTORS, pair):
                class_rows[baseline].append(
                    {
                        "model": model,
                        "hotspot_overlap_count": 10,
                        "total_vhh_pvrl2_residue_pair_occlusion": 100,
                        "cdr3_pvrl2_residue_pair_occlusion": 20,
                        "cdr3_occlusion_fraction": 0.2,
                        "blocker_class": blocker_class,
                    }
                )
                mechanism_rows[baseline].append(
                    {
                        "model": model,
                        "hotspot_overlap_count": 10,
                        "pvrig_vhh_contact_pair_count": 30,
                        "pvrl2_vhh_occluding_contact_count": 100,
                    }
                )
            consensus_rows.append(
                {
                    "model": model,
                    "baseline_count": 2,
                    "blocker_like_count": counts["BLOCKER_LIKE_A"],
                    "plausible_count": counts["BLOCKER_PLAUSIBLE_B"],
                    "binder_like_count": counts["BINDER_LIKE_C"],
                    "evidence_only_count": counts["EVIDENCE_INFERENCE_ONLY_E"],
                    "best_haddock_rank": rank,
                    "baseline_classes": f"8x6b:{pair[0]};9e6y:{pair[1]}",
                }
            )
            canonical_rows.append(
                {
                    "model": model,
                    "generation_receptor": row["receptor_id"],
                    "canonical_residue_pair_count": 30,
                    "status": "PASS",
                }
            )
        write_csv(reports / f"{run_id}_dual_baseline_consensus.csv", consensus_rows)
        write_csv(reports / f"{run_id}_canonical_contact_summary.csv", canonical_rows)
        write_csv(
            reports / f"{run_id}_canonical_contact_pairs.csv",
            [{"model": model, "pvrig_uniprot_position": 1, "vhh_resseq": 1} for model in models],
        )
        write_csv(
            reports / "haddock3_model_ranks.csv",
            [{"model": model, "haddock_rank": rank} for rank, model in enumerate(models, 1)],
        )
        for baseline in MOD.RECEPTORS:
            write_csv(reports / f"{run_id}_{baseline}_blocker_classification.csv", class_rows[baseline])
            write_csv(
                run_root / f"{baseline}_baseline/haddock3_top_model_mechanism_scores_{baseline}.csv",
                mechanism_rows[baseline],
            )
        synced_run_dir = sync_root / row["run_dir_relpath"]
        selected_dir = synced_run_dir / "6_seletopclusts"
        selected_dir.mkdir(parents=True, exist_ok=True)
        selected_pose_files = []
        for rank, model in enumerate(models, 1):
            pose = selected_dir / f"{model}.pdb.gz"
            pose.write_bytes(f"pose:{model}\n".encode())
            selected_pose_files.append(
                {"model": model, "filename": pose.name, "sha256": sha(pose), "haddock_rank": rank}
            )
        completion = sync_root / row["completion_relpath"]
        completion.parent.mkdir(parents=True, exist_ok=True)
        completion_payload = {
            "schema_version": "phase2_v3_p2_pilot64_run_completion_v1_1",
            "protocol_id": MOD.PROTOCOL_ID,
            "status": "PASS_DOCKING_OUTPUT_COMPLETE",
            "run_id": run_id,
            "pilot_id": row["pilot_id"],
            "source_candidate_id": row["source_candidate_id"],
            "receptor_id": row["receptor_id"],
            "seed_role": row["seed_role"],
            "pose_count": 8,
            "cluster_count": 2,
        }
        completion.write_text(json.dumps(completion_payload), encoding="utf-8")
        artifacts = {
            "consensus": reports / f"{run_id}_dual_baseline_consensus.csv",
            "classification_8x6b": reports / f"{run_id}_8x6b_blocker_classification.csv",
            "classification_9e6y": reports / f"{run_id}_9e6y_blocker_classification.csv",
            "mechanism_8x6b": run_root / "8x6b_baseline/haddock3_top_model_mechanism_scores_8x6b.csv",
            "mechanism_9e6y": run_root / "9e6y_baseline/haddock3_top_model_mechanism_scores_9e6y.csv",
            "canonical_contact_summary": reports / f"{run_id}_canonical_contact_summary.csv",
            "canonical_contact_pairs": reports / f"{run_id}_canonical_contact_pairs.csv",
            "ranks": reports / "haddock3_model_ranks.csv",
        }
        marker = {
            "schema_version": "phase2_v3_p2_dual_docking_run_postprocess_v1_1",
            "protocol_id": MOD.PROTOCOL_ID,
            "status": "PASS",
            "run_id": run_id,
            "pilot_id": row["pilot_id"],
            "source_candidate_id": row["source_candidate_id"],
            "generation_receptor": row["receptor_id"],
            "seed_role": row["seed_role"],
            "run_manifest_sha256": run_manifest_sha256,
            "docking_completion": {
                "relpath": row["completion_relpath"],
                "sha256": sha(completion),
                **completion_payload,
            },
            "input_sha256": {
                "config": row["config_sha256"],
                "monomer": row["monomer_sha256"],
                "receptor": row["receptor_sha256"],
            },
            "selected_pose_files": selected_pose_files,
            "counts": {
                "selected_models": 8,
                "pose_clusters": 2,
                "consensus_rows": 8,
                "classification_8x6b_rows": 8,
                "classification_9e6y_rows": 8,
                "mechanism_8x6b_rows": 8,
                "mechanism_9e6y_rows": 8,
                "canonical_contact_pose_rows": 8,
                "canonical_contact_pair_rows": 8,
                "contact_failures": 0,
            },
            "artifacts": {
                key: {"relpath": str(path.relative_to(run_root)), "sha256": sha(path)}
                for key, path in artifacts.items()
            },
            "consensus_sha256": sha(artifacts["consensus"]),
            "claim_boundary": MOD.CLAIM_BOUNDARY,
        }
        (run_root / "postprocess.complete.json").write_text(json.dumps(marker), encoding="utf-8")
        return consensus_rows

    def test_postprocessed_run_pins_weights_tiers_and_complete_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "run_id": "P2PILOT_001__8x6b__main",
                "pilot_id": "P2PILOT_001",
                "source_candidate_id": "candidate_1",
                "receptor_id": "8x6b",
                "seed_role": "main",
                "run_dir_relpath": "runs/P2PILOT_001__8x6b__main/run_P2PILOT_001__8x6b__main",
                "completion_relpath": "runs/P2PILOT_001__8x6b__main/P2PILOT_001__8x6b__main.complete.json",
                "config_sha256": "c" * 64,
                "monomer_sha256": "m" * 64,
                "receptor_sha256": "r" * 64,
            }
            sync_root = root / "sync"
            consensus = self.make_postprocessed_run(root, row, sync_root, "f" * 64)
            poses, evidence, errors = MOD.evaluate_postprocessed_run(row, root, sync_root, "f" * 64)
            self.assertEqual(errors, [])
            self.assertEqual(len(poses), 8)
            self.assertEqual(evidence["pose_clusters"], 2)
            self.assertEqual(evidence["stable_tier"], "G1")
            self.assertEqual(evidence["contact_failures"], 0)
            relevances = [4, 3, 2, 1, 0, 4, 2, 1]
            weights = [MOD.pose_weight(rank, 4) for rank in range(1, 9)]
            expected = sum(weight * relevance for weight, relevance in zip(weights, relevances)) / sum(weights)
            self.assertAlmostEqual(evidence["r_receptor"], expected)
            self.assertEqual([int(row["relevance"]) for row in poses], relevances)
            self.assertTrue(all(row["schema_version"] == "phase2_v3_p2_docking_gold_pose_v1_1" for row in poses))
            self.assertTrue(all(row["protocol_id"] == MOD.PROTOCOL_ID for row in poses))

    def test_postprocessed_run_rejects_canonical_contact_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            row = {
                "run_id": "P2PILOT_001__8x6b__main",
                "pilot_id": "P2PILOT_001",
                "source_candidate_id": "candidate_1",
                "receptor_id": "8x6b",
                "seed_role": "main",
                "run_dir_relpath": "runs/P2PILOT_001__8x6b__main/run_P2PILOT_001__8x6b__main",
                "completion_relpath": "runs/P2PILOT_001__8x6b__main/P2PILOT_001__8x6b__main.complete.json",
                "config_sha256": "c" * 64,
                "monomer_sha256": "m" * 64,
                "receptor_sha256": "r" * 64,
            }
            sync_root = root / "sync"
            self.make_postprocessed_run(root, row, sync_root, "f" * 64)
            path = root / row["run_id"] / "reports" / f"{row['run_id']}_canonical_contact_summary.csv"
            rows = MOD.read_csv(path)
            rows[0]["status"] = "FAIL"
            write_csv(path, rows)
            _poses, evidence, errors = MOD.evaluate_postprocessed_run(row, root, sync_root, "f" * 64)
            self.assertEqual(evidence["contact_failures"], 1)
            self.assertTrue(any(error.startswith("marker_artifact_hash_mismatch:canonical_contact_summary") for error in errors))

    def test_postprocessed_run_requires_marker_and_rejects_selected_pose_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_root = root / "sync"
            row = {
                "run_id": "P2PILOT_001__8x6b__main",
                "pilot_id": "P2PILOT_001",
                "source_candidate_id": "candidate_1",
                "receptor_id": "8x6b",
                "seed_role": "main",
                "run_dir_relpath": "runs/P2PILOT_001__8x6b__main/run_P2PILOT_001__8x6b__main",
                "completion_relpath": "runs/P2PILOT_001__8x6b__main/P2PILOT_001__8x6b__main.complete.json",
                "config_sha256": "c" * 64,
                "monomer_sha256": "m" * 64,
                "receptor_sha256": "r" * 64,
            }
            self.make_postprocessed_run(root, row, sync_root, "f" * 64)
            marker = root / row["run_id"] / "postprocess.complete.json"
            marker.unlink()
            _poses, _evidence, errors = MOD.evaluate_postprocessed_run(row, root, sync_root, "f" * 64)
            self.assertIn("postprocess_marker_missing", errors)
            self.make_postprocessed_run(root, row, sync_root, "f" * 64)
            pose = next((sync_root / row["run_dir_relpath"] / "6_seletopclusts").glob("*.pdb.gz"))
            pose.write_bytes(b"tampered\n")
            _poses, _evidence, errors = MOD.evaluate_postprocessed_run(row, root, sync_root, "f" * 64)
            self.assertTrue(any(error.startswith("marker_selected_pose_hash_mismatch:") for error in errors))

    def test_package_closure_is_rooted_in_package_audit_and_detects_content_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            manifests = package / "manifests"
            manifests.mkdir(parents=True)
            selection = root / "selection.csv"
            selection.write_text("pilot_id\nP2PILOT_001\n", encoding="utf-8")
            run_manifest = manifests / "run_manifest.csv"
            run_manifest.write_text("run_id\nrun_1\n", encoding="utf-8")
            protocol_manifest = manifests / "protocol_manifest.csv"
            protocol_manifest.write_text("protocol_id\nDG_A_PILOT64_V1_1\n", encoding="utf-8")
            monomer_manifest = manifests / "monomer_manifest.csv"
            monomer_manifest.write_text("pilot_id\nP2PILOT_001\n", encoding="utf-8")
            payload = package / "payload.txt"
            payload.write_text("frozen\n", encoding="utf-8")
            content_manifest = manifests / "package_content_sha256.tsv"
            content_rows = [
                (sha(path), str(path.relative_to(package)))
                for path in (run_manifest, protocol_manifest, monomer_manifest, payload)
            ]
            content_manifest.write_text(
                "sha256\tpath\n" + "".join(f"{digest}\t{path}\n" for digest, path in sorted(content_rows, key=lambda item: item[1])),
                encoding="utf-8",
            )
            audit = {
                "schema_version": "phase2_v3_p2_pilot64_package_audit_v1_1",
                "protocol_id": MOD.PROTOCOL_ID,
                "status": "PASS_PILOT64_DUAL_DOCKING_PACKAGE_READY",
                "pilot_manifest_sha256": sha(selection),
                "run_manifest": "manifests/run_manifest.csv",
                "run_manifest_sha256": sha(run_manifest),
                "protocol_manifest": "manifests/protocol_manifest.csv",
                "protocol_manifest_sha256": sha(protocol_manifest),
                "monomer_manifest": "manifests/monomer_manifest.csv",
                "monomer_manifest_sha256": sha(monomer_manifest),
                "package_content_hash_manifest": "manifests/package_content_sha256.tsv",
                "package_content_hash_manifest_sha256": sha(content_manifest),
                "package_content_hash_scope_exclusions": ["package_audit.json", "manifests/package_content_sha256.tsv"],
                "per_candidate_failure_tolerance_override": False,
                "tolerance_relaxed": False,
            }
            (package / "package_audit.json").write_text(json.dumps(audit), encoding="utf-8")
            evidence, errors = MOD.validate_package_closure(selection, run_manifest)
            self.assertEqual(errors, [])
            self.assertTrue(evidence["checks"]["content_manifest_exact_file_set"])
            payload.write_text("drifted\n", encoding="utf-8")
            _evidence, errors = MOD.validate_package_closure(selection, run_manifest)
            self.assertTrue(any(error.startswith("content_sha256_mismatch:payload.txt") for error in errors))

    def test_manifest_contract_requires_exact_64_plus_16_design(self) -> None:
        selection: list[dict[str, str]] = []
        runs: list[dict[str, str]] = []
        for index in range(1, 65):
            pilot_id = f"P2PILOT_{index:03d}"
            replicate = index <= 16
            selection.append({"pilot_id": pilot_id, "replicate_seed_required": str(replicate).lower()})
            for receptor in MOD.RECEPTORS:
                runs.append({"run_id": f"{pilot_id}_{receptor}_main", "pilot_id": pilot_id, "receptor_id": receptor, "seed_role": "main"})
                if replicate:
                    runs.append({"run_id": f"{pilot_id}_{receptor}_rep", "pilot_id": pilot_id, "receptor_id": receptor, "seed_role": "replicate"})
        _by_id, errors = MOD.manifest_contract(selection, runs)
        self.assertEqual(errors, [])
        self.assertEqual(len(runs), 160)
        _by_id, errors = MOD.manifest_contract(selection, runs[:-1])
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
