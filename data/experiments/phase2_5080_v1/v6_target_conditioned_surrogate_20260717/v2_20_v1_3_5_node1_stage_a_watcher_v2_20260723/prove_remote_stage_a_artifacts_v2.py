#!/usr/bin/env python3
"""Read-only remote proof for terminal Stage-A receipt artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{64}$")
RECEIPT_NAME = "NODE1_V1_3_5_PREFLIGHT_RECEIPT.json"


def read_regular(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"not_regular:{path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    if not raw or identity(before) != identity(after):
        raise RuntimeError(f"unstable_or_empty:{path}")
    return raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    receipt = args.runtime / RECEIPT_NAME
    sidecar = args.runtime / f"{RECEIPT_NAME}.sha256"
    raw = read_regular(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    if not SHA_RE.fullmatch(digest):
        raise RuntimeError("digest")
    if read_regular(sidecar) != f"{digest}  {RECEIPT_NAME}\n".encode():
        raise RuntimeError("sidecar_mismatch")
    content_name = f"{receipt.stem}.{digest}.json"
    content = args.runtime / content_name
    if read_regular(content) != raw:
        raise RuntimeError("content_mismatch")
    if read_regular(args.evidence / "PREFLIGHT_LAUNCHER.rc") != b"0\n":
        raise RuntimeError("launcher_rc")
    read_regular(args.evidence / "PREFLIGHT_LAUNCHER.log")
    print(json.dumps({
        "status": "PASS_REMOTE_REGULAR_NONSYMLINK_STAGE_A_ARTIFACTS",
        "receipt_name": RECEIPT_NAME,
        "sidecar_name": f"{RECEIPT_NAME}.sha256",
        "content_name": content_name,
        "receipt_sha256": digest,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
