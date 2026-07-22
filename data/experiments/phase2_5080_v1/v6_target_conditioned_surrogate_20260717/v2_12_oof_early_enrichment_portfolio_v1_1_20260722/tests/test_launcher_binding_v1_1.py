from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LauncherBindingTests(unittest.TestCase):
    def test_launcher_binds_train9849_not_canonical10644(self) -> None:
        text = (ROOT / "launchers/run_after_clean_oof_node1_v1_1.sh").read_text(encoding="utf-8")
        self.assertIn("TEACHER=$OOF_ROOT/prepared/train9849_teacher.tsv", text)
        self.assertIn("beb3205b998105b900c9d31207d7ff61b6b462f9188d58e5b896c985056c90f0", text)
        self.assertNotIn("TEACHER=/data1/qlyu/projects/pvrig_v29_canonical_merged_teacher", text)
        self.assertIn("len({row['candidate_id'] for row in rows})==expected", text)


if __name__ == "__main__":
    unittest.main()
