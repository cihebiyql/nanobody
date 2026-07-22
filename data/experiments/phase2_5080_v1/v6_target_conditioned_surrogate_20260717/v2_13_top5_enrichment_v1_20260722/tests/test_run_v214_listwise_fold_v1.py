from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PKG=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);assert spec and spec.loader
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module


FIXTURES=load("v214_fixture_source",PKG/"tests/test_run_top5_clean_attention_fold_v1.py")
MOD=load("v214_runner_test",PKG/"src/run_v214_listwise_fold_v1.py")


class V214RunnerTests(unittest.TestCase):
    def test_tiny_e2e_listwise_is_exact_min_and_firewalled(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=FIXTURES.Fixture(Path(temporary))
            args=argparse.Namespace(
                contract=fixture.contract,listwise_contract=PKG/"V2_14_LISTWISE_TOP5_CONTRACT_V1.json",variant="N3",
                graph_cache_dir=fixture.graph_cache,output_dir=Path(temporary)/"v214_output",device="cpu",seed=43,
                epochs=1,batch_size=32,eval_batch_size=2,gradient_accumulation=1,precision="fp32",learning_rate=1e-4,
                weight_decay=.02,gradient_clip=1.,graph_hidden_dim=16,dropout=.1,receptor_weight=1.,dual_weight=.5,
                huber_beta=.03,softmin_tau=.02,backbone_kind="tiny",backbone_dtype="fp32",model_path=None,
                model_identity_file=None,expected_model_sha256=None,tiny_hidden_size=16,tiny_e2e=True,
            )
            result=MOD.train(args)
            self.assertEqual(result["status"],"PASS_V2_14_LISTWISE_TOP5_FOLD")
            self.assertTrue(result["exact_min_inference"])
            self.assertEqual(result["neural_input_firewall"]["candidate_id_input_count"],0)
            self.assertEqual(result["neural_input_firewall"]["candidate_docking_pose_input_count"],0)
            self.assertEqual(result["training"]["batch_size"],32)
            self.assertEqual(result["training"]["listwise_loss"]["top_k"],4)


if __name__=="__main__":unittest.main()
