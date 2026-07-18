import argparse
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("nested_plan", HERE.with_name("build_strict_nested_crossfit_plan_v1.py"))
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)
VALIDATOR_PATH = ROOT / "feature_contract" / "src" / "validate_receptor_compact_evidence_v2.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("evidence_validator", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(VALIDATOR_SPEC)
assert VALIDATOR_SPEC and VALIDATOR_SPEC.loader
VALIDATOR_SPEC.loader.exec_module(validator)

SPLIT_ROOT = ROOT / "split_contract" / "prepared" / "whole_parent_nested_splits_all_outer_seed1931_v3_parent_balanced_v2_4"
TRAINING = ROOT / "data_contract" / "materialized_v1" / "v6_supervised1507_v2_4.tsv"
OUTER = SPLIT_ROOT / "outer_development_manifest.tsv"
INNER = SPLIT_ROOT / "inner_nested_oof_manifest.tsv"
DEPLOYMENT = ROOT / "deployment" / "V2_4_NODE1_PREFREEZE_MANIFEST_V1.json"
FORMULA = ROOT / "contact_contract" / "contact_score_formula_v1.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_tsv(path):
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class StrictNestedPlanTests(unittest.TestCase):
    def args(self, root):
        out = root / "plan"
        return argparse.Namespace(
            training_tsv=TRAINING, outer_manifest=OUTER, inner_manifest=INNER,
            deployment_manifest=DEPLOYMENT, contact_formula=FORMULA,
            output_dir=out, runtime_root=str(root / "runtime"), node1_plan_root=str(out),
            planner_node1_path=str(HERE.with_name("build_strict_nested_crossfit_plan_v1.py")),
            feature_validator_node1_path=str(ROOT / "feature_contract" / "src" / "validate_receptor_compact_evidence_v2.py"),
            stack_fitter_node1_path=str(ROOT / "src" / "fit_shared_nonnegative_stack_v2.py"),
            inner_manifest_node1_path=str(INNER), outer_manifest_node1_path=str(OUTER),
            contact_formula_node1_path=str(FORMULA),
        )

    def test_plan_has_strict_double_crossfit_dag_and_no_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(Path(tmp))
            receipt = mod.plan(args)
            graph = json.loads((args.output_dir / "job_graph.json").read_text())
            self.assertEqual(receipt["status"], "DRY_RUN_PENDING_POSTCALIBRATION_FREEZE_DO_NOT_EXECUTE")
            self.assertFalse(graph["execution_authorized"])
            self.assertEqual(graph["resources"]["inner_gpu_jobs"], 75)
            self.assertEqual(graph["resources"]["outer_refit_gpu_jobs"], 15)
            self.assertEqual(graph["resources"]["gpu_training_jobs"], 90)
            self.assertEqual(graph["resources"]["cpu_postprocess_jobs"], 105)
            self.assertEqual(len(graph["jobs"]), 195)
            self.assertEqual(len(graph["split_manifests"]), 30)
            self.assertEqual(graph["stack_lanes"], list(mod.LANES))
            self.assertIn(mod.EXCLUDED_LANE, graph["diagnostic_exclusions"])
            gpu = [j for j in graph["jobs"] if j["kind"].startswith("GPU_")]
            self.assertTrue(all(j["command"] is None for j in gpu))
            for fold in mod.OUTER_FOLDS:
                for lane in mod.LANES:
                    prefix = f"o{fold}.{lane}"
                    fit = next(j for j in graph["jobs"] if j["job_id"] == f"{prefix}.meta.fit")
                    self.assertEqual(set(fit["dependencies"]), {f"{prefix}.inner_oof.validate", f"{prefix}.outer_base.validate"})
                    meta = next(j for j in graph["jobs"] if j["job_id"] == f"{prefix}.meta.materialize")
                    self.assertEqual(meta["dependencies"], [f"{prefix}.meta.fit"])
            self.assertNotRegex(json.dumps(graph).lower(), r"v4[_-]?f|test32")

    def test_planner_rejects_sealed_tokens(self):
        with self.assertRaisesRegex(mod.NestedPlanError, "sealed_v4f_forbidden"):
            mod.reject_sealed("/data1/project/pvrig_v4_f/test32.tsv", "test")

    def write_fake_base_output(self, job, lane, training_by_candidate):
        out = Path(job["output_dir"])
        out.mkdir(parents=True)
        split = json.loads(Path(job["split_manifest"]).read_text())
        score = set(split["score_parents"])
        candidates = [r for r in training_by_candidate.values() if r["parent_framework_cluster"] in score]
        m2 = out / "m2_ridge.json"; m2.write_text("{}\n")
        neural = out / "neural_head.pt"; neural.write_bytes(b"head")
        component = out / "component_receipts.json"; component.write_text("{}\n")
        pred = out / "base_score_predictions.tsv"
        columns = [
            "candidate_id", "teacher_source", "parent_framework_cluster", "split_id", "lane",
            "truth_R8", "truth_R9", "truth_Rdual", "M2_R8", "M2_R9", "M2_Rdual",
            "neural_R8", "neural_R9", "neural_Rdual", "contact_score_R8", "contact_score_R9",
            "contact_score_role", "contact_score_formula_sha256", "base_training_parent_set_sha256",
            "base_training_parent_count", "base_model_receipt_sha256",
        ]
        with pred.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            for index, row in enumerate(candidates):
                r8, r9 = float(row["R_8X6B"]), float(row["R_9E6Y"])
                m8, m9 = r8 * .9 + .01, r9 * .9 + .01
                n8, n9 = r8 * .8 + .02, r9 * .8 + .02
                c8, c9 = .1 + (index % 17) / 20, .1 + (index % 13) / 18
                writer.writerow({
                    "candidate_id": row["candidate_id"], "teacher_source": row["teacher_source"],
                    "parent_framework_cluster": row["parent_framework_cluster"], "split_id": split["split_id"], "lane": lane,
                    "truth_R8": r8, "truth_R9": r9, "truth_Rdual": min(r8, r9),
                    "M2_R8": m8, "M2_R9": m9, "M2_Rdual": min(m8, m9),
                    "neural_R8": n8, "neural_R9": n9, "neural_Rdual": min(n8, n9),
                    "contact_score_R8": c8, "contact_score_R9": c9,
                    "contact_score_role": "stack_eligible_pvrig_contact_composite",
                    "contact_score_formula_sha256": mod.CONTACT_FORMULA_SHA,
                    "base_training_parent_set_sha256": split["train_parent_set_sha256"],
                    "base_training_parent_count": len(split["train_parents"]),
                    "base_model_receipt_sha256": sha(component),
                })
        artifacts = {
            "predictions": {"path": pred.name, "rows": len(candidates), "sha256": sha(pred)},
            "m2_ridge": {"path": m2.name, "sha256": sha(m2)},
            "neural_head": {"path": neural.name, "sha256": sha(neural)},
            "component_receipts": {"path": component.name, "sha256": sha(component)},
        }
        result = {
            "status": "PASS_OPEN_BASE_SPLIT_COMPLETE", "lane": lane, "split": split,
            "open_only": True, "v4_f_test32_access_count": 0,
            "contact_score_stack_eligible": True,
            "contact_score_formula_receipt_sha256": mod.CONTACT_FORMULA_SHA,
            "artifacts": artifacts,
        }
        (out / "RESULT.json").write_text(json.dumps(result) + "\n")

    def test_completed_fake_outputs_materialize_disjoint_inner_outer_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); args = self.args(root); mod.plan(args)
            graph_path = args.output_dir / "job_graph.json"
            graph = json.loads(graph_path.read_text())
            training = {r["candidate_id"]: r for r in read_tsv(TRAINING)}
            fold, lane = 0, "B_TARGET_NO_CONTACT"
            selected = [j for j in graph["jobs"] if j.get("outer_fold") == fold and j.get("lane") == lane and j["kind"] in {"GPU_BASE_TRAIN_INNER", "GPU_BASE_REFIT_OUTER_TRAIN"}]
            for item in selected:
                self.write_fake_base_output(item, lane, training)
            evidence_dir = root / "evidence"; evidence_dir.mkdir()
            inner_tsv, inner_prov = evidence_dir / "inner.tsv", evidence_dir / "inner.json"
            outer_tsv, outer_prov = evidence_dir / "outer.tsv", evidence_dir / "outer.json"
            mod.assemble_base(argparse.Namespace(job_graph=graph_path, outer_fold=fold, lane=lane, role="inner", output_tsv=inner_tsv, provenance_json=inner_prov))
            mod.assemble_base(argparse.Namespace(job_graph=graph_path, outer_fold=fold, lane=lane, role="outer", output_tsv=outer_tsv, provenance_json=outer_prov))
            inner_validation = validator.run(argparse.Namespace(evidence_tsv=inner_tsv, split_manifest_tsv=INNER,
                provenance_json=inner_prov, contact_formula_json=FORMULA, report_json=evidence_dir / "inner.validation.json"))
            outer_validation = validator.run(argparse.Namespace(evidence_tsv=outer_tsv, split_manifest_tsv=OUTER,
                provenance_json=outer_prov, contact_formula_json=FORMULA, report_json=evidence_dir / "outer.validation.json"))
            self.assertEqual(inner_validation["status"], "PASS_ROLE_SEPARATED_COMPONENT_CONTRACT")
            self.assertEqual(outer_validation["status"], "PASS_ROLE_SEPARATED_COMPONENT_CONTRACT")
            inner_rows, outer_rows = read_tsv(inner_tsv), read_tsv(outer_tsv)
            self.assertEqual(len(inner_rows), 1269)
            self.assertEqual(len(outer_rows), 238)
            self.assertTrue({r["parent_framework_cluster"] for r in inner_rows}.isdisjoint({r["parent_framework_cluster"] for r in outer_rows}))
            self.assertEqual(len({r["candidate_id"] for r in inner_rows}), len(inner_rows))

            stack = root / "stack"; stack.mkdir()
            model = stack / "model.json"; model.write_text("{}\n")
            predictions = stack / "outer_test_meta_predictions.tsv"
            cols = ["candidate_id", "teacher_source", "parent_framework_cluster", "outer_fold", "prediction_R8", "prediction_R9", "prediction_R_dual_min"]
            with predictions.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=cols, delimiter="\t", lineterminator="\n"); writer.writeheader()
                for row in outer_rows:
                    p8, p9 = float(row["M2_R8"]), float(row["M2_R9"])
                    writer.writerow({"candidate_id": row["candidate_id"], "teacher_source": row["teacher_source"],
                        "parent_framework_cluster": row["parent_framework_cluster"], "outer_fold": fold,
                        "prediction_R8": p8, "prediction_R9": p9, "prediction_R_dual_min": min(p8, p9)})
            receipt = {"model_json_sha256": sha(model), "prediction_tsv_sha256": sha(predictions)}
            (stack / "receipt.json").write_text(json.dumps(receipt) + "\n")
            meta_tsv, meta_prov = evidence_dir / "meta.tsv", evidence_dir / "meta.json"
            result = mod.materialize_meta(argparse.Namespace(job_graph=graph_path, outer_fold=fold, lane=lane,
                inner_evidence_tsv=inner_tsv, outer_base_tsv=outer_tsv, stack_output_dir=stack,
                output_tsv=meta_tsv, provenance_json=meta_prov))
            self.assertFalse(result["outer_labels_used_for_fit"])
            meta_validation = validator.run(argparse.Namespace(evidence_tsv=meta_tsv, split_manifest_tsv=OUTER,
                provenance_json=meta_prov, contact_formula_json=FORMULA, report_json=evidence_dir / "meta.validation.json"))
            self.assertEqual(meta_validation["status"], "PASS_ROLE_SEPARATED_COMPONENT_CONTRACT")
            meta_rows = read_tsv(meta_tsv)
            self.assertEqual(len(meta_rows), 238)
            self.assertTrue(all(float(r["prediction_R_dual_min"]) == min(float(r["prediction_R8"]), float(r["prediction_R9"])) for r in meta_rows))


if __name__ == "__main__":
    unittest.main()
