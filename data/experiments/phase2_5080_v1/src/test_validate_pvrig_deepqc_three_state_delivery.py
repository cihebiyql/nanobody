import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


VALIDATOR = load("delivery_validator_test", HERE / "validate_pvrig_deepqc_three_state_delivery.py")
MERGE = load("merge_evidence_test", HERE / "merge_pvrig_candidate_evidence_v2.py")


def write_tsv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def tnp_rows():
    rows = []
    for index in range(85):
        rows.append({
            "id": f"valid_{index}", "tnp_supervision_state": "VALID_TNP",
            "tnp_result_json_sha256": "b" * 64,
            "tnp_PSH": "1", "tnp_PPC": "2", "tnp_PNC": "3",
            **{field: "GREEN" for field in VALIDATOR.TNP_FLAG_FIELDS},
        })
    for index in range(7):
        rows.append({
            "id": f"numbering_{index}", "tnp_supervision_state": "TNP_NUMBERING_HARD_FAIL_NA",
            "tnp_result_json_sha256": "c" * 64,
            **{field: "" for field in (*VALIDATOR.TNP_NUMERIC_FIELDS, *VALIDATOR.TNP_FLAG_FIELDS)},
        })
    for index in range(8):
        rows.append({
            "id": f"upstream_{index}", "tnp_supervision_state": "UPSTREAM_L2_HARD_FAIL_NA",
            "tnp_result_json_sha256": "",
            **{field: "" for field in (*VALIDATOR.TNP_NUMERIC_FIELDS, *VALIDATOR.TNP_FLAG_FIELDS)},
        })
    return rows


class ThreeStateDeliveryTests(unittest.TestCase):
    def build_delivery(self, root):
        rows = tnp_rows()
        igfold = [{"id": row["id"], "igfold_status": "VALID_MONOMER_PREDICTION"} for row in rows]
        fixed = [
            root / "run_deepqc.sh", root / "deepqc_config.json", root / "input_audit.json",
            root / "inputs/pre_shortlist100.fasta", root / "inputs/pre_shortlist100.tsv",
            root / "reports/tnp_summary.tsv", root / "reports/tnp_merge.json",
            root / "reports/igfold_summary.tsv", root / "reports/igfold_merge.json",
            root / "reports/INPUT_SHA256SUMS.txt", root / "status/deepqc_status.json",
        ]
        for path in fixed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n")
        write_tsv(root / "reports/tnp_summary.tsv", rows)
        write_tsv(root / "reports/igfold_summary.tsv", igfold)
        files = list(fixed)
        for row in rows:
            pdb = root / "structures" / row["id"] / "igfold.pdb"
            pdb.parent.mkdir(parents=True)
            pdb.write_text("ATOM\n")
            files.append(pdb)
        self.assertEqual(len(files), 111)
        manifest_rows = [{
            "path": str(path.relative_to(root)), "bytes": path.stat().st_size,
            "sha256": VALIDATOR.sha256_file(path),
        } for path in files]
        write_tsv(root / "reports/delivery_file_manifest.tsv", manifest_rows)
        receipt = {
            "status": "PASS_DEEPQC100_DELIVERY_READY", "candidate_count": 100,
            "tnp_row_count": 100, "igfold_row_count": 100, "igfold_pdb_count": 100,
            "tnp_state_counts": VALIDATOR.EXPECTED_STATES,
            "delivery_manifest_sha256": VALIDATOR.sha256_file(root / "reports/delivery_file_manifest.tsv"),
        }
        (root / "reports/deepqc_delivery_receipt_v1.json").write_text(json.dumps(receipt))

    def test_full_delivery_verifier_accepts_honest_partition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_delivery(root)
            result = VALIDATOR.validate_delivery(root)
            self.assertEqual(result["status"], "PASS_THREE_STATE_TNP_IGFOLD100_DELIVERY")

    def test_merge_keeps_na_numeric_fields_empty(self):
        rows = [{"candidate_id": "x"}, {"candidate_id": "y"}]
        evidence = {
            "x": {
                "tnp_supervision_state": "TNP_NUMBERING_HARD_FAIL_NA",
                "tnp_PSH": "", "tnp_PPC": "", "tnp_PNC": "",
            },
            "y": {
                "tnp_supervision_state": "VALID_TNP", "tnp_PSH": "1",
                "tnp_PPC": "2", "tnp_PNC": "3", "tnp_L_flag": "GREEN",
            },
        }
        MERGE.merge_tnp(rows, evidence)
        self.assertEqual(rows[0]["tnp_merge_status"], "MERGED_TNP_EXPLICIT_NA_NO_IMPUTATION")
        self.assertEqual((rows[0]["tnp_psh"], rows[0]["tnp_ppc"], rows[0]["tnp_pnc"]), ("", "", ""))
        evidence["x"]["tnp_PSH"] = "0"
        with self.assertRaises(MERGE.MergeError):
            MERGE.merge_tnp([{"candidate_id": "x"}], {"x": evidence["x"]})

    def test_monitor_is_wired_to_ssd_three_state_validator(self):
        text = (HERE / "monitor_pvrig_v4d_deepqc_postprocess.sh").read_text()
        self.assertIn("/data1/qlyu/pvrig_migration_20260716/deepqc_reconciliation_eligible92_igfold100_v3_1", text)
        self.assertIn("validate_pvrig_deepqc_three_state_delivery import validate_delivery", text)


if __name__ == "__main__":
    unittest.main()
