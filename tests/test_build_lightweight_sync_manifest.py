from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.build_lightweight_sync_manifest import (
    build_manifest,
    is_excluded_dir,
    validate_total_size,
)


PROJECT = "code/pvrig_500k_generation_20260721"


class LightweightSyncManifestTests(unittest.TestCase):
    def test_excludes_generated_code_runtime_trees(self) -> None:
        self.assertTrue(is_excluded_dir(f"{PROJECT}/run"))
        self.assertTrue(is_excluded_dir("pvrig-vhh-sicbc-submission"))
        self.assertTrue(
            is_excluded_dir(
                f"{PROJECT}/deployment/example/reallocation_work"
            )
        )
        self.assertTrue(is_excluded_dir("code/results"))

    def test_keeps_source_docs_tests_and_runtime_implementation(self) -> None:
        self.assertFalse(is_excluded_dir(f"{PROJECT}/scripts"))
        self.assertFalse(is_excluded_dir(f"{PROJECT}/docs"))
        self.assertFalse(is_excluded_dir(f"{PROJECT}/tests"))
        self.assertFalse(
            is_excluded_dir(f"{PROJECT}/deployment/example/runtime")
        )

    def test_manifest_keeps_implementation_but_skips_generated_payloads(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                f"{PROJECT}/scripts/build.py": "print('keep')\n",
                f"{PROJECT}/docs/README.md": "# Keep\n",
                f"{PROJECT}/tests/test_build.py": "def test_keep(): pass\n",
                f"{PROJECT}/deployment/example/runtime/worker.sh": "#!/bin/sh\n",
                f"{PROJECT}/run/job/results.json": '{"drop": true}\n',
                (
                    f"{PROJECT}/deployment/example/reallocation_work/"
                    "production/scripts/copied.py"
                ): "print('drop duplicate')\n",
                "code/results/benchmark/output.json": '{"drop": true}\n',
            }
            for rel, content in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            selected = {rel for rel, _ in build_manifest(root)}

        self.assertIn(f"{PROJECT}/scripts/build.py", selected)
        self.assertIn(f"{PROJECT}/docs/README.md", selected)
        self.assertIn(f"{PROJECT}/tests/test_build.py", selected)
        self.assertIn(
            f"{PROJECT}/deployment/example/runtime/worker.sh", selected
        )
        self.assertNotIn(f"{PROJECT}/run/job/results.json", selected)
        self.assertNotIn(
            (
                f"{PROJECT}/deployment/example/reallocation_work/"
                "production/scripts/copied.py"
            ),
            selected,
        )
        self.assertNotIn("code/results/benchmark/output.json", selected)

    def test_total_size_guard_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_total_size([("one.json", 6), ("two.md", 5)], 10)

    def test_manifest_skips_paths_too_deep_for_portable_checkout(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = "/".join(["deep"] * 50) + "/result.json"
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"drop": true}\n', encoding="utf-8")

            selected = {item for item, _ in build_manifest(root)}

        self.assertGreater(len(rel), 220)
        self.assertNotIn(rel, selected)


if __name__ == "__main__":
    unittest.main()
