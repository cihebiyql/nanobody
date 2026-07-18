import hashlib
import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


ROOT = pathlib.Path(__file__).parents[1]
MODULE = ROOT / "src" / "collect_residue_oof_v1_3.py"
GOVERNANCE = ROOT.parent / "PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json"
spec = importlib.util.spec_from_file_location("residue_oof_v1_3", MODULE)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)


class TestGovernanceBinding(unittest.TestCase):
    def test_real_governance_passes_and_tampered_copy_fails(self):
        payload = mod.validate_governance_amendment(GOVERNANCE)
        self.assertEqual(payload["frozen_implementation"]["promotion_gate"], mod.EXACT_PROMOTION_GATE)
        with tempfile.TemporaryDirectory() as temporary:
            tampered = pathlib.Path(temporary) / GOVERNANCE.name
            changed = json.loads(GOVERNANCE.read_text())
            changed["frozen_implementation"]["promotion_gate"] = "weakened"
            tampered.write_text(json.dumps(changed, sort_keys=True))
            with self.assertRaisesRegex(Exception, "governance_sha256_mismatch"):
                mod.validate_governance_amendment(tampered)

    def test_governance_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            link = pathlib.Path(temporary) / GOVERNANCE.name
            link.symlink_to(GOVERNANCE)
            with self.assertRaisesRegex(Exception, "governance_symlink_forbidden"):
                mod.validate_governance_amendment(link)

    def make_freeze_fixture(self, root, governance_path="../PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json", governance_sha=None):
        residue = root / "residue_v1"
        residue.mkdir()
        governance = root / GOVERNANCE.name
        shutil.copyfile(GOVERNANCE, governance)
        implementation = residue / "implementation.py"
        implementation.write_text("frozen\n")
        implementation_sha = hashlib.sha256(implementation.read_bytes()).hexdigest()
        freeze = residue / "IMPLEMENTATION_FREEZE_V1_3.json"
        freeze.write_text(json.dumps({
            "schema_version": "pvrig_v6_residue_v1_3_implementation_freeze",
            "status": "IMPLEMENTED_CPU_VALIDATED_NOT_REMOTE_TRAINED",
            "governance": {
                "path": governance_path,
                "sha256": governance_sha or mod.GOVERNANCE_SHA256,
                "promotion_gate": mod.EXACT_PROMOTION_GATE,
            },
            "implementation_sha256": {"implementation.py": implementation_sha},
        }))
        return residue, governance, freeze

    def test_freeze_governance_path_and_sha_are_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            residue, governance, freeze = self.make_freeze_fixture(root)
            self.assertTrue(mod.validate_implementation_freeze(freeze, residue, governance))
        for changed_path, changed_sha, expected in (
            ("../other.json", None, "freeze_governance_path_mismatch"),
            ("../PREREGISTRATION_V1_1_IMPLEMENTATION_AMENDMENT.json", "0" * 64, "freeze_governance_sha256_mismatch"),
        ):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                root = pathlib.Path(temporary)
                residue, governance, freeze = self.make_freeze_fixture(root, changed_path, changed_sha)
                with self.assertRaisesRegex(Exception, expected):
                    mod.validate_implementation_freeze(freeze, residue, governance)


class TestOuterBindingClosure(unittest.TestCase):
    def valid_documents(self):
        binding = "b" * 64
        freeze = "f" * 64
        contract = {
            "binding_hash": binding,
            "binding": {"external_hashes": {"implementation_freeze_sha256": freeze}},
        }
        result = {"status": "PASS_OUTER_FOLD_COMPLETE", "outer_evaluation_count": 1, "binding_hash": binding}
        seal = {"status": "SEALED_COMPLETE_ONE_EVALUATION", "binding_hash": binding}
        return result, seal, contract, freeze

    def test_valid_outer_documents_close(self):
        result, seal, contract, freeze = self.valid_documents()
        mod.validate_outer_binding_documents(result, seal, contract, freeze)

    def test_tampered_freeze_result_or_seal_binding_is_rejected(self):
        mutations = ("freeze", "result", "seal", "contract")
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                result, seal, contract, freeze = self.valid_documents()
                if mutation == "freeze":
                    contract["binding"]["external_hashes"]["implementation_freeze_sha256"] = "x" * 64
                elif mutation == "result":
                    result["binding_hash"] = "x" * 64
                elif mutation == "seal":
                    seal["binding_hash"] = "x" * 64
                else:
                    contract["binding_hash"] = "x" * 64
                with self.assertRaisesRegex(Exception, "outer_binding_closure_failed|outer_freeze_binding_mismatch"):
                    mod.validate_outer_binding_documents(result, seal, contract, freeze)


if __name__ == "__main__":
    unittest.main()

