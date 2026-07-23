#!/usr/bin/env python3
"""Run an exact allowlisted set of unittest files without package discovery.

The standard ``python -m unittest tests/test_x.py`` path imports
``tests.test_x``.  On the bxcpu Python 3.11 environment an unrelated
site-packages distribution owns the top-level ``tests`` package, so that
invocation never reaches the frozen repository files.  This adapter loads
each explicitly supplied regular file under a private module name and then
uses unittest only to collect tests from that already-loaded module.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


class ExactFileTestError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ExactFileTestError(message)


def load_suite(root: Path, relative_files: list[str]) -> unittest.TestSuite:
    root = root.resolve(strict=True)
    require(root.is_dir() and not root.is_symlink(), "root_not_regular_directory")
    require(bool(relative_files), "no_test_files")
    require(len(relative_files) == len(set(relative_files)), "duplicate_test_file")

    sys.path[:0] = [str(root), str(root / "src")]
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for index, relative_text in enumerate(relative_files):
        relative = Path(relative_text)
        require(
            not relative.is_absolute()
            and relative.parent == Path("tests")
            and relative.name.startswith("test_")
            and relative.suffix == ".py",
            f"invalid_test_relative_path:{relative_text}",
        )
        path = root / relative
        require(path.is_file() and not path.is_symlink(), f"test_not_regular_file:{relative_text}")
        require(path.resolve().parent == (root / "tests").resolve(), f"test_escapes_root:{relative_text}")
        digest = hashlib.sha256(relative_text.encode()).hexdigest()[:16]
        module_name = f"_v220_exact_file_test_{index:02d}_{digest}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        require(spec is not None and spec.loader is not None, f"cannot_load_test:{relative_text}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        suite.addTests(loader.loadTestsFromModule(module))
    return suite


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("relative_test_file", nargs="+")
    parser.add_argument("--verbosity", type=int, default=2)
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=args.verbosity).run(
        load_suite(args.root, args.relative_test_file)
    )
    print(f"EXACT_FILE_TESTS_RUN={result.testsRun}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
