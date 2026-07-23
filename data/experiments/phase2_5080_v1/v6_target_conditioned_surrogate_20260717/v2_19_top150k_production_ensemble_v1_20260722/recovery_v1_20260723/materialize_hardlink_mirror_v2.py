#!/usr/bin/env python3
"""Create or verify a content-bound hardlink mirror for label-free monomers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

FORBIDDEN = ("docking", "docked", "haddock", "pose", "complex", "job_result")


class MirrorError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise MirrorError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def check_safe_root(path: Path) -> None:
    require(path.is_absolute(), "safe_root_not_absolute")
    for part in path.parts:
        lowered = part.lower()
        require(not any(token in lowered for token in FORBIDDEN), f"safe_root_forbidden_component:{part}")
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current /= part
        require(current.exists(), f"safe_root_ancestor_missing:{current}")
        require(not current.is_symlink(), f"safe_root_ancestor_symlink:{current}")


def read_rows(manifest: Path, expected_rows: int) -> list[dict[str, str]]:
    require(manifest.is_file() and not manifest.is_symlink(), "manifest_invalid")
    with manifest.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    require(len(rows) == expected_rows, f"manifest_row_count:{len(rows)}")
    required = {"candidate_id", "monomer_relative_path", "monomer_sha256"}
    require(rows and required.issubset(rows[0]), "manifest_columns_missing")
    return rows


def inspect_rows(rows: list[dict[str, str]], source: Path, mirror: Path, *, create: bool) -> dict:
    seen_candidates: set[str] = set()
    seen_relatives: set[str] = set()
    inventory = hashlib.sha256()
    bytes_total = 0
    for row_number, row in enumerate(rows, 1):
        candidate = row["candidate_id"].strip()
        relative_text = row["monomer_relative_path"].strip()
        expected_sha = row["monomer_sha256"].strip().lower()
        require(candidate and candidate not in seen_candidates, f"candidate_duplicate:{row_number}")
        require(len(expected_sha) == 64 and all(c in "0123456789abcdef" for c in expected_sha), f"sha_invalid:{candidate}")
        relative = PurePosixPath(relative_text)
        require(relative_text == relative.as_posix() and not relative.is_absolute(), f"relative_invalid:{candidate}")
        require(".." not in relative.parts and "." not in relative.parts, f"relative_escape:{candidate}")
        require(relative_text not in seen_relatives, f"relative_duplicate:{candidate}")
        for part in relative.parts:
            lowered = part.lower()
            require(not any(token in lowered for token in FORBIDDEN), f"relative_forbidden:{candidate}:{part}")
        src = source.joinpath(*relative.parts)
        dst = mirror.joinpath(*relative.parts)
        src_lstat = src.lstat()
        require(stat.S_ISREG(src_lstat.st_mode) and src_lstat.st_size > 0, f"source_not_regular:{candidate}")
        require(not src.is_symlink(), f"source_symlink:{candidate}")
        if create:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.link(src, dst, follow_symlinks=False)
        dst_lstat = dst.lstat()
        require(stat.S_ISREG(dst_lstat.st_mode) and dst_lstat.st_size > 0, f"mirror_not_regular:{candidate}")
        require(not dst.is_symlink(), f"mirror_symlink:{candidate}")
        require(src_lstat.st_dev == dst_lstat.st_dev, f"device_mismatch:{candidate}")
        require(src_lstat.st_ino == dst_lstat.st_ino, f"inode_mismatch:{candidate}")
        require(dst_lstat.st_nlink >= 2, f"link_count_invalid:{candidate}")
        require(src_lstat.st_size == dst_lstat.st_size, f"size_mismatch:{candidate}")
        observed_sha = sha256_file(dst)
        require(observed_sha == expected_sha, f"mirror_sha256_mismatch:{candidate}")
        inventory.update(f"{candidate}\t{relative_text}\t{expected_sha}\t{dst_lstat.st_size}\n".encode())
        bytes_total += dst_lstat.st_size
        seen_candidates.add(candidate)
        seen_relatives.add(relative_text)
    return {
        "rows": len(rows),
        "unique_candidates": len(seen_candidates),
        "unique_relative_paths": len(seen_relatives),
        "bytes": bytes_total,
        "hardlink_inventory_sha256": inventory.hexdigest(),
    }


def run(args: argparse.Namespace) -> dict:
    source = args.source_root.resolve(strict=True)
    mirror = args.mirror_root.absolute()
    check_safe_root(mirror)
    require(source.is_dir() and not source.is_symlink(), "source_root_invalid")
    require(mirror.parent.is_dir() and not mirror.parent.is_symlink(), "mirror_parent_invalid")
    require(source.stat().st_dev == mirror.parent.stat().st_dev, "cross_device_mirror_forbidden")
    rows = read_rows(args.manifest, args.expected_rows)
    if args.mode == "create":
        require(not mirror.exists() and not mirror.is_symlink(), "mirror_root_exists")
        partial = mirror.with_name(f".{mirror.name}.partial.{os.getpid()}.{uuid.uuid4().hex}")
        require(not partial.exists(), "partial_exists")
        partial.mkdir(mode=0o750)
        try:
            metrics = inspect_rows(rows, source, partial, create=True)
            os.replace(partial, mirror)
        finally:
            if partial.exists():
                import shutil
                shutil.rmtree(partial)
    else:
        require(mirror.is_dir() and not mirror.is_symlink(), "mirror_root_invalid")
        metrics = inspect_rows(rows, source, mirror, create=False)
    payload = {
        "schema_version": "pvrig_top150k_label_free_hardlink_mirror_v2",
        "status": "PASS_TOP150K_LABEL_FREE_HARDLINK_MIRROR",
        "mode": args.mode,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "manifest": {"path": str(args.manifest.resolve(strict=True)), "sha256": sha256_file(args.manifest)},
        "source_root": str(source),
        "mirror_root": str(mirror),
        "checks": {
            "same_device_inode_all_rows": True,
            "nonempty_regular_nonsymlink_all_rows": True,
            "st_nlink_at_least_two_all_rows": True,
            "manifest_sha256_match_all_rows": True,
            "safe_path_components_all_rows": True,
            "atomic_partial_to_final_rename": args.mode == "create",
        },
        **metrics,
        "truth_access": {"candidate_docking_pose_files_opened": 0, "teacher_labels_opened": 0},
    }
    atomic_json(args.receipt, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("create", "validate"), required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--mirror-root", type=Path, required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args), sort_keys=True))


if __name__ == "__main__":
    main()
