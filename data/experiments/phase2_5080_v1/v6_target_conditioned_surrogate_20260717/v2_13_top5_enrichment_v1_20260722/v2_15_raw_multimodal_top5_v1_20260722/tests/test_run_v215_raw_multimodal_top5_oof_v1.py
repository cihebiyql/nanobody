from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("v215_raw_multimodal", HERE / "src/run_v215_raw_multimodal_top5_oof_v1.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("import")
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V215Test(unittest.TestCase):
    def test_percentile_reference(self) -> None:
        got = MOD.percentile_from_train(MOD.np.asarray([1.0, 2.0, 3.0]), MOD.np.asarray([0.0, 2.0, 4.0]))
        MOD.np.testing.assert_allclose(got, [0.0, 2/3, 1.0])

    def test_full_firewalled_oof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assignment, legacy, l1, raw = root/"assignment.tsv", root/"legacy.tsv", root/"l1.tsv", root/"raw.tsv"
            assignment_rows=[]; legacy_rows=[]; l1_rows=[]; raw_rows=[]
            raw_fields=["candidate_id","sequence_sha256","sequence","parent_framework_cluster","sample_weight","ALL__f0","ALL__f1","ALL__f2","C2__f0","C2__f1","C2__f2"]
            legacy_fields=["candidate_id","parent_framework_cluster","teacher_source","truth_R8","truth_R9","truth_Rdual_exact_min",
                "S0_MATCHED_ESM2_650M_PCA_ELASTICNET__R8","S0_MATCHED_ESM2_650M_PCA_ELASTICNET__R9","S0_MATCHED_ESM2_650M_PCA_ELASTICNET__Rdual_exact_min",
                "M2_STRUCTURE_ALPHA10__R8","M2_STRUCTURE_ALPHA10__R9","M2_STRUCTURE_ALPHA10__Rdual_exact_min",
                "C2_COARSE_POSE_PCA8__R8","C2_COARSE_POSE_PCA8__R9","C2_COARSE_POSE_PCA8__Rdual_exact_min"]
            l1_fields=["candidate_id","fold_id","truth_Rdual_exact_min","B_TOP5_L1__R8","B_TOP5_L1__R9","B_TOP5_L1__Rdual_exact_min"]
            for i in range(100):
                candidate=f"C{i:03d}"; parent=f"P{i//10:02d}"; fold=(i//10)%5; truth=0.4+0.002*i
                assignment_rows.append({"candidate_id":candidate,"sequence_sha256":f"s{i}","parent_framework_cluster":parent,"fold_id":fold})
                base={"candidate_id":candidate,"parent_framework_cluster":parent,"teacher_source":"TRAIN","truth_R8":truth+0.01,"truth_R9":truth,"truth_Rdual_exact_min":truth}
                for prefix,delta in (("S0_MATCHED_ESM2_650M_PCA_ELASTICNET",0.01),("M2_STRUCTURE_ALPHA10",-0.005),("C2_COARSE_POSE_PCA8",0.0)):
                    base[f"{prefix}__R8"]=truth+delta+0.01; base[f"{prefix}__R9"]=truth+delta; base[f"{prefix}__Rdual_exact_min"]=truth+delta
                legacy_rows.append(base)
                l1_rows.append({"candidate_id":candidate,"fold_id":fold,"truth_Rdual_exact_min":truth,"B_TOP5_L1__R8":truth+0.015,"B_TOP5_L1__R9":truth+0.005,"B_TOP5_L1__Rdual_exact_min":truth+0.005})
                raw_rows.append({"candidate_id":candidate,"sequence_sha256":f"s{i}","sequence":"A"*110,"parent_framework_cluster":parent,"sample_weight":1.0,"ALL__f0":i,"ALL__f1":i%7,"ALL__f2":i%11,"C2__f0":truth,"C2__f1":i%5,"C2__f2":i%3})
            for i in range(5):
                raw_rows.append({"candidate_id":f"OPEN{i}","sequence_sha256":"x","sequence":"A"*110,"parent_framework_cluster":"OPEN","sample_weight":1.0,"ALL__f0":999,"ALL__f1":999,"ALL__f2":999,"C2__f0":999,"C2__f1":999,"C2__f2":999})
            write_tsv(assignment,["candidate_id","sequence_sha256","parent_framework_cluster","fold_id"],assignment_rows)
            write_tsv(legacy,legacy_fields,legacy_rows); write_tsv(l1,l1_fields,l1_rows); write_tsv(raw,raw_fields,raw_rows)
            contract={"schema_version":MOD.CONTRACT_SCHEMA,"status":"FROZEN_BEFORE_V2_15_OOF_EXECUTION","data":{"expected_rows":100,"expected_parents":10,"expected_folds":5,"expected_raw_numeric_features":6,"open_rows_excluded_before_value_parsing":5},
                "input_bindings":{"raw_multimodal_sha256":sha(raw),"assignment_sha256":sha(assignment),"legacy_oof_sha256":sha(legacy),"l1_oof_sha256":sha(l1)},
                "hgb_classifier":{"learning_rate":0.1,"max_iter":5,"max_leaf_nodes":5,"min_samples_leaf":5,"l2_regularization":1.0},
                "extra_trees":{"n_estimators":10,"max_depth":4,"min_samples_leaf":2,"max_features":0.5,"n_jobs":1},
                "hgb_regressor":{"learning_rate":0.1,"max_iter":5,"max_leaf_nodes":5,"min_samples_leaf":5,"l2_regularization":1.0,"loss":"absolute_error"},
                "input_access":{"open_development_rows":0,"frozen_test_rows":0}}
            contract_path=root/"contract.json"; contract_path.write_text(json.dumps(contract))
            out=root/"out"; report=MOD.run(contract_path,raw,assignment,legacy,l1,out)
            self.assertEqual(report["counts"]["rows"],100)
            self.assertEqual(report["feature_firewall"]["open_rows_excluded_before_value_parsing"],5)
            self.assertEqual(report["input_access"],{"open_development_rows":0,"frozen_test_rows":0})
            self.assertTrue((out/"RUN_RECEIPT.json").is_file())


if __name__ == "__main__":
    unittest.main()
