#!/usr/bin/env python3
"""Child wrapper: pass the runtime-only token to the frozen evaluator in memory."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--expected-evaluator-sha256", required=True)
    parser.add_argument("--execution-manifest", required=True)
    parser.add_argument("--input-closure-receipt", required=True)
    parser.add_argument("--authorization-overlay", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    evaluator = Path(args.evaluator).resolve()
    if not evaluator.is_file() or evaluator.is_symlink():
        raise RuntimeError("frozen_evaluator_regular_file_required")
    if sha256_file(evaluator) != args.expected_evaluator_sha256:
        raise RuntimeError("frozen_evaluator_hash_mismatch")
    token = os.environ.pop("PVRIG_V2_5_AUTH_TOKEN", "")
    if not token:
        raise RuntimeError("runtime_authorization_token_missing")
    spec = importlib.util.spec_from_file_location("frozen_v2_5_evaluator", evaluator)
    if spec is None or spec.loader is None:
        raise RuntimeError("frozen_evaluator_import_failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.argv = [
        str(evaluator),
        "--execution-manifest", args.execution_manifest,
        "--input-closure-receipt", args.input_closure_receipt,
        "--authorization-overlay", args.authorization_overlay,
        "--authorization-token", token,
        "--contract", args.contract,
        "--input-root", args.input_root,
        "--runtime-root", args.runtime_root,
        "--output-dir", args.output_dir,
    ]
    try:
        return int(module.main())
    finally:
        token = ""
        sys.argv = [sys.argv[0]]


if __name__ == "__main__":
    raise SystemExit(main())
