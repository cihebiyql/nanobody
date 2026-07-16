#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True
MODULE_PATH = Path(__file__).with_name("prepare_pvrig_submission_release.py")
SPEC = importlib.util.spec_from_file_location("prepare_pvrig_submission_release", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_table(path: Path, rows: list[dict[str, str]], delimiter: str = "\t") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(rows[0]), delimiter=delimiter, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sequence(index: int) -> str:
    alphabet = "ACDEFGHIKLMNPQRSTVWY"
    return "Q" * 98 + alphabet[index // len(alphabet)] + alphabet[index % len(alphabet)]


def build_fixture(root: Path) -> dict[str, Path]:
    shortlist = root / "shortlist50.tsv"
    shortlist_audit = root / "geometry_shortlist_audit.json"
    top10_selection = root / "top10_selection.tsv"
    pose_manifest = root / "pose_bundle" / "pose_review_manifest.tsv"
    pose_audit = root / "pose_bundle" / "pose_review_audit.json"
    pose_verdicts = root / "pose_review_verdicts.tsv"

    shortlist_rows: list[dict[str, str]] = []
    for index in range(50):
        candidate = f"CAND_{index + 1:03d}"
        seq = sequence(index)
        row = {field: "" for field in sorted(MOD.SHORTLIST_REQUIRED)}
        row.update(
            {
                "candidate_id": candidate,
                "rank": str(index + 1),
                "sequence": seq,
                "sequence_sha256": hashlib.sha256(seq.encode("ascii")).hexdigest(),
                "source_cohort": "FULLQC290_PRIMARY",
                "parent_id": f"PARENT_{index % 20:02d}",
                "scaffold_id": "",
                "target_patch_id": ("A_CENTER", "B_LOWER", "C_CROSS")[index % 3],
                "design_mode": "H1H3" if index % 2 else "H3",
                "cdr1": "GFTFSSYA",
                "cdr2": "ISYDGSNK",
                "cdr3": f"AR{sequence(index)[-2:]}GYYYY",
                "cdr3_length": "9",
                "fast_hard_fail": "False",
                "full_qc_status": "COMPLETE_HARD_PASS_ABNATIV_COMPLETE",
                "official_validator_pass": "PASS",
                "anarci_status": "True",
                "imgt_chain_type": "H",
                "abnativ_status": "SCORED",
                "max_positive_cdr_identity": "0.55",
                "exact_positive_id": "",
                "leakage_status": "PROSPECTIVE_GENERATED_NOT_KNOWN_POSITIVE_OR_DERIVATIVE",
                "developability_score": "95.0",
                "expression_purity_risk_score": "90.0",
                "abnativ_vhh_score": "0.91",
                "generic_binding_prior": "0.61",
                "generic_prior_claim_boundary": MOD.GENERIC_PRIOR_CLAIM_BOUNDARY,
                "monomer_status": "FROZEN_NBB2_SEQUENCE_VERIFIED",
                "monomer_sha256": hashlib.sha256(candidate.encode("ascii")).hexdigest(),
                "monomer_sequence_match": "true",
                "geometry_status": "OPEN_AVAILABLE_V4D_COMPUTATIONAL_GEOMETRY",
                "r_8x6b": f"{0.9 - index / 1000:.6f}",
                "r_9e6y": f"{0.8 - index / 1000:.6f}",
                "r_dual_min": f"{0.8 - index / 1000:.6f}",
                "r_dual_gap": "0.1",
                "geometry_uncertainty": "0.02",
                "successful_seeds_8x6b": "3",
                "successful_seeds_9e6y": "3",
                "full_sequence_cluster": f"FULL_{index % 25:02d}",
                "cdr3_cluster": f"CDR3_{index % 25:02d}",
                "angle_family": f"ANGLE_{index % 8:02d}",
                "v4d_teacher_model_split": "OPEN_TRAIN" if index % 4 else "OPEN_DEVELOPMENT",
                "geometry_rank_score": f"{1.0 - index / 100:.6f}",
                "selection_reason": "R_DUAL_MIN_PRIMARY_GEOMETRY_WITH_DIVERSITY_CAPS",
                "ranking_claim_boundary": MOD.RANKING_CLAIM_BOUNDARY,
                "backbone_index": str(index % 12),
                "mpnn_index": str(index % 3),
                "arm_id": "",
                "h3_regime": "balanced",
                "backbone_group_id": "",
            }
        )
        shortlist_rows.append(row)
    all_fields = list(shortlist_rows[0])
    for extra in ("backbone_index", "mpnn_index", "arm_id", "h3_regime", "backbone_group_id"):
        if extra not in all_fields:
            all_fields.append(extra)
    normalized_rows = [{field: row.get(field, "") for field in all_fields} for row in shortlist_rows]
    write_table(shortlist, normalized_rows)
    write_json(
        shortlist_audit,
        {
            "schema_version": "pvrig_geometry_shortlist_audit_v1",
            "status": "PASS_OPEN_GEOMETRY_SHORTLIST",
            "eligible_open_rows": 258,
            "sealed_fullqc_excluded_count": 32,
            "shortlist_count": 50,
            "shortlist_parent_max": 3,
            "shortlist_parent_patch_mode_max": 1,
            "shortlist_cdr3_cluster_max": 2,
            "output_sha256": {
                "shortlist50": hashlib.sha256(shortlist.read_bytes()).hexdigest()
            },
        },
    )

    top10_rows = [
        {
            "candidate_id": shortlist_rows[index]["candidate_id"],
            "portfolio_rank": str(index + 1),
            "selection_reason": "MANUAL_COMPUTATIONAL_POSE_ACCEPTANCE_AND_DIVERSITY",
        }
        for index in range(10)
    ]
    write_table(top10_selection, top10_rows)
    verdict_rows = [
        {
            "candidate_id": shortlist_rows[index]["candidate_id"],
            "verdict": "ACCEPT_COMPUTATIONAL_PRIORITY" if index < 10 else "REVIEW_DEVELOPABILITY",
            "reviewer": "fixture_reviewer",
            "review_notes": "Fixture manual computational review note.",
        }
        for index in range(20)
    ]
    write_table(pose_verdicts, verdict_rows)

    pose_rows: list[dict[str, str]] = []
    for index in range(20):
        candidate = shortlist_rows[index]["candidate_id"]
        for conformation in ("8x6b", "9e6y"):
            for seed in ("917", "1931", "3253"):
                for model_index in range(3):
                    model = f"cluster_{model_index + 1}_model_1.pdb.gz"
                    relative = Path(candidate) / conformation / seed / model
                    pose = pose_manifest.parent / relative
                    pose.parent.mkdir(parents=True, exist_ok=True)
                    with gzip.GzipFile(filename=str(pose), mode="wb", mtime=0) as handle:
                        handle.write(f"MODEL {model_index + 1}\nEND\n".encode("ascii"))
                    digest = hashlib.sha256(pose.read_bytes()).hexdigest()
                    summary = json.dumps(
                        {
                            "reference_id": conformation,
                            "hotspot_full_count": 15,
                            "total_occlusion": 550,
                            "cdr3_occlusion": 120,
                            "cdr3_fraction": 0.2,
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    pose_rows.append(
                        {
                            "candidate_id": candidate,
                            "rank": str(index + 1),
                            "conformation": conformation,
                            "seed": seed,
                            "job_id": f"JOB_{candidate}_{conformation}_{seed}",
                            "job_hash": hashlib.sha256(f"{candidate}{conformation}{seed}".encode()).hexdigest(),
                            "model": model,
                            "HADDOCK_score": str(-60 + model_index),
                            "geometry_8x6b_summary": summary,
                            "geometry_9e6y_summary": summary,
                            "source_sha256": digest,
                            "target_sha256": digest,
                            "bundle_relpath": relative.as_posix(),
                            "claim_boundary": MOD.CLAIM_BOUNDARY,
                        }
                    )
    write_table(pose_manifest, pose_rows)
    write_json(
        pose_audit,
        {
            "schema_version": "pvrig_top20_pose_review_bundle_v2",
            "status": "PASS_OPEN_ONLY_V4D_POSE_REVIEW",
            "candidate_count": 20,
            "successful_job_count": 120,
            "manifest_pose_count": 360,
            "input_sha256": {"shortlist": hashlib.sha256(shortlist.read_bytes()).hexdigest()},
            "output_sha256": {
                "manifest": hashlib.sha256(pose_manifest.read_bytes()).hexdigest()
            },
        },
    )
    return {
        "shortlist": shortlist,
        "shortlist_audit": shortlist_audit,
        "top10_selection": top10_selection,
        "pose_manifest": pose_manifest,
        "pose_audit": pose_audit,
        "pose_verdicts": pose_verdicts,
    }


def args_for(inputs: dict[str, Path], outdir: Path):
    return MOD.parse_args(
        [
            "--shortlist", str(inputs["shortlist"]),
            "--shortlist-audit", str(inputs["shortlist_audit"]),
            "--top10-selection", str(inputs["top10_selection"]),
            "--pose-manifest", str(inputs["pose_manifest"]),
            "--pose-audit", str(inputs["pose_audit"]),
            "--pose-verdicts", str(inputs["pose_verdicts"]),
            "--outdir", str(outdir),
        ]
    )


class SubmissionReleaseTests(unittest.TestCase):
    def test_builds_deterministic_release_and_clean_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            first = root / "first"
            second = root / "second"
            audit = MOD.run(args_for(inputs, first))
            self.assertEqual(audit["status"], "PASS_COMPUTATIONAL_SUBMISSION_PACKAGE_READY")
            self.assertEqual(audit["top50_count"], 50)
            self.assertEqual(audit["top10_count"], 10)
            self.assertEqual(audit["top10_copied_pose_count"], 180)
            self.assertEqual((first / "submission_top10.fasta").read_text().count(">"), 10)
            self.assertEqual(len(list((first / "submission_top10_dossier").glob("*/DOSSIER.md"))), 10)
            self.assertEqual(len(list((first / "submission_top10_dossier").glob("*/poses/**/*.pdb.gz"))), 180)

            MOD.run(args_for(inputs, second))
            self.assertEqual((first / "SHA256SUMS").read_bytes(), (second / "SHA256SUMS").read_bytes())
            self.assertEqual(
                hashlib.sha256((first / "pvrig_submission_release_v1.tar.gz").read_bytes()).hexdigest(),
                hashlib.sha256((second / "pvrig_submission_release_v1.tar.gz").read_bytes()).hexdigest(),
            )
            environment = dict(os.environ, PYTHON=sys.executable)
            completed = subprocess.run(
                [str(first / "clean_replay.sh")],
                check=True,
                text=True,
                capture_output=True,
                env=environment,
            )
            self.assertIn("PASS_CLEAN_REPLAY_BYTE_IDENTICAL", completed.stdout)
            receipt = json.loads((first / "clean_replay_receipt.json").read_text())
            self.assertEqual(receipt["status"], "PASS_CLEAN_REPLAY_BYTE_IDENTICAL")

            (first / "submission_top50.fasta").write_text("tampered\n", encoding="ascii")
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(
                    [str(first / "clean_replay.sh")],
                    check=True,
                    text=True,
                    capture_output=True,
                    env=environment,
                )

    def test_sealed_candidate_fails_before_pose_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            fields, rows, _ = MOD.read_table(inputs["shortlist"])
            rows[0]["v4d_teacher_model_split"] = "PROSPECTIVE_COMPUTATIONAL_TEST"
            write_table(inputs["shortlist"], rows)
            for pose in inputs["pose_manifest"].parent.glob("**/*.pdb.gz"):
                pose.unlink()
            with self.assertRaisesRegex(MOD.ReleaseError, "Refusing sealed/test candidate before pose access"):
                MOD.run(args_for(inputs, root / "release"))

    def test_missing_top10_pose_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            pose = next(inputs["pose_manifest"].parent.glob("CAND_001/**/*.pdb.gz"))
            pose.unlink()
            with self.assertRaisesRegex(MOD.ReleaseError, "Missing Top20 pose source"):
                MOD.run(args_for(inputs, root / "release"))

    def test_missing_non_top10_pose_also_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            pose = next(inputs["pose_manifest"].parent.glob("CAND_011/**/*.pdb.gz"))
            pose.unlink()
            with self.assertRaisesRegex(MOD.ReleaseError, "Missing Top20 pose source"):
                MOD.run(args_for(inputs, root / "release"))

    def test_unaccepted_top10_verdict_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["pose_verdicts"])
            rows[0]["verdict"] = "REJECT_IMPLAUSIBLE_POSE"
            write_table(inputs["pose_verdicts"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "unresolved/rejected pose verdict"):
                MOD.run(args_for(inputs, root / "release"))

    def test_top10_diversity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            for row in rows[:3]:
                row["parent_id"] = "TOP10_DOMINANT_PARENT"
            write_table(inputs["shortlist"], rows)
            shortlist_audit = json.loads(inputs["shortlist_audit"].read_text())
            shortlist_audit["output_sha256"]["shortlist50"] = hashlib.sha256(inputs["shortlist"].read_bytes()).hexdigest()
            write_json(inputs["shortlist_audit"], shortlist_audit)
            audit = json.loads(inputs["pose_audit"].read_text())
            audit["input_sha256"]["shortlist"] = hashlib.sha256(inputs["shortlist"].read_bytes()).hexdigest()
            write_json(inputs["pose_audit"], audit)
            with self.assertRaisesRegex(MOD.ReleaseError, ">=4 parent families"):
                MOD.run(args_for(inputs, root / "release"))

    def test_actual_top50_diversity_is_recomputed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            for row in rows[:40]:
                row["parent_id"] = "DOMINANT_PARENT"
            write_table(inputs["shortlist"], rows)
            audit = json.loads(inputs["shortlist_audit"].read_text())
            audit["output_sha256"]["shortlist50"] = hashlib.sha256(inputs["shortlist"].read_bytes()).hexdigest()
            write_json(inputs["shortlist_audit"], audit)
            pose_audit = json.loads(inputs["pose_audit"].read_text())
            pose_audit["input_sha256"]["shortlist"] = hashlib.sha256(inputs["shortlist"].read_bytes()).hexdigest()
            write_json(inputs["pose_audit"], pose_audit)
            with self.assertRaisesRegex(MOD.ReleaseError, "Actual Top50 parent cap"):
                MOD.run(args_for(inputs, root / "release"))

    def test_claim_boundary_drift_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            rows[0]["ranking_claim_boundary"] = "PROVEN BLOCKING"
            write_table(inputs["shortlist"], rows)
            audit = json.loads(inputs["shortlist_audit"].read_text())
            audit["output_sha256"]["shortlist50"] = hashlib.sha256(inputs["shortlist"].read_bytes()).hexdigest()
            write_json(inputs["shortlist_audit"], audit)
            with self.assertRaisesRegex(MOD.ReleaseError, "claim boundary drift"):
                MOD.run(args_for(inputs, root / "release"))

    def test_pose_model_path_traversal_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["pose_manifest"])
            rows[0]["model"] = "../../escape.pdb.gz"
            write_table(inputs["pose_manifest"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "Unsafe pose model"):
                MOD.run(args_for(inputs, root / "release"))

    def test_cross_candidate_pose_substitution_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["pose_manifest"])
            source = next(
                row for row in rows
                if row["candidate_id"] == "CAND_002"
                and row["conformation"] == "8x6b"
                and row["seed"] == "917"
                and row["model"] == "cluster_1_model_1.pdb.gz"
            )
            target = next(
                row for row in rows
                if row["candidate_id"] == "CAND_001"
                and row["conformation"] == "8x6b"
                and row["seed"] == "917"
                and row["model"] == "cluster_1_model_1.pdb.gz"
            )
            for field in ("bundle_relpath", "source_sha256", "target_sha256"):
                target[field] = source[field]
            write_table(inputs["pose_manifest"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "not identity-bound"):
                MOD.run(args_for(inputs, root / "release"))

    def test_non_top10_duplicate_model_and_target_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["pose_manifest"])
            job_rows = [
                row for row in rows
                if row["candidate_id"] == "CAND_011"
                and row["conformation"] == "8x6b"
                and row["seed"] == "917"
            ]
            for field in ("model", "bundle_relpath", "source_sha256", "target_sha256"):
                job_rows[1][field] = job_rows[0][field]
            write_table(inputs["pose_manifest"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "Duplicate pose model identity"):
                MOD.run(args_for(inputs, root / "release"))

    def test_pose_manifest_must_match_pose_audit_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["pose_manifest"])
            rows[0]["HADDOCK_score"] = "-999"
            write_table(inputs["pose_manifest"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "not hash-bound"):
                MOD.run(args_for(inputs, root / "release"))

    def test_sequence_hash_and_known_positive_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            rows[0]["sequence_sha256"] = "0" * 64
            write_table(inputs["shortlist"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "Sequence SHA256 mismatch"):
                MOD.run(args_for(inputs, root / "hash_fail"))

            inputs = build_fixture(root / "second")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            rows[0]["exact_positive_id"] = "HR-151"
            write_table(inputs["shortlist"], rows)
            with self.assertRaisesRegex(MOD.ReleaseError, "Exact positive identity"):
                MOD.run(args_for(inputs, root / "positive_fail"))

    def test_requires_exactly_fifty_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = build_fixture(root / "inputs")
            _fields, rows, _ = MOD.read_table(inputs["shortlist"])
            write_table(inputs["shortlist"], rows[:-1])
            with self.assertRaisesRegex(MOD.ReleaseError, "exactly 50 rows"):
                MOD.run(args_for(inputs, root / "release"))


if __name__ == "__main__":
    unittest.main()
