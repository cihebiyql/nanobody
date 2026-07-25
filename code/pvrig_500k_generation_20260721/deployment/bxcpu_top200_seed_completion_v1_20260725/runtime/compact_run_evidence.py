#!/usr/bin/env python3
"""Create compact, hash-indexed evidence for one successful HADDOCK job."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import pathlib
import shutil
import tarfile
import time
from typing import Any


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def required_members(root: pathlib.Path, job_id: str) -> tuple[dict[str, Any], list[str]]:
    result_path = root / "results" / job_id / "job_result.json"
    result = json.loads(result_path.read_text())
    if result.get("state") != "SUCCESS" or result.get("job_id") != job_id:
        raise RuntimeError("job_result is not a matching SUCCESS")
    selected = [str(value) for value in result.get("selected_models", [])]
    if not selected:
        raise RuntimeError("SUCCESS result has no selected models")
    prefix = f"runs/{job_id}"
    members = [
        f"{prefix}/job.json",
        f"{prefix}/haddock3.cfg",
        f"{prefix}/data/air.tbl",
        f"{prefix}/haddock.stdout.log",
        f"{prefix}/haddock.stderr.log",
        f"{prefix}/SCRATCH_PROVENANCE.json",
        f"{prefix}/haddock_run/6_seletopclusts/io.json",
        *selected,
    ]
    return result, sorted(set(members))


def add_bytes(
    archive: tarfile.TarFile, relative: str, data: bytes, mode: int = 0o640
) -> None:
    info = tarfile.TarInfo(relative)
    info.size = len(data)
    info.mtime = int(time.time())
    info.mode = mode
    archive.addfile(info, io.BytesIO(data))


def add_full_result(
    archive: tarfile.TarFile,
    root: pathlib.Path,
    job_id: str,
    hashes: dict[str, str],
) -> None:
    relative = f"results/{job_id}/job_result.json"
    path = root / relative
    data = path.read_bytes()
    hashes[relative] = sha256_bytes(data)
    info = archive.gettarinfo(str(path), arcname=relative)
    with path.open("rb") as handle:
        archive.addfile(info, handle)


def add_manifest(
    archive: tarfile.TarFile,
    job_id: str,
    result: dict[str, Any],
    hashes: dict[str, str],
) -> None:
    payload = {
        "schema_version": "pvrig.compact_haddock_evidence.v2",
        "job_id": job_id,
        "job_hash": result.get("job_hash"),
        "protocol_core_sha256": result.get("protocol_core_sha256"),
        "selected_model_count": result.get("selected_model_count"),
        "files_sha256": hashes,
        "created_epoch": time.time(),
        "claim_boundary": (
            "Selected docking pose evidence only; not affinity or experimental blocking."
        ),
    }
    add_bytes(
        archive,
        f"runs/{job_id}/COMPACT_EVIDENCE.json",
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode(),
    )


def compact_directory(root: pathlib.Path, job_id: str, output: pathlib.Path) -> None:
    result, members = required_members(root, job_id)
    hashes: dict[str, str] = {}
    with tarfile.open(output, "w:gz", compresslevel=3) as archive:
        add_full_result(archive, root, job_id, hashes)
        for relative in members:
            path = root / relative
            if not path.is_file():
                if relative.endswith(
                    (
                        "SCRATCH_PROVENANCE.json",
                        "io.json",
                        "haddock.stdout.log",
                        "haddock.stderr.log",
                    )
                ):
                    continue
                raise FileNotFoundError(path)
            data = path.read_bytes()
            hashes[relative] = sha256_bytes(data)
            info = archive.gettarinfo(str(path), arcname=relative)
            with path.open("rb") as handle:
                archive.addfile(info, handle)
        add_manifest(archive, job_id, result, hashes)


def validate(path: pathlib.Path, job_id: str) -> None:
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
        manifest_name = f"runs/{job_id}/COMPACT_EVIDENCE.json"
        result_name = f"results/{job_id}/job_result.json"
        if manifest_name not in names or result_name not in names:
            raise RuntimeError("compact evidence manifest or full result is missing")
        if not any(
            "/6_seletopclusts/" in name and name.endswith((".pdb", ".pdb.gz"))
            for name in names
        ):
            raise RuntimeError("selected PDB evidence is missing")
        manifest_handle = archive.extractfile(manifest_name)
        if manifest_handle is None:
            raise RuntimeError("compact evidence manifest is unreadable")
        manifest = json.load(manifest_handle)
        for relative, expected in manifest["files_sha256"].items():
            handle = archive.extractfile(relative)
            if handle is None or sha256_bytes(handle.read()) != expected:
                raise RuntimeError(f"compact member hash mismatch: {relative}")


def minimize_published_result(
    output: pathlib.Path, job_id: str, result: dict[str, Any]
) -> None:
    if output.parent.name != "compressed_queue":
        return
    publish_root = output.parent.parent
    result_dir = publish_root / "results" / job_id
    result_path = result_dir / "job_result.json"
    if not result_path.is_file():
        return
    stub = {
        "state": "SUCCESS",
        "job_id": job_id,
        "job_hash": result.get("job_hash"),
        "protocol_core_sha256": result.get("protocol_core_sha256"),
        "selected_model_count": result.get("selected_model_count"),
        "selected_models": result.get("selected_models", []),
        "full_result_in_compact_archive": True,
        "offloaded_to_node1": False,
    }
    temporary_dir = result_dir.with_name(f".{job_id}.compact-result.{os.getpid()}")
    old_dir = result_dir.with_name(f".{job_id}.full-result.{os.getpid()}")
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    if old_dir.exists():
        shutil.rmtree(old_dir)
    temporary_dir.mkdir(parents=True)
    (temporary_dir / "job_result.json").write_text(
        json.dumps(stub, sort_keys=True) + "\n"
    )
    os.replace(result_dir, old_dir)
    os.replace(temporary_dir, result_dir)
    shutil.rmtree(old_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=pathlib.Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.unlink(missing_ok=True)
    result = json.loads(
        (args.project_root / "results" / args.job_id / "job_result.json").read_text()
    )
    compact_directory(args.project_root, args.job_id, args.output)
    validate(args.output, args.job_id)
    minimize_published_result(args.output, args.job_id, result)
    print(
        json.dumps(
            {
                "status": "PASS",
                "job_id": args.job_id,
                "bytes": args.output.stat().st_size,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
