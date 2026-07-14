import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PROTOCOL = ROOT / "config" / "protocol_spec.json"
REPORTS = ROOT / "reports"


def load_module(name):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_tsv(path, rows, fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class StabilityGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="stability_gate_", dir=REPORTS))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_clean_pdb(self, name="clean.pdb"):
        pdb = self.tmp / name
        pdb.write_text(
            "ATOM      1  N   ALA T  71       0.000   0.000   0.000  1.00 20.00           N  \n"
            "ATOM      2  CA  ALA T  71       1.000   0.000   0.000  1.00 20.00           C  \n"
            "END\n",
            encoding="utf-8",
        )
        return pdb

    def _manifest_rows(self, entities=(), include_controls=True, pdb_path=None):
        if pdb_path is None:
            pdb_path = self._write_clean_pdb()
        protocol_hash = "p" * 64
        rows = []
        entity_ids = list(entities)
        if include_controls:
            entity_ids.extend(f"CTRL_{i:02d}" for i in range(1, 48))
        for entity_id in entity_ids:
            entity_type = "control" if entity_id.startswith("CTRL_") else "candidate"
            control_class = "positive" if entity_id.startswith("CTRL_0") else "destructive" if entity_id.startswith("CTRL_4") else "negative"
            for conformation in ("8x6b", "9e6y"):
                for seed in (917, 1931, 3253):
                    cfg_text = f"entity={entity_id}\nconformation={conformation}\nseed={seed}\n"
                    cfg_hash = __import__("hashlib").sha256(cfg_text.encode()).hexdigest()
                    job_hash = __import__("hashlib").sha256(f"{protocol_hash}:{entity_id}:{conformation}:{seed}:{cfg_hash}".encode()).hexdigest()
                    rows.append(
                        {
                            "job_id": f"{entity_id}_{conformation}_{seed}",
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "control_class": control_class if entity_type == "control" else "",
                            "conformation": conformation,
                            "seed": str(seed),
                            "protocol_hash": protocol_hash,
                            "cfg_text": cfg_text.replace("\n", "\\n"),
                            "cfg_hash": cfg_hash,
                            "job_hash": job_hash,
                            "pdb_path": str(pdb_path),
                            "receptor_chain": "T",
                            "ligand_chain": "L",
                            "numbering": "UniProt_Q6DKI7",
                        }
                    )
        return rows

    def _passing_results(self, rows):
        result_rows = []
        for row in rows:
            cls = "A" if row["control_class"] == "positive" else "C"
            result_rows.append(
                {
                    "job_id": row["job_id"],
                    "state": "SUCCESS",
                    "native_class": cls,
                    "cross_class": cls,
                    "native_score": "1.0",
                    "cross_score": "0.9",
                    "anomaly_flag": "false",
                    "unstable_flag": "false",
                }
            )
        return result_rows

    def test_validate_protocol_reports_not_ready_when_no_jobs_exist(self):
        validate_protocol = load_module("validate_protocol")
        output = self.tmp / "validation.json"

        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(self.tmp / "missing.tsv"), "--out", str(output)])

        self.assertNotEqual(code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "NOT_READY")
        self.assertIn("job_manifest", payload["gates"])

    def test_validate_protocol_rejects_hetatm_and_seed_missing_from_cfg_text(self):
        validate_protocol = load_module("validate_protocol")
        bad_pdb = self.tmp / "bad.pdb"
        bad_pdb.write_text(
            "ATOM      1  N   ALA T  71       0.000   0.000   0.000  1.00 20.00           N  \n"
            "HETATM    2  O   HOH T 201       0.000   1.000   0.000  1.00 20.00           O  \n",
            encoding="utf-8",
        )
        rows = self._manifest_rows(entities=["CAND_001"], include_controls=False, pdb_path=bad_pdb)
        rows[0]["cfg_text"] = "entity=CAND_001\\nconformation=8x6b\\n"
        manifest = self.tmp / "jobs.tsv"
        write_tsv(manifest, rows)
        output = self.tmp / "validation.json"

        code = validate_protocol.main(["--protocol", str(PROTOCOL), "--jobs", str(manifest), "--out", str(output), "--expected-total-jobs", str(len(rows))])

        self.assertNotEqual(code, 0)
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("standard_atom_only", payload["gates"])
        self.assertIn("seed_in_cfg_hash", payload["gates"])

    def test_aggregate_writes_pass_when_all_stability_gates_succeed(self):
        aggregate_results = load_module("aggregate_results")
        rows = self._manifest_rows(entities=["CAND_001"], include_controls=True)
        manifest = self.tmp / "jobs.tsv"
        results = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(manifest, rows)
        write_tsv(results, self._passing_results(rows))

        code = aggregate_results.main(["--protocol", str(PROTOCOL), "--jobs", str(manifest), "--results", str(results), "--out", str(out), "--expected-total-jobs", str(len(rows))])

        self.assertEqual(code, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["job_count"], len(rows))
        self.assertTrue((self.tmp / "control_drift.tsv").exists())
        self.assertTrue((self.tmp / "threshold_sensitivity.tsv").exists())
        self.assertTrue((self.tmp / "job_state_summary.tsv").exists())

    def test_aggregate_marks_fail_when_positive_controls_collapse_to_e_only(self):
        aggregate_results = load_module("aggregate_results")
        rows = self._manifest_rows(entities=["CAND_001"], include_controls=True)
        result_rows = self._passing_results(rows)
        for row in rows:
            if row["control_class"] == "positive":
                for result in result_rows:
                    if result["job_id"] == row["job_id"]:
                        result["native_class"] = "E"
                        result["cross_class"] = "E"
        manifest = self.tmp / "jobs.tsv"
        results = self.tmp / "results.tsv"
        out = self.tmp / "EVALUATOR_STABLE.json"
        write_tsv(manifest, rows)
        write_tsv(results, result_rows)

        code = aggregate_results.main(["--protocol", str(PROTOCOL), "--jobs", str(manifest), "--results", str(results), "--out", str(out), "--expected-total-jobs", str(len(rows))])

        self.assertNotEqual(code, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["status"], "FAIL")
        self.assertIn("positive_controls_not_e_only", payload["gates"])

    def test_guard_requires_pass_status_and_matching_hashes(self):
        guard_next_generation = load_module("guard_next_generation")
        evaluator = self.tmp / "EVALUATOR_STABLE.json"
        evaluator.write_text(json.dumps({"status": "PASS", "protocol_hash": "abc", "job_set_hash": "def"}), encoding="utf-8")

        ok = guard_next_generation.main(["--evaluator", str(evaluator), "--protocol-hash", "abc", "--job-set-hash", "def"])
        bad = guard_next_generation.main(["--evaluator", str(evaluator), "--protocol-hash", "abc", "--job-set-hash", "mismatch"])

        self.assertEqual(ok, 0)
        self.assertNotEqual(bad, 0)

    def test_scripts_exit_nonzero_for_current_empty_state(self):
        out = self.tmp / "empty_eval.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "aggregate_results.py"), "--protocol", str(PROTOCOL), "--jobs", str(self.tmp / "missing.tsv"), "--results", str(self.tmp / "missing_results.tsv"), "--out", str(out)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "NOT_READY")


if __name__ == "__main__":
    unittest.main()
