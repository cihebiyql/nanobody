#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("prepare_phase2_v4_d_open_teacher.py")
SPEC = importlib.util.spec_from_file_location("prepare_phase2_v4_d_open_teacher", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def split_row(candidate_id: str, model_split: str) -> dict[str, str]:
    row = {field: f"{field}-{candidate_id}" for field in MOD.CANDIDATE_FIELDS}
    row.update(
        candidate_id=candidate_id,
        sequence_sha256=f"sha-{candidate_id}",
        sequence="Q" * 110,
        model_split=model_split,
        cdr1="AAA",
        cdr2="BBB",
        cdr3="CCC",
        cdr3_length="3",
    )
    return row


def pose(model: str, reference: str, multiplier: float = 1.0) -> dict[str, str]:
    return {
        "model": model,
        "scoring_reference": reference,
        "haddock_score": "-10.0",
        "air_energy": "1.0",
        "hotspot_overlap": str(14 * multiplier),
        "anchor_overlap": "7",
        "holdout_overlap": "5",
        "total_occlusion": str(500 * multiplier),
        "cdr3_occlusion": str(100 * multiplier),
        "cdr3_fraction": str(0.15 * multiplier),
        "vhh_pvrig_clash_residue_pairs": "0",
        "vhh_pvrl2_clash_residue_pairs": "10",
        "overlay_rmsd_a": "0.2",
    }


def raw_job(
    job_id: str,
    job_hash: str,
    state: str = "SUCCESS",
    entity_id: str = "open",
    conformation: str = "8x6b",
    seed: str = "917",
) -> dict[str, object]:
    scores = []
    for index in range(4):
        pose_scores = []
        for reference in MOD.CONFORMATIONS:
            pose_scores.append(
                {
                    "reference_id": reference,
                    "hotspot_overlap": {"full": {"count": 14}, "anchor": {"count": 7}, "holdout": {"count": 5}},
                    "vhh_pvrl2_occlusion": {
                        "residue_pair_count": 500,
                        "by_vhh_region_pair_count": {"cdr3": 100},
                        "cdr3_fraction": 0.15,
                    },
                    "clashes_2p5a": {
                        "atom_pair_count": 20,
                        "residue_pair_count": 10,
                        "vhh_pvrig": {"residue_pair_count": 0},
                        "vhh_pvrl2": {"residue_pair_count": 10},
                    },
                    "overlay": {"t_ca_rmsd_a": 0.2},
                }
            )
        scores.append({"pose": f"model_{index}.pdb", "haddock_io": {"score": -100 + index, "unw_energies.air": 1.0}, "scores": pose_scores})
    return {
        "job_id": job_id,
        "job_hash": job_hash,
        "entity_type": "candidate",
        "entity_id": entity_id,
        "dock_conformation": conformation,
        "seed": int(seed),
        "state": state,
        "protocol_core_sha256": MOD.EXPECTED_PROTOCOL_CORE_SHA256,
        "selected_model_count": 4,
        "pose_scores": scores,
    }


class PrepareV4DOpenTeacherTest(unittest.TestCase):
    def test_selects_all_258_open_rows_with_real_v4d_fields(self) -> None:
        rows = [split_row(f"train-{index}", "OPEN_TRAIN") for index in range(226)]
        rows += [split_row(f"dev-{index}", "OPEN_DEVELOPMENT") for index in range(32)]
        rows += [split_row(f"test-{index}", MOD.SEALED_SPLIT) for index in range(32)]
        selected = MOD.select_open_split(rows)
        self.assertEqual(len(selected), 258)
        self.assertEqual({row["model_split"] for row in selected}, {"OPEN_TRAIN", "OPEN_DEVELOPMENT"})
        self.assertTrue(all(set(MOD.CANDIDATE_FIELDS) <= set(row) for row in selected))

    def test_sealed_raw_result_is_not_opened(self) -> None:
        open_jobs = []
        for conformation in MOD.CONFORMATIONS:
            for seed in ("917", "1931", "3253"):
                index = len(open_jobs)
                open_jobs.append({
                    "job_id": f"open-{index}", "job_hash": f"hash-open-{index}",
                    "entity_type": "candidate", "entity_id": "open",
                    "conformation": conformation, "seed": seed,
                })
        sealed_job = {"job_id": "sealed-1", "job_hash": "hash-sealed", "entity_type": "candidate", "entity_id": "sealed"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for job in open_jobs:
                open_path = root / job["job_id"]
                open_path.mkdir()
                (open_path / "job_result.json").write_text(
                    json.dumps(raw_job(
                        job["job_id"], job["job_hash"], entity_id=job["entity_id"],
                        conformation=job["conformation"], seed=job["seed"],
                    )), encoding="utf-8"
                )
            sealed_path = root / "sealed-1"
            sealed_path.mkdir()
            (sealed_path / "job_result.json").write_text("not JSON and must not be opened", encoding="utf-8")
            selected = MOD.select_open_candidate_jobs(open_jobs + [sealed_job], {"open"})
            poses, results, bindings, chain = MOD.raw_pose_rows_for_jobs(root, selected)
        self.assertEqual({row["job_id"] for row in results}, {job["job_id"] for job in open_jobs})
        self.assertEqual({binding["job_id"] for binding in bindings}, {job["job_id"] for job in open_jobs})
        self.assertEqual(len(poses), 48)
        self.assertEqual(
            chain,
            hashlib.sha256(
                json.dumps(bindings, separators=(",", ":"), sort_keys=True).encode("utf-8")
            ).hexdigest(),
        )

    def test_evaluator_old_hash_and_nonpass_fail_closed(self) -> None:
        valid = {
            "status": "PASS", "evidence_mode": "production_pose_backed", "unlockable": True,
            "job_count": 2022, "job_manifest_sha256": MOD.EXPECTED_JOB_MANIFEST_SHA256,
            "protocol_lock_sha256": MOD.EXPECTED_PROTOCOL_LOCK_SHA256,
            "protocol_core_sha256": MOD.EXPECTED_PROTOCOL_CORE_SHA256,
            "candidates_sha256": MOD.EXPECTED_CANDIDATES_SHA256,
            "stability_gate_spec_sha256": MOD.EXPECTED_STABILITY_SPEC_SHA256,
            "job_set_hash": "job-set", "gates": {"all_jobs_terminal": {"status": "PASS"}},
        }
        old_hash = dict(valid, protocol_lock_sha256="6ea729edc9b070bba7271bea3c64da0fffad46921ea8899548eb9b1ad8a120a7")
        with self.assertRaises(MOD.TeacherBuildError):
            MOD.validate_evaluator(old_hash)
        nonpass = dict(valid, status="FAIL")
        with self.assertRaises(MOD.TeacherBuildError):
            MOD.validate_evaluator(nonpass)

    def test_continuous_scores_and_strict_a_boundary_are_raw_derived(self) -> None:
        just_below = pose("m", "8x6b", 1.0)
        just_below["cdr3_occlusion"] = "99.999999999"
        self.assertFalse(MOD.is_strict_a(just_below))
        at_boundary = pose("m", "8x6b", 1.0)
        self.assertTrue(MOD.is_strict_a(at_boundary))
        low = MOD.native_pose_utility(pose("m", "8x6b", 0.5))
        high = MOD.native_pose_utility(pose("m", "8x6b", 1.5))
        self.assertGreater(high, low)
        rows = [pose(f"m{index}", reference) for index in range(4) for reference in MOD.CONFORMATIONS]
        summary = MOD.job_summary("job", "8x6b", rows)
        self.assertEqual(summary["model_strict_a_fraction"], 1.0)
        self.assertEqual(summary["model_pair_consensus_fraction"], 1.0)
        self.assertEqual(summary["native_cross_support_agreement"], 1.0)

    def test_robustness_matches_frozen_ab_pair_semantics(self) -> None:
        rows = []
        model_classes = (("A", "A"), ("B", "B"), ("B", "B"), ("E", "E"))
        metrics = {
            "A": (14, 500, 100, 0.15),
            "B": (10, 100, 20, 0.10),
            "E": (1, 1, 1, 0.01),
        }
        for index, classes in enumerate(model_classes):
            for reference, geometry_class in zip(MOD.CONFORMATIONS, classes):
                row = pose(f"m{index}", reference)
                hotspot, total, cdr3, fraction = metrics[geometry_class]
                row.update(
                    hotspot_overlap=str(hotspot),
                    total_occlusion=str(total),
                    cdr3_occlusion=str(cdr3),
                    cdr3_fraction=str(fraction),
                )
                rows.append(row)
        summary = MOD.job_summary("job", "8x6b", rows)
        self.assertEqual(summary["native_cross_support_agreement"], 1.0)
        self.assertEqual(summary["model_pair_consensus_fraction"], 0.5)
        self.assertEqual(summary["model_strict_a_fraction"], 0.25)

    def test_raw_rows_must_match_evaluator_bound_open_aggregate(self) -> None:
        job = {
            "job_id": "job", "job_hash": "hash", "entity_type": "candidate",
            "entity_id": "open", "conformation": "8x6b", "seed": "917",
        }
        with tempfile.TemporaryDirectory() as directory:
            result_dir = Path(directory) / "job"
            result_dir.mkdir()
            (result_dir / "job_result.json").write_text(
                json.dumps(raw_job("job", "hash")), encoding="utf-8"
            )
            poses, results, bindings, _chain = MOD.raw_pose_rows_for_jobs(
                Path(directory), [job]
            )
        summary = MOD.job_summary("job", "8x6b", poses)
        aggregate_result = {
            "job_id": "job", "job_hash": "hash", "state": "SUCCESS",
            "selected_model_count": "4", "pose_backed_2x2": "true",
            "model_pair_consensus_fraction": f"{summary['model_pair_consensus_fraction']:.6f}",
            "model_native_cross_support_agreement_fraction": f"{summary['native_cross_support_agreement']:.6f}",
            "model_strict_a_fraction": f"{summary['model_strict_a_fraction']:.6f}",
        }
        aggregate_poses = []
        for row in poses:
            aggregate_poses.append({
                **row,
                "geometry_class": MOD.classify_geometry(row),
            })
        receipt = MOD.verify_raw_aggregate_closure(
            [job], results, poses, [aggregate_result], aggregate_poses, bindings
        )
        self.assertEqual(
            receipt["status"],
            "PASS_RAW_OPEN_RESULTS_MATCH_EVALUATOR_BOUND_AGGREGATES",
        )
        aggregate_poses[0]["hotspot_overlap"] = "999"
        with self.assertRaisesRegex(MOD.TeacherBuildError, "metric_mismatch"):
            MOD.verify_raw_aggregate_closure(
                [job], results, poses, [aggregate_result], aggregate_poses, bindings
            )

    def test_candidate_teacher_does_not_emit_obsolete_split_fields(self) -> None:
        row = split_row("candidate", "OPEN_DEVELOPMENT")
        summaries = []
        for conformation in MOD.CONFORMATIONS:
            for value in (0.2, 0.4):
                summaries.append({
                    "dock_conformation": conformation, "job_utility": value,
                    "native_cross_support_agreement": 1.0, "model_pair_consensus_fraction": 1.0,
                    "model_strict_a_fraction": 1.0, "model_count_reliability": 1.0,
                    "agreement_reliability": 1.0, **{field: 1.0 for field in (
                        "hotspot_overlap", "anchor_overlap", "holdout_overlap", "total_occlusion",
                        "cdr3_occlusion", "cdr3_fraction", "vhh_pvrig_clash_residue_pairs",
                        "vhh_pvrl2_clash_residue_pairs", "overlay_rmsd_a")},
                })
        teacher = MOD.build_candidate_teacher(row, summaries)
        self.assertEqual(teacher["parent_framework_cluster"], row["parent_framework_cluster"])
        self.assertNotIn("scaffold_id", teacher)
        self.assertAlmostEqual(teacher["R_dual_min"], 0.3)


if __name__ == "__main__":
    unittest.main()
