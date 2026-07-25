import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("vhh_screen_parallel_tnp.py")
SPEC = importlib.util.spec_from_file_location("vhh_screen_parallel_tnp", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ParallelTnpTest(unittest.TestCase):
    def test_completed_tnp_json_is_reused(self):
        candidate = MODULE.Candidate(seq_id="candidate/1", sequence="HVQLV")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sid = MODULE.safe_id(candidate.seq_id)
            output = root / "layer3_tnp" / sid
            output.mkdir(parents=True)
            result = {"Flags": {"Aggregation": "Green"}}
            (output / f"TNP_Results_SingleSeqEntry_{sid}.json").write_text(
                json.dumps({sid: result})
            )
            with mock.patch.object(MODULE, "run_cmd") as run_cmd:
                MODULE.run_tnp(candidate, root, 1, "4")
            run_cmd.assert_not_called()
            self.assertEqual(candidate.tnp, result)

    def test_invalid_tnp_json_is_not_accepted(self):
        candidate = MODULE.Candidate(seq_id="candidate", sequence="HVQLV")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{bad")
            self.assertFalse(MODULE.load_existing_tnp(candidate, path))

    def test_gpu_assignment_is_passed_to_tnp_subprocess(self):
        candidate = MODULE.Candidate(seq_id="candidate", sequence="HVQLV")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(MODULE, "run_cmd", return_value=False) as run_cmd:
                MODULE.run_tnp(candidate, root, 1, "2")
            self.assertEqual(run_cmd.call_args.kwargs["env"]["CUDA_VISIBLE_DEVICES"], "2")


if __name__ == "__main__":
    unittest.main()
