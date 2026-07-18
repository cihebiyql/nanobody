import csv
import gzip
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest


HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[1]
DEPLOYMENT_DIR = ROOT / "deployment"
sys.path.insert(0, str(DEPLOYMENT_DIR))
import build_node1_smoke_package_v1 as mod


CANONICAL_FORMULA = (
    ROOT.parents[0]
    / "v2_4_fs_stack_prototype_v1_20260718"
    / "contact_contract/contact_score_formula_v1.json"
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path, fieldnames, rows, gz=False):
    context = gzip.open(path, "wt", newline="") if gz else path.open("w", newline="")
    with context as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_source(root: pathlib.Path):
    base = root / "node1_bundle"
    training = base / "inputs/split_training/outer_0_inner_0.tsv"
    contacts = base / "inputs/split_contacts"
    graphs = base / "inputs/split_graphs/outer_0_inner_0"
    plan = base / "plan/trainer_splits"
    for directory in (training.parent, contacts, graphs, plan):
        directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(1269):
        if index < 1085:
            parent = f"T{index % 22:02d}"
        else:
            parent = f"S{(index - 1085) % 6:02d}"
        rows.append({"candidate_id": f"C{index:04d}", "parent_framework_cluster": parent})
    write_tsv(training, ["candidate_id", "parent_framework_cluster"], rows)
    contact_rows = [{"candidate_id": row["candidate_id"], "value": "0.1"} for row in rows]
    write_tsv(contacts / "outer_0_inner_0.marginal.tsv.gz", ["candidate_id", "value"], contact_rows, gz=True)
    write_tsv(contacts / "outer_0_inner_0.pair.tsv.gz", ["candidate_id", "value"], contact_rows, gz=True)
    graph_rows = [{"entity_id": row["candidate_id"], "value": row["value"]} for row in contact_rows]
    write_tsv(graphs / "graph_manifest_v2.tsv", ["entity_id", "value"], graph_rows)
    (graphs / "graph_cache_receipt_v2.json").write_text("{}\n")
    (graphs / "graph_cache_v2.npz").write_bytes(b"fake-npz")
    formula = base / "inputs/contact_score_formula_v1.json"
    formula.parent.mkdir(parents=True, exist_ok=True)
    formula.write_bytes(CANONICAL_FORMULA.read_bytes())
    split = {
        "split_id": "outer_0_inner_0",
        "outer_fold": 0,
        "open_only": True,
        "v4_f_test32_access_count": 0,
        "fixed_epochs": 8,
        "training_tsv_sha256": sha(training),
        "train_parents": [f"T{i:02d}" for i in range(22)],
        "score_parents": [f"S{i:02d}" for i in range(6)],
    }
    (plan / "outer_0_inner_0.json").write_text(json.dumps(split) + "\n")
    files = sorted(path for path in root.rglob("*") if path.is_file())
    (root / "SHA256SUMS").write_text(
        "".join(f"{sha(path)}  {path.relative_to(root)}\n" for path in files)
    )
    return root


class TestNode1PackageBuilder(unittest.TestCase):
    def test_build_and_audit_nonlaunching_six_job_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            source = make_source(root / "source")
            output = root / "package"
            manifest = mod.build_package(output, source)
            self.assertFalse(manifest["launch_authorized"])
            self.assertFalse(manifest["training_or_prediction_executed"])
            self.assertEqual(manifest["job_plan"]["jobs"], 6)
            plan = json.loads((output / "NONLAUNCHING_JOB_PLAN.json").read_text())
            self.assertTrue(all(job["command"] is None for job in plan["jobs"]))
            self.assertEqual({job["physical_gpu"] for job in plan["jobs"]}, {2, 4, 5})
            self.assertEqual(sum(job["kind"].endswith("PREOPTIMIZER_NO_OPTIMIZER") for job in plan["jobs"]), 3)
            self.assertEqual(sum("ONE_EPOCH" in job["kind"] for job in plan["jobs"]), 3)
            for lane in mod.LANES:
                smoke = next(job for job in plan["jobs"] if job["job_id"] == f"{lane}.one_epoch_smoke")
                self.assertEqual(smoke["dependencies"], [f"{lane}.preoptimizer"])
            audit = mod.audit_package(output)
            self.assertEqual(audit["status"], "PASS_NONLAUNCHING_PACKAGE_AUDIT")
            self.assertFalse(audit["launch_authorized"])
            self.assertEqual(audit["v4_f_test32_access_count"], 0)

    def test_sealed_string_values_fail_but_zero_access_key_is_allowed(self):
        mod.reject_sealed({"v4_f_test32_access_count": 0, "path": "/data/open/train.tsv"})
        with self.assertRaisesRegex(mod.PackageBuildError, "sealed_reference_forbidden"):
            mod.reject_sealed({"path": "/data/V4-F/test32.tsv"})


if __name__ == "__main__":
    unittest.main()
