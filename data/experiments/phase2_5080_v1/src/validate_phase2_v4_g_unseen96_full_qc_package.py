#!/usr/bin/env python3
"""Validate the frozen label-free V4-G unseen96 Full-QC package."""

import argparse
import json
from pathlib import Path

from build_phase2_v4_g_unseen96_full_qc_package import (
    DEFAULT_FREEZE_RECEIPT,
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT,
    DEFAULT_PREREG,
    validate_package,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREG)
    parser.add_argument("--freeze-receipt", type=Path, default=DEFAULT_FREEZE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = validate_package(args.output, args.manifest, args.preregistration, args.freeze_receipt)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
