#!/usr/bin/env python3
"""Write a deterministic package checksum list (excluding itself)."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evidence/manifests/SHA256SUMS"
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    files = [
        p
        for p in ROOT.rglob("*")
        if p.is_file() and p != OUT and not (set(p.relative_to(ROOT).parts) & EXCLUDED_PARTS)
    ]
    OUT.write_text(
        "\n".join(f"{digest(path)}  {path.relative_to(ROOT)}" for path in sorted(files)) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(files)} checksums")


if __name__ == "__main__":
    main()
