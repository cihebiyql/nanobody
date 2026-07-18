#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "strict_terminal_eval", HERE / "evaluate_v2_2_2_strict_terminal_v1.py"
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


LANES = ("B_TARGET_NO_CONTACT", "C_SPLIT_MARGINAL", "D_SPLIT_PAIR")


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class StrictTerminalEvaluatorTests(unittest.TestCase):
    def build_runtime(self, root: Path, *, d_is_good: bool = True) -> tuple[Path, Path, Path]:
        runtime = root / "runtime"
        runtime.mkdir()
        jobs: list[dict[str, object]] = []
        candidates = []
        for index in range(1507):
            parent_index = index % 31
            fold = parent_index % 5
            truth8 = 0.2 + index / 4000.0
            truth9 = 0.25 + index / 5000.0
            candidates.append({
                "candidate_id": f"C{index:04d}",
                "teacher_source": "V4D_OPEN_MULTI_SEED" if index < 226 else "V4H_ADAPTIVE_SEED_RANKING",
                "parent_framework_cluster": f"P{parent_index:02d}",
                "outer_fold": fold,
                "R_8X6B": truth8,
                "R_9E6Y": truth9,
                "R_dual_min": min(truth8, truth9),
            })

        for lane in LANES:
            for fold in range(5):
                subset = [row for row in candidates if row["outer_fold"] == fold]
                prefix = f"o{fold}.{lane}"
                base_path = runtime / "evidence" / lane / f"outer_{fold}" / "outer_test_base.tsv"
                base_rows = []
                meta_rows = []
                for row in subset:
                    if lane == "D_SPLIT_PAIR" and not d_is_good:
                        pred8 = pred9 = 0.5
                    else:
                        pred8, pred9 = row["R_8X6B"], row["R_9E6Y"]
                    base_rows.append({
                        "schema_version": MOD.BASE_SCHEMA,
                        "evidence_role": MOD.BASE_ROLE,
                        **row,
                        "inner_fold": "NONE",
                        "M2_R8": row["R_8X6B"],
                        "M2_R9": row["R_9E6Y"],
                    })
                    meta_rows.append({
                        "schema_version": MOD.META_SCHEMA,
                        "evidence_role": MOD.META_ROLE,
                        **row,
                        "prediction_R8": pred8,
                        "prediction_R9": pred9,
                        "prediction_R_dual_min": min(pred8, pred9),
                        "meta_model_receipt_sha256": f"receipt-{lane}-{fold}",
                    })
                write_tsv(base_path, base_rows)
                meta_path = base_path.with_name("outer_test_meta_prediction.tsv")
                write_tsv(meta_path, meta_rows)
                validation_path = meta_path.with_suffix(".validation.json")
                validation_path.write_text(json.dumps({"status": "PASS_META", "sealed_evaluation_access_count": 0}) + "\n")
                jobs.extend([
                    {"job_id": f"{prefix}.outer_base.assemble", "kind": "CPU_ASSEMBLE_OUTER_TEST_BASE_FEATURE", "expected_result": str(base_path)},
                    {"job_id": f"{prefix}.meta.materialize", "kind": "CPU_MATERIALIZE_OUTER_TEST_META_PREDICTION", "expected_result": str(meta_path)},
                    {"job_id": f"{prefix}.meta.validate", "kind": "CPU_VALIDATE_OUTER_TEST_META_PREDICTION", "expected_result": str(validation_path)},
                ])

        expected_counts = {
            "GPU_BASE_TRAIN_INNER": 75,
            "CPU_ASSEMBLE_INNER_OOF_BASE_FEATURE": 15,
            "CPU_VALIDATE_INNER_OOF_BASE_FEATURE": 15,
            "CPU_FIT_FIVE_PARAMETER_META": 15,
            "GPU_BASE_REFIT_OUTER_TRAIN": 15,
            "CPU_VALIDATE_OUTER_TEST_BASE_FEATURE": 15,
        }
        for kind, count in expected_counts.items():
            for index in range(count):
                path = runtime / "dummy" / kind / f"{index}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n")
                jobs.append({"job_id": f"dummy.{kind}.{index}", "kind": kind, "expected_result": str(path)})
        self.assertEqual(len(jobs), 195)
        graph = {
            "schema_version": MOD.GRAPH_SCHEMA,
            "sealed_evaluation_access_count": 0,
            "prediction_metrics_access_count": 0,
            "jobs": jobs,
        }
        graph_path = root / "job_graph.json"
        graph_path.write_text(json.dumps(graph, sort_keys=True) + "\n")
        contract = {
            "schema_version": MOD.CONTRACT_SCHEMA,
            "status": "FROZEN_BEFORE_ANY_STRICT_OUTER_META_PREDICTION_EXISTED",
            "claim_boundary": "synthetic open-development test only",
            "expected_candidate_count": 1507,
            "expected_parent_count": 31,
            "expected_outer_folds": 5,
            "expected_job_count": 195,
            "expected_job_graph_sha256": MOD.sha256_file(graph_path),
            "expected_job_kind_counts": dict(sorted(MOD.Counter(job["kind"] for job in jobs).items())),
            "expected_sources": {"V4D_OPEN_MULTI_SEED": 226, "V4H_ADAPTIVE_SEED_RANKING": 1281},
            "frozen_lanes": list(LANES),
            "formal_primary_lane": "D_SPLIT_PAIR",
            "non_primary_lane_policy": "B/C diagnostic only",
            "promotion_gate": {
                "frozen_M2_Rdual_spearman": 1.0,
                "M2_Rdual_mae_ceiling": 0.0,
                "M2_Rdual_rmse_ceiling": 0.0,
                "required_Rdual_spearman": 1.0,
            },
        }
        contract_path = root / "contract.json"
        contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n")
        (runtime / "TERMINAL.json").write_text(json.dumps({"returncode": 0, "status": "PASS"}) + "\n")
        (runtime / "AUTHORIZED_LAUNCH_RECEIPT.json").write_text(json.dumps({
            "status": "AUTHORIZED_LAUNCH_STARTED",
            "job_graph_sha256": MOD.sha256_file(graph_path),
            "job_count": 195,
            "sealed_evaluation_access_count": 0,
        }) + "\n")
        return runtime, graph_path, contract_path

    def test_full_closure_promotes_only_primary_when_primary_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, graph, contract = self.build_runtime(root, d_is_good=True)
            output = root / "result"
            receipt = MOD.evaluate(argparse.Namespace(
                runtime_root=runtime, job_graph=graph, contract=contract, output_dir=output,
            ))
            self.assertEqual(receipt["status"], "PASS_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK")
            self.assertEqual(receipt["strict_oof_candidate_count_per_lane"], 1507)
            self.assertEqual(receipt["strict_meta_validation_reports_passed"], 15)
            self.assertEqual(receipt["v4_f_or_test32_access_count"], 0)
            self.assertTrue((output / "SHA256SUMS").is_file())

    def test_non_primary_success_cannot_rescue_failed_primary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime, graph, contract = self.build_runtime(root, d_is_good=False)
            output = root / "result"
            receipt = MOD.evaluate(argparse.Namespace(
                runtime_root=runtime, job_graph=graph, contract=contract, output_dir=output,
            ))
            self.assertEqual(receipt["status"], "DO_NOT_PROMOTE_V2_4_D_SPLIT_PAIR_STRICT_STACK")
            decision = json.loads((output / "PROMOTION_DECISION.json").read_text())
            self.assertTrue(decision["lane_gate_diagnostics"]["C_SPLIT_MARGINAL"]["all_pass"])
            self.assertFalse(decision["formal_primary_lane_all_gates_pass"])

    def test_sealed_token_is_rejected(self) -> None:
        with self.assertRaisesRegex(MOD.EvaluationError, "sealed_artifact_forbidden"):
            MOD.reject_sealed(Path("some_test32_file.tsv"), "unit")

    def test_exact_min_violation_is_rejected(self) -> None:
        raw = [{
            "schema_version": MOD.META_SCHEMA,
            "evidence_role": MOD.META_ROLE,
            "candidate_id": "C1",
            "teacher_source": "V4D_OPEN_MULTI_SEED",
            "parent_framework_cluster": "P1",
            "outer_fold": "0",
            "R_8X6B": "0.4",
            "R_9E6Y": "0.5",
            "R_dual_min": "0.4",
            "prediction_R8": "0.3",
            "prediction_R9": "0.6",
            "prediction_R_dual_min": "0.4",
            "meta_model_receipt_sha256": "x",
        }]
        with self.assertRaisesRegex(MOD.EvaluationError, "prediction_exact_min"):
            MOD.normalize_meta(raw, "D_SPLIT_PAIR", 0)


if __name__ == "__main__":
    unittest.main()
