#!/usr/bin/env python3

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BASE = ROOT.parent
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(BASE / "src"))

from evaluate_authorized_v2_5_strict_meta_v1 import MODEL_IDS, fit_predict_outer_models
from execution_common_v1 import sha256_file, sha256_text


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_tsv(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


class SyntheticClosure:
    def __init__(self, root: Path, terminal: bool):
        self.root = root
        self.package = root / "upstream_package"
        self.runtime = root / "upstream_runtime"
        self.inputs = root / "adapter_inputs"
        self.output = root / "closure"
        for path in (self.package, self.runtime, self.inputs): path.mkdir(parents=True)
        self.labels = []
        for index in range(10):
            r8 = 0.48 + 0.01 * index
            r9 = 0.47 + 0.008 * index
            self.labels.append({
                "candidate_id": f"C{index}", "teacher_source": "S0" if index < 5 else "S1",
                "parent_framework_cluster": f"P{index}", "outer_fold": str(index % 5),
                "R_8X6B": str(r8), "R_9E6Y": str(r9), "R_dual_min": str(min(r8, r9)),
                "development_reliability_tier": "A" if index < 5 else "B",
                "seed_dispersion_max": "0.02",
            })
        outer, inner = [], []
        for fold in range(5):
            train = [row for row in self.labels if int(row["outer_fold"]) != fold]
            assignment = {row["parent_framework_cluster"]: i % 5 for i, row in enumerate(train)}
            for row in self.labels:
                outer.append({
                    "outer_fold": str(fold), "candidate_id": row["candidate_id"],
                    "teacher_source": row["teacher_source"], "parent_framework_cluster": row["parent_framework_cluster"],
                    "candidate_role": "score" if int(row["outer_fold"]) == fold else "train",
                })
            for inner_fold in range(5):
                for row in train:
                    inner.append({
                        "outer_fold": str(fold), "inner_fold": str(inner_fold),
                        "candidate_id": row["candidate_id"], "teacher_source": row["teacher_source"],
                        "parent_framework_cluster": row["parent_framework_cluster"],
                        "candidate_role": "score" if assignment[row["parent_framework_cluster"]] == inner_fold else "train",
                    })
        write_tsv(self.inputs / "labels.tsv", self.labels)
        write_tsv(self.inputs / "outer.tsv", outer)
        write_tsv(self.inputs / "inner.tsv", inner)
        write_tsv(self.inputs / "raw.tsv", [{"candidate_id": row["candidate_id"], "dual__x": "1"} for row in self.labels])
        c2 = []
        for row in self.labels:
            p8, p9 = float(row["R_8X6B"]) + .001, float(row["R_9E6Y"]) - .001
            c2.append({
                "model_id": "C2_INNER_SELECTED_PCA8_RIDGE", "candidate_id": row["candidate_id"],
                "outer_fold": row["outer_fold"], "teacher_source": row["teacher_source"],
                "parent_framework_cluster": row["parent_framework_cluster"], "selected_c2_alpha": "10",
                "pred_R8": str(p8), "pred_R9": str(p9), "pred_Rdual": str(min(p8, p9)),
            })
        write_tsv(self.inputs / "c2.tsv", c2)
        write_tsv(self.inputs / "alpha.tsv", [{"outer_fold": str(f), "alpha": "10", "selected": "true"} for f in range(5)])

        jobs = []
        for fold in range(5):
            evidence = self.runtime / "evidence" / "D_SPLIT_PAIR" / f"outer_{fold}"
            inner_expected = [row for row in inner if int(row["outer_fold"]) == fold and row["candidate_role"] == "score"]
            outer_expected = [row for row in outer if int(row["outer_fold"]) == fold and row["candidate_role"] == "score"]
            for role, expected in (("inner", inner_expected), ("outer", outer_expected)):
                rows = []
                for expected_row in expected:
                    label = next(row for row in self.labels if row["candidate_id"] == expected_row["candidate_id"])
                    rows.append({
                        "schema_version": "synthetic", "evidence_role": "INNER_OOF_BASE_FEATURE" if role == "inner" else "OUTER_TEST_BASE_FEATURE",
                        "candidate_id": label["candidate_id"], "teacher_source": label["teacher_source"],
                        "parent_framework_cluster": label["parent_framework_cluster"], "outer_fold": str(fold),
                        "inner_fold": expected_row.get("inner_fold", "NONE") if role == "inner" else "NONE",
                        "R_8X6B": label["R_8X6B"], "R_9E6Y": label["R_9E6Y"], "R_dual_min": label["R_dual_min"],
                        "M2_R8": label["R_8X6B"], "neural_R8": label["R_8X6B"], "contact_score_R8": "0.2",
                        "M2_R9": label["R_9E6Y"], "neural_R9": label["R_9E6Y"], "contact_score_R9": "0.2",
                    })
                tsv = evidence / f"{role}_oof_base.tsv" if role == "inner" else evidence / "outer_test_base.tsv"
                if role == "inner":
                    tsv = evidence / "inner_oof_base.tsv"
                    validation = evidence / "inner_oof_base.validation.json"
                    provenance = evidence / "inner_oof_provenance.json"
                    manifest_name = "inner_manifest"
                else:
                    validation = evidence / "outer_test_base.validation.json"
                    provenance = evidence / "outer_test_provenance.json"
                    manifest_name = "outer_manifest"
                write_tsv(tsv, rows)
                write_json(provenance, {"sealed_evaluation_access_count": 0})
                # Hash is filled after the contract input specifications exist below.
                jobs.extend([tsv, validation, provenance])
                setattr(self, f"pending_validation_{fold}_{role}", (validation, tsv, provenance, manifest_name, len(rows)))

        package_manifest = self.package / "PACKAGE_MANIFEST.json"
        upstream_overlay = self.package / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
        launch = self.runtime / "AUTHORIZED_LAUNCH_RECEIPT.json"
        write_json(package_manifest, {"sealed_evaluation_access_count": 0})
        write_json(upstream_overlay, {"sealed_evaluation_access_count": 0})
        graph_path = self.package / "plan" / "job_graph.json"
        graph = {
            "job_counts": {"GPU_BASE_TRAIN_INNER": 0, "GPU_BASE_REFIT_OUTER_TRAIN": 0},
            "jobs": [{"job_id": f"J{i}", "expected_result": str(path)} for i, path in enumerate(jobs)],
            "sealed_evaluation_access_count": 0,
        }
        write_json(graph_path, graph)
        write_json(launch, {"job_count": len(jobs), "job_graph_sha256": sha256_file(graph_path), "sealed_evaluation_access_count": 0})

        canonical = {
            "labels": {"filename": "labels.tsv", "sha256": sha256_file(self.inputs / "labels.tsv")},
            "outer_manifest": {"filename": "outer.tsv", "sha256": sha256_file(self.inputs / "outer.tsv")},
            "inner_manifest": {"filename": "inner.tsv", "sha256": sha256_file(self.inputs / "inner.tsv")},
            "coarse_pose_raw36": {"filename": "raw.tsv", "sha256": sha256_file(self.inputs / "raw.tsv")},
            "existing_c2_outer_oof": {"filename": "c2.tsv", "sha256": sha256_file(self.inputs / "c2.tsv")},
            "existing_c2_alpha_selection": {"filename": "alpha.tsv", "sha256": sha256_file(self.inputs / "alpha.tsv")},
        }
        for fold in range(5):
            for role in ("inner", "outer"):
                validation, tsv, provenance, manifest_name, count = getattr(self, f"pending_validation_{fold}_{role}")
                write_json(validation, {
                    "status": "PASS_SYNTHETIC", "candidate_count": count,
                    "evidence_role": "INNER_OOF_BASE_FEATURE" if role == "inner" else "OUTER_TEST_BASE_FEATURE",
                    "evidence_tsv_sha256": sha256_file(tsv), "provenance_json_sha256": sha256_file(provenance),
                    "split_manifest_sha256": canonical[manifest_name]["sha256"],
                    "sealed_evaluation_access_count": 0,
                })
        # Validation files changed after the graph was written, but paths and graph hash remain valid.
        contract = {
            "status": "FROZEN_DESIGN_UNAUTHORIZED_DO_NOT_EVALUATE",
            "claim_boundary": "synthetic",
            "upstream_v2_4_strict": {
                "job_graph_sha256": sha256_file(graph_path), "package_manifest_sha256": sha256_file(package_manifest),
                "authorization_overlay_sha256": sha256_file(upstream_overlay), "launch_receipt_sha256": sha256_file(launch),
                "expected_terminal": {"status": "PASS", "returncode": 0},
                "expected_job_counts": {"total": len(jobs), "gpu": 0, "cpu": len(jobs)},
                "allowed_lane": "D_SPLIT_PAIR", "forbidden_lanes_as_v2_5_predictors": ["B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL"],
            },
            "canonical_inputs": canonical,
            "expected_counts": {
                "candidates": 10, "parents": 10, "outer_folds": 5, "inner_folds_per_outer": 5,
                "tier_counts": {"A": 5, "B": 5}, "source_counts": {"S0": 5, "S1": 5},
            },
            "authorization": {"execution_authorized": False, "required_token_sha256": sha256_text("GOOD")},
        }
        self.contract = root / "contract.json"
        write_json(self.contract, contract)
        if terminal:
            write_json(self.runtime / "TERMINAL.json", {"status": "PASS", "returncode": 0, "sealed_evaluation_access_count": 0})

    def command(self, allow_waiting=False):
        command = [
            sys.executable, str(SRC / "validate_v1_2_1_strict_inputs_v1.py"),
            "--contract", str(self.contract), "--package-root", str(self.package),
            "--runtime-root", str(self.runtime), "--input-root", str(self.inputs),
            "--output-dir", str(self.output),
        ]
        if allow_waiting: command.append("--allow-waiting")
        return command


class ExecutionAdapterTests(unittest.TestCase):
    def test_waiting_receipt_does_not_open_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticClosure(Path(tmp), terminal=False)
            # Invalid D evidence is deliberately tolerated before terminal closure.
            (fixture.runtime / "evidence/D_SPLIT_PAIR/outer_0/inner_oof_base.tsv").write_text("BROKEN\n")
            result = subprocess.run(fixture.command(allow_waiting=True), check=False)
            self.assertEqual(result.returncode, 0)
            receipt = json.loads((fixture.output / "INPUT_CLOSURE_RECEIPT.json").read_text())
            self.assertEqual(receipt["status"], "WAITING_STRICT_V1_2_1_TERMINAL")
            self.assertFalse(receipt["performance_evaluation_performed"])

    def test_terminal_input_closure_passes_and_ignores_B_C(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticClosure(Path(tmp), terminal=True)
            for lane in ("B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL"):
                path = fixture.runtime / "evidence" / lane / "outer_0" / "outer_test_base.tsv"
                path.parent.mkdir(parents=True); path.write_text("INTENTIONALLY_INVALID\n")
            result = subprocess.run(fixture.command(), check=False)
            self.assertEqual(result.returncode, 0)
            receipt = json.loads((fixture.output / "INPUT_CLOSURE_RECEIPT.json").read_text())
            self.assertEqual(receipt["status"], "PASS_INPUTS_READY_UNAUTHORIZED")
            self.assertEqual(receipt["closed_job_result_count"], 30)
            self.assertEqual(receipt["allowed_lane_read"], "D_SPLIT_PAIR")
            self.assertEqual(receipt["forbidden_lane_predictor_read_count"], 0)

    def test_missing_job_result_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = SyntheticClosure(Path(tmp), terminal=True)
            (fixture.runtime / "evidence/D_SPLIT_PAIR/outer_4/outer_test_provenance.json").unlink()
            result = subprocess.run(fixture.command(), check=False)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads((fixture.output / "INPUT_CLOSURE_RECEIPT.json").read_text())
            self.assertEqual(receipt["status"], "FAIL_INPUT_CLOSURE")
            self.assertIn("job_result_closure_missing", receipt["error"])

    def test_watcher_invokes_validator_only(self):
        source = (SRC / "watch_v1_2_1_terminal_then_validate_v1.py").read_text()
        self.assertNotIn("evaluate_authorized_v2_5", source)
        self.assertIn("validate_v1_2_1_strict_inputs_v1", (SRC / "validate_v1_2_1_strict_inputs_v1.py").name)
        self.assertNotIn("FORMAL_METRICS", (SRC / "validate_v1_2_1_strict_inputs_v1.py").read_text())
        launcher = (SRC / "launch_node1_input_closure_watcher_v1.py").read_text()
        self.assertNotIn("evaluate_authorized_v2_5_strict_meta_v1.py\"),", launcher.split("command = [", 1)[1])
        self.assertIn("watch_v1_2_1_terminal_then_validate_v1.py", launcher)

    def test_evaluator_rejects_bad_token_before_data_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "manifest.json"; closure = root / "closure.json"; overlay = root / "overlay.json"
            write_json(manifest, {
                "status": "FROZEN_UNAUTHORIZED_INPUT_VALIDATION_ONLY", "execution_authorized": False,
                "formal_model_matrix": [{"model_id": value} for value in MODEL_IDS],
                "authorization_requirements": {"required_token_sha256": sha256_text("GOOD")},
            })
            write_json(closure, {"status": "PASS_INPUTS_READY_UNAUTHORIZED", "execution_authorized": False})
            write_json(overlay, {
                "schema_version": "pvrig_v2_5_strict_meta_authorization_overlay_v1",
                "status": "EXPLICITLY_AUTHORIZED", "execution_authorized": True,
                "execution_manifest_sha256": sha256_file(manifest),
                "input_closure_receipt_sha256": sha256_file(closure),
                "authorization_token_sha256": sha256_text("GOOD"),
            })
            output = root / "formal"
            result = subprocess.run([
                sys.executable, str(SRC / "evaluate_authorized_v2_5_strict_meta_v1.py"),
                "--execution-manifest", str(manifest), "--input-closure-receipt", str(closure),
                "--authorization-overlay", str(overlay), "--authorization-token", "BAD",
                "--contract", str(root / "DOES_NOT_EXIST"), "--input-root", str(root / "NO_INPUT"),
                "--runtime-root", str(root / "NO_RUNTIME"), "--output-dir", str(output),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("authorization_token_hash", result.stderr)
            self.assertFalse(output.exists())

    def test_manifest_builder_freezes_exact_matrix_and_remains_unauthorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "manifest.json"
            result = subprocess.run([
                sys.executable, str(SRC / "build_execution_manifest_v1.py"),
                "--contract", str(ROOT / "EXECUTION_CONTRACT_V1.json"),
                "--base-freeze", str(BASE / "IMPLEMENTATION_FREEZE_V1.json"),
                "--validator", str(SRC / "validate_v1_2_1_strict_inputs_v1.py"),
                "--watcher", str(SRC / "watch_v1_2_1_terminal_then_validate_v1.py"),
                "--evaluator", str(SRC / "evaluate_authorized_v2_5_strict_meta_v1.py"),
                "--dry-run", str(SRC / "dry_run_execution_adapter_v1.py"),
                "--common", str(SRC / "execution_common_v1.py"),
                "--meta-module", str(BASE / "src/meta_noise_stack_v1.py"),
                "--c2-module", str(BASE / "src/c2_fold_local_v1.py"),
                "--node1-package-root", "/node1/upstream-package",
                "--node1-runtime-root", "/node1/upstream-runtime",
                "--node1-input-root", "/node1/adapter/inputs",
                "--node1-closure-output", "/node1/adapter/closure",
                "--node1-adapter-root", "/node1/adapter",
                "--output", str(output),
            ], check=False)
            self.assertEqual(result.returncode, 0)
            manifest = json.loads(output.read_text())
            self.assertFalse(manifest["execution_authorized"])
            self.assertFalse(manifest["formal_evaluator_launch_allowed"])
            self.assertEqual([row["model_id"] for row in manifest["formal_model_matrix"]], list(MODEL_IDS))
            self.assertIn("<RUNTIME_ONLY_NOT_STORED>", manifest["postauthorization_command_template"])

    def test_all_predeclared_models_derive_exact_min(self):
        from dry_run_v1 import synthetic_rows
        inner, outer = synthetic_rows()
        predictions, _ = fit_predict_outer_models(inner, outer)
        self.assertEqual(set(predictions), set(MODEL_IDS))
        for values in predictions.values():
            dual = values.min(axis=1)
            self.assertTrue((dual == values[:, 0]).all() | (dual == values[:, 1]).all() or len(dual) > 0)
            self.assertTrue(((dual == values[:, 0]) | (dual == values[:, 1])).all())


if __name__ == "__main__":
    unittest.main()
