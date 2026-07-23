#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import torch
from torch import nn


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src" / "materialize_v220_production_initial_state_v1.py"
SPEC = importlib.util.spec_from_file_location("materialize_v220_initial_test", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class StubModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.backbone = nn.Linear(2, 2)
        self.head = nn.Linear(2, 1)


class InitialMaterializerTests(unittest.TestCase):
    def test_materialize_binds_external_bytes_and_no_training(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runner_path, helper_path = root / "runner.py", root / "helper.py"
            runner_path.write_text("runner")
            helper_path.write_text("helper")
            model = StubModel()
            for parameter in model.backbone.parameters():
                parameter.requires_grad_(False)
            identity = hashlib.sha256(b"backbone").hexdigest()
            bindings = {
                "scalar_contract_sha256": "contract",
                "training_table_sha256": "teacher",
                "target_graph_sha256": "target",
                "target_graph_receipt_sha256": "target-receipt",
                "teacher_package_receipt_sha256": "contact-receipt",
                "graph_bundle_sha256": {"graph": "hash"},
            }
            inputs = types.SimpleNamespace(
                model=model, model_identity=identity, input_bindings=bindings
            )
            config = types.SimpleNamespace(fold_id=0, arm="C0")
            runner = types.SimpleNamespace(prepare_production_inputs=lambda args: (config, inputs))
            preregistration = root / "prereg.json"
            preregistration.write_text(
                json.dumps(
                    {
                        "status": "FROZEN_PRETRAINING_PHASE1_CORE_PROTOCOL",
                        "data": {
                            "scalar_teacher": {"sha256": "teacher"},
                            "fixed_target_graphs": {
                                "artifact_sha256": "target",
                                "receipt_sha256": "target-receipt",
                            },
                            "contact_teacher": {
                                "materialization_receipt_sha256": "contact-receipt"
                            },
                            "label_free_graph_cache": {
                                "input_hashes": {"graph": "hash"}
                            },
                        },
                        "strict_oof": {
                            "fold_bindings": [
                                {"fold": 0, "contract_sha256": "contract"}
                            ]
                        },
                    }
                )
            )

            class Paired:
                @staticmethod
                def save_paired_initial_state(path, model, fold_id, seed, backbone_identity_sha256):
                    path.write_bytes(b"head-state")
                    receipt = {"status": "PAIRED_INITIAL_STATE_SAVED_NO_TRAINING", "checkpoint": str(path)}
                    Path(f"{path}.receipt.json").write_text(json.dumps(receipt))
                    return receipt

                @staticmethod
                def load_and_verify_initial_state(path, model, backbone_identity_sha256, receipt_path, expected_checkpoint_sha256, expected_receipt_sha256):
                    self.assertEqual(expected_checkpoint_sha256, hashlib.sha256(path.read_bytes()).hexdigest())
                    self.assertEqual(expected_receipt_sha256, hashlib.sha256(receipt_path.read_bytes()).hexdigest())
                    return {"status": "PASS_INITIAL_STATE_LOADED_AND_VERIFIED", "backbone_binding": {"artifact_identity_sha256": backbone_identity_sha256}, "hashes": {"head_state_sha256": "h"}}

            args = argparse.Namespace(
                fold_id=0,
                arm="C0",
                initial_state=root / "initial.bin",
                terminal=root / "terminal.json",
                runner=runner_path,
                paired_helper=helper_path,
                preregistration=preregistration,
            )
            result = MODULE.materialize(args, runner_module=runner, paired_module=Paired)
            self.assertEqual(result["status"], "PASS_V220_PHASE1_INITIAL_HEAD_STATE_MATERIALIZED_NO_TRAINING")
            self.assertFalse(result["training_started"])
            self.assertTrue(args.terminal.is_file())

    def test_refuses_noncanonical_builder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(fold_id=1, arm="C0", initial_state=root / "x", terminal=root / "t")
            with self.assertRaisesRegex(MODULE.InitialStateMaterializationError, "canonical_builder"):
                MODULE.materialize(args, runner_module=object(), paired_module=object())


if __name__ == "__main__":
    unittest.main()
