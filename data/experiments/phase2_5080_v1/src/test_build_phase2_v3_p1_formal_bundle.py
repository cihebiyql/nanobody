import argparse
import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_phase2_v3_p1_formal_bundle.py")
SPEC = importlib.util.spec_from_file_location("formal_bundle", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MOD)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class FormalBundleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.prereg = self.root / "prereg.json"
        self.spec = self.root / "spec.json"
        for path in (self.prereg, self.spec):
            path.write_text("{}\n")
        self.bound = []
        for name in ("config.json", "teacher_open.csv", "teacher_sealed.csv", "data_audit.json", "inputs.json", "trainer.py", "model.py", "evaluator.py", "bundle.py"):
            path = self.root / name
            path.write_text(name + "\n")
            self.bound.append(path)
        self.full = self.make_training("full")
        self.shuffled = self.make_training("label_shuffle")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def make_training(self, control_type: str) -> Path:
        rows = []
        controls = MOD.FULL_CONTROLS if control_type == "full" else MOD.LABEL_CONTROL
        baseline_content = None
        for seed in MOD.EXPECTED_SEEDS:
            seed_dir = self.root / control_type / f"seed_{seed}"
            seed_dir.mkdir(parents=True)
            checkpoint = seed_dir / "checkpoint.pt"; checkpoint.write_text(f"checkpoint-{control_type}-{seed}\n")
            prediction = seed_dir / "test.csv"; prediction.write_text(f"prediction-{control_type}-{seed}\n")
            dev = seed_dir / "dev.csv"; dev.write_text(f"dev-{control_type}-{seed}\n")
            baseline = seed_dir / "baseline.csv"; baseline.write_text("candidate_id,baseline_generic\nc1,0.5\n")
            if baseline_content is None: baseline_content = baseline.read_bytes()
            self.assertEqual(baseline.read_bytes(), baseline_content)
            control = seed_dir / "controls.csv"
            write_csv(control, [{"candidate_id": "c1", "control_type": name, "seed": seed} for name in sorted(controls)])
            replay = seed_dir / "replay.json"
            replay_record = {"contact_auprc_retention_fraction": 0.95, "paratope_auprc_retention_fraction": 0.96}
            replay.write_text(json.dumps({"per_seed": {str(seed): replay_record}}))
            rows.append({
                "seed": seed, "status": "PASS_FORMAL_TRAINING_COMPLETE", "control_type": control_type,
                "formal_governance_preflight": {"status": "PASS_FORMAL_GOVERNANCE_PREFLIGHT"},
                "best_checkpoint": str(checkpoint), "best_checkpoint_sha256": MOD.sha256_file(checkpoint),
                "test_predictions_path": str(prediction), "test_predictions_sha256": MOD.sha256_file(prediction),
                "dev_predictions_path": str(dev), "dev_predictions_sha256": MOD.sha256_file(dev),
                "control_predictions_path": str(control), "control_predictions_sha256": MOD.sha256_file(control),
                "baseline_registry_path": str(baseline), "baseline_registry_sha256": MOD.sha256_file(baseline),
                "generic_replay_retention_path": str(replay), "generic_replay_retention_sha256": MOD.sha256_file(replay),
                "generic_replay_retention": replay_record, "config_fingerprint": f"fingerprint-{control_type}",
                "preregistration_sha256": MOD.sha256_file(self.prereg), "test_spec_sha256": MOD.sha256_file(self.spec),
            })
        path = self.root / control_type / "training_summary.json"
        path.write_text(json.dumps({"status": "PASS_FORMAL_MULTISEED_COMPLETE", "control_type": control_type, "seed_summaries": rows}))
        return path

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            full_training_summary=self.full, label_shuffle_training_summary=self.shuffled,
            preregistration=self.prereg, test_spec=self.spec, config=self.bound[0],
            teacher_open=self.bound[1], teacher_test_sealed=self.bound[2], formal_data_audit=self.bound[3],
            model_input_validation=self.bound[4], trainer_source=self.bound[5], model_source=self.bound[6],
            evaluator_source=self.bound[7], bundle_builder_source=self.bound[8], output_dir=self.root / "bundle",
        )

    def test_builds_hash_bound_bundle(self) -> None:
        manifest = MOD.build(self.args())
        self.assertEqual(manifest["status"], "PASS_V3_P1_FORMAL_ARTIFACT_BUNDLE_READY")
        self.assertEqual(set(manifest["seed_predictions"]), {"83", "89", "97"})
        controls = MOD.read_csv(self.root / "bundle/control_predictions.csv")
        self.assertEqual(len(controls), 15)
        self.assertEqual({row["control_type"] for row in controls}, MOD.FULL_CONTROLS | MOD.LABEL_CONTROL)

    def test_rejects_checkpoint_drift(self) -> None:
        summary = MOD.load_json(self.full)
        Path(summary["seed_summaries"][0]["best_checkpoint"]).write_text("changed\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            MOD.build(self.args())


if __name__ == "__main__":
    unittest.main()
