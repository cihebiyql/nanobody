import hashlib
import json
import pathlib
import subprocess
import unittest


DEPLOY = pathlib.Path(__file__).parents[1]
BASE = DEPLOY.parents[1]
RESIDUE = BASE / "residue_v1"
MATRIX = RESIDUE / "RESIDUE_PRODUCTION_MATRIX_V1_2.json"
SCRIPTS = {
    "deploy": DEPLOY / "deploy_node1_residue_v1_5_exact.sh",
    "common": DEPLOY / "residue_v1_5_common.sh",
    "smoke": DEPLOY / "run_node1_residue_v1_5_smoke.sh",
    "supervisor": DEPLOY / "supervise_node1_residue_v1_5_production.sh",
}
CHECKPOINT_AUDITOR = DEPLOY / "validate_residue_v1_5_smoke_checkpoint.py"
SHA = {
    "freeze": "3a4046462bcf138c25c5c36005d1f6e24f2df3f931fe32369dba80ee834e155e",
    "trainer": "6c4ee5e9827854406615df6e61b63e5d445d27535eb00a44fca5570c062779af",
    "collector": "a15db4aceaeb8c62bca277d9d39015aff3e7e95bacf30a3dd635c1d18558cee0",
    "governance": "dddc693483c1f9a4145b6e28b74bdc9290ec5e7544e9da302e88cc4c10aa1226",
    "training": "ee120e460ce5f89cf0adc68e7f112395f0460834755d858ba1e7c509de116633",
    "training_receipt": "46fae18a63e10920c05ccf1dc873de2b588ec436a0320d909405164f9d14c529",
    "contact": "bd3cb205af606391aa2153f3c2bbc243c9630796228e12b4a561a2a7da7c7f0f",
    "contact_receipt": "de3973e76e48f0be0c8854fe3f8560c42522ec3e42f90ea4861ce8f9b0ed9027",
    "contact_validation": "8dae292b1dd922ff2af7f9f73bdaa662e4fe3f827f30f633df9d3a3ebd603911",
    "model": "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0",
}
LANES = [
    "F1_contact_low_frozen",
    "F4_contact_high_frozen",
    "F3_contact_low_rank_frozen",
    "L1_contact_low_lora",
]
GPU_ASSIGNMENT = {"1": [0, 4], "2": [1], "3": [2], "4": [3]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_json(path, argument):
    result = subprocess.run(
        ["bash", str(path), argument], text=True, capture_output=True, check=True
    )
    return json.loads(result.stdout)


class TestFrozenMatrix(unittest.TestCase):
    def test_exact_v15_hashes_bootstrap_gpu_lanes_and_seal(self):
        matrix = json.loads(MATRIX.read_text())
        frozen = matrix["frozen_inputs"]
        self.assertEqual(matrix["schema_version"], "pvrig_v6_residue_production_matrix_v1_2")
        self.assertEqual(matrix["status"], "FROZEN_BEFORE_FIRST_V1_5_SMOKE_OR_PRODUCTION_RUN")
        self.assertEqual(matrix["bootstrap"], {"repetitions": 1000, "seed": 20260718})
        self.assertEqual([row["lane"] for row in matrix["lanes_in_fixed_execution_order"]], LANES)
        self.assertEqual(matrix["execution"]["gpu_zero"], "FORBIDDEN")
        observed = {
            key.removeprefix("physical_gpu_"): value
            for key, value in matrix["execution"]["gpu_assignment"].items()
        }
        self.assertEqual(observed, GPU_ASSIGNMENT)
        self.assertIn("SEALED", matrix["sealed_evidence"]["V4_F"])
        self.assertEqual(frozen["implementation_freeze_v1_5_sha256"], SHA["freeze"])
        self.assertEqual(frozen["trainer_v1_5_sha256"], SHA["trainer"])
        self.assertEqual(frozen["collector_v1_5_sha256"], SHA["collector"])
        self.assertEqual(frozen["governance_amendment_sha256"], SHA["governance"])
        self.assertEqual(frozen["training_tsv_sha256"], SHA["training"])
        self.assertEqual(frozen["training_receipt_sha256"], SHA["training_receipt"])
        self.assertEqual(frozen["contact_targets_sha256"], SHA["contact"])
        self.assertEqual(frozen["contact_receipt_sha256"], SHA["contact_receipt"])
        self.assertEqual(frozen["contact_independent_validation_sha256"], SHA["contact_validation"])
        self.assertEqual(frozen["esm2_650m_model_safetensors_sha256"], SHA["model"])
        self.assertTrue(matrix["deployment_contract"]["input_paths"]["contact_receipt"].endswith("/RUN_RECEIPT.json"))

    def test_v15_frozen_files_are_unchanged(self):
        self.assertEqual(sha(RESIDUE / "IMPLEMENTATION_FREEZE_V1_5.json"), SHA["freeze"])
        self.assertEqual(sha(RESIDUE / "src/train_nested_residue_surrogate_v1_5.py"), SHA["trainer"])
        self.assertEqual(sha(RESIDUE / "src/collect_residue_oof_v1_5.py"), SHA["collector"])


class TestDeploymentScripts(unittest.TestCase):
    def test_scripts_have_valid_shell_syntax(self):
        for name, path in SCRIPTS.items():
            with self.subTest(name=name):
                subprocess.run(["bash", "-n", str(path)], check=True)

    def test_common_forbids_gpu_zero(self):
        rejected = subprocess.run(
            ["bash", str(SCRIPTS["common"]), "--assert-gpu", "0"],
            text=True,
            capture_output=True,
        )
        self.assertNotEqual(rejected.returncode, 0)
        accepted = subprocess.run(
            ["bash", str(SCRIPTS["common"]), "--assert-gpu", "1"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_machine_readable_plans_are_exact(self):
        deploy = run_json(SCRIPTS["deploy"], "--print-plan")
        smoke = run_json(SCRIPTS["smoke"], "--print-plan")
        production = run_json(SCRIPTS["supervisor"], "--print-plan")
        self.assertEqual(deploy["remote_host"], "node1")
        self.assertTrue(deploy["remote_code_root"].endswith("/code_v1_5"))
        self.assertEqual(deploy["hashes"], SHA)
        self.assertFalse(deploy["launches_remote_jobs"])
        self.assertEqual(smoke["lanes"], LANES)
        self.assertEqual(smoke["physical_gpu"], 1)
        self.assertEqual(production["lanes"], LANES)
        self.assertEqual(production["gpu_assignment"], GPU_ASSIGNMENT)
        self.assertEqual(production["bootstrap"], {"repetitions": 1000, "seed": 20260718})
        self.assertEqual(production["collector_after_fold_terminals"], 5)
        self.assertTrue(production["resume"])
        self.assertTrue(production["fail_closed"])

    def test_shell_lane_arguments_match_frozen_matrix(self):
        matrix = json.loads(MATRIX.read_text())
        for expected in matrix["lanes_in_fixed_execution_order"]:
            with self.subTest(lane=expected["lane"]):
                plan = subprocess.run(
                    ["bash", str(SCRIPTS["common"]), "--print-lane", expected["lane"]],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                argv = json.loads(plan.stdout)["argv"]
                pairs = {
                    argv[index].removeprefix("--"): argv[index + 1]
                    for index in range(len(argv) - 1)
                    if argv[index].startswith("--") and not argv[index + 1].startswith("--")
                }
                self.assertEqual(pairs["backbone-mode"], expected["backbone_mode"])
                self.assertEqual(float(pairs["contact-weight"]), expected["contact_weight"])
                self.assertEqual(float(pairs["ranking-weight"]), expected["ranking_weight"])
                self.assertEqual(float(pairs["ranking-minimum-delta"]), expected["ranking_minimum_delta"])
                self.assertEqual(float(pairs["ranking-temperature"]), expected["ranking_temperature"])
                if expected["backbone_mode"] == "lora":
                    self.assertIn("--gradient-checkpointing", argv)
                    self.assertEqual(int(pairs["lora-r"]), expected["lora_r"])
                    self.assertEqual(int(pairs["lora-alpha"]), expected["lora_alpha"])
                    self.assertEqual(float(pairs["lora-dropout"]), expected["lora_dropout"])
                    self.assertEqual(pairs["lora-target-modules"], expected["lora_target_modules"])
                    self.assertEqual(float(pairs["lora-learning-rate"]), expected["lora_learning_rate"])

    def test_authoritative_receipt_bootstrap_and_no_sealed_path_reads(self):
        combined = "\n".join(path.read_text() for path in SCRIPTS.values())
        self.assertIn("inputs_v1_2/residue_contact_targets_v1/RUN_RECEIPT.json", combined)
        self.assertIn("inputs_v1_2/full1507/v6_supervised1507.tsv", combined)
        self.assertIn("--bootstrap-replicates 1000", combined)
        self.assertIn("--bootstrap-seed 20260718", combined)
        lowered = combined.lower()
        for forbidden in ("v4_f", "test32", "holdout96"):
            self.assertNotIn(forbidden, lowered)

    def test_deploy_never_stages_or_overwrites_existing_code_v15(self):
        source = SCRIPTS["deploy"].read_text()
        self.assertIn("SSH_BIN=${SSH_BIN:-ssh.exe}", source)
        self.assertNotIn('\nssh "$REMOTE_HOST"', source)
        self.assertNotIn('$stage/code_v1_5', source)
        self.assertIn("immutable_code_upload_forbidden", source)
        self.assertIn("immutable_code_v1_5_touched", source)
        self.assertIn("PASS_EXISTING_CODE_V1_5_MODEL_AND_REMOTE_TEST_VALIDATION", source)
        self.assertIn("validate_residue_v1_5_smoke_checkpoint.py", source)

    def test_deploy_has_exact_remote_compile_and_41_test_gate(self):
        source = SCRIPTS["deploy"].read_text()
        self.assertIn("'-m','py_compile'", source)
        self.assertIn("PYTHONPYCACHEPREFIX", source)
        self.assertIn("'unittest','discover'", source)
        self.assertIn("int(match.group(1))==41", source)
        self.assertIn("remote_test_count':41", source)
        self.assertIn("remote_test_result':'PASS", source)
        self.assertIn("remote_py_compile_result':'PASS", source)
        self.assertIn("existing_deployment_remote_test_gate_missing", source)

    def test_smoke_fail_closed_checkpoint_and_gpu_audit_is_wired(self):
        source = SCRIPTS["smoke"].read_text()
        self.assertTrue(CHECKPOINT_AUDITOR.is_file())
        for token in (
            "validate_residue_v1_5_smoke_checkpoint.py",
            "--gpu-memory-csv",
            "checkpoint_audit.json",
            "FAIL_RESIDUE_V1_5_SMOKE_CHECKPOINT_AUDIT",
            "FAIL_RESIDUE_V1_5_SMOKE_GPU_MONITOR",
            "checkpoint_count=",
            "checkpoint_total_bytes=",
            "peak_gpu_memory_mib=",
            "nvidia-smi --id=\"$physical_gpu\"",
        ):
            self.assertIn(token, source)
        supervisor = SCRIPTS["supervisor"].read_text()
        self.assertIn("deploy['remote_test_count']==41", supervisor)
        self.assertIn("deploy['remote_test_result']=='PASS'", supervisor)

    def test_supervisor_encodes_terminal_and_disk_guards(self):
        source = SCRIPTS["supervisor"].read_text()
        for token in (
            "PASS_OUTER_FOLD_COMPLETE",
            "SEALED_COMPLETE_ONE_EVALUATION",
            "SAFE_STOP_DISK_BELOW_CHECKPOINT_GUARD",
            "SEALED_STARTED_NOT_REPEATABLE",
            "PASS_RESIDUE_V1_5_PRODUCTION_TERMINAL",
            "FAIL_RESIDUE_V1_5_PRODUCTION",
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
