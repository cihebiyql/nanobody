#!/usr/bin/env python3
"""Create a hash-closed v2 handoff with insertion-aware VHH residue handling."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import tempfile
from datetime import datetime, timezone


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".partial",
        delete=False,
    ) as handle:
        handle.write(text)
        temporary = pathlib.Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: pathlib.Path, payload: dict) -> None:
    atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def replace_once(path: pathlib.Path, old: str, new: str) -> dict[str, str]:
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(
            f"{path}: expected one patch anchor, found {source.count(old)}"
        )
    before = sha256(path)
    atomic_text(path, source.replace(old, new))
    return {"before_sha256": before, "after_sha256": sha256(path)}


def hardlink_copy(source: str, destination: str) -> str:
    os.link(source, destination)
    return destination


def rebuild_sha256sums(root: pathlib.Path) -> str:
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix()
        if relative == "SHA256SUMS":
            continue
        rows.append(f"{sha256(path)}  {relative}")
    atomic_text(root / "SHA256SUMS", "\n".join(rows) + "\n")
    return sha256(root / "SHA256SUMS")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not (source / "READY.json").is_file():
        raise RuntimeError(f"source handoff is incomplete: {source}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite output: {output}")

    shutil.copytree(source, output, copy_function=hardlink_copy)
    try:
        run_job = output / "scripts/run_job.py"
        build_jobs = output / "scripts/build_docking_jobs.py"
        patch_records = {
            "scripts/run_job.py.return_type": replace_once(
                run_job,
                "def normalize_monomer(source: Path, source_chain: str, "
                "destination: Path) -> set[int]:",
                "def normalize_monomer(source: Path, source_chain: str, "
                "destination: Path) -> set[str]:",
            ),
            "scripts/run_job.py.residue_set": replace_once(
                run_job,
                "    residues: set[int] = set()\n",
                "    residues: set[str] = set()\n",
            ),
            "scripts/run_job.py.residue_identity": replace_once(
                run_job,
                "        residue = int(line[22:26])\n"
                "        residues.add(residue)\n",
                "        residue = f\"{int(line[22:26])}{line[26].strip()}\"\n"
                "        residues.add(residue)\n",
            ),
            "scripts/run_job.py.requested_residues": replace_once(
                run_job,
                "    requested_residues = {int(value) for value in "
                "job[\"cdr_residues\"].split(\",\") if value}\n",
                "    requested_residues = {value.strip() for value in "
                "job[\"cdr_residues\"].split(\",\") if value.strip()}\n",
            ),
            "scripts/build_docking_jobs.py.render_type": replace_once(
                build_jobs,
                "def render_restraints(cdr_residues: list[int], "
                "core_hash: str) -> str:",
                "def render_restraints(cdr_residues: list[str], "
                "core_hash: str) -> str:",
            ),
            "scripts/build_docking_jobs.py.provenance_comment": replace_once(
                build_jobs,
                '        "! VHH CDR residues (chain A) to 12 '
                'UniProt-numbered PVRIG AIR anchors (chain T)",\n',
                '        "! VHH CDR residues (source chain H, runtime chain A) '
                'to 12 UniProt-numbered PVRIG AIR anchors (chain T)",\n',
            ),
            "scripts/build_docking_jobs.py.render_from_job": replace_once(
                build_jobs,
                "def render_restraints_from_job(job: dict[str, str]) -> str:\n"
                "    residues = [int(value) for value in "
                "job[\"cdr_residues\"].split(\",\") if value]\n",
                "def render_restraints_from_job(job: dict[str, str]) -> str:\n"
                "    residues = [value.strip() for value in "
                "job[\"cdr_residues\"].split(\",\") if value.strip()]\n",
            ),
        }

        manifest = output / "manifests/docking_jobs.tsv"
        with manifest.open(encoding="utf-8") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            first = handle.readline().rstrip("\n").split("\t")
        row = dict(zip(header, first))
        insertion_tokens = [
            token
            for token in row["cdr_residues"].split(",")
            if re.fullmatch(r"-?\d+[A-Za-z]+", token)
        ]
        if not insertion_tokens:
            raise RuntimeError("first smoke job does not exercise insertion codes")

        receipt_path = output / "HANDOFF_RECEIPT.json"
        source_receipt_sha256 = sha256(receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["schema_version"] = (
            "pvrig.top5000.dualreceptor_4seed.handoff.v2"
        )
        receipt["package_version"] = (
            "pvrig_top5000_dualreceptor_4seed_handoff_v2_20260724"
        )
        receipt["runtime_compatibility_patch"] = {
            "status": "INSERTION_AWARE_VHH_RESIDUE_IDENTIFIERS",
            "reason": (
                "NBB2 IMGT-numbered PDBs contain insertion codes such as 111A; "
                "the inherited frozen runner parsed CDR residue identifiers as "
                "integers before HADDOCK execution."
            ),
            "scientific_scope": (
                "Preserves exact manifest CDR residue identifiers and AIR text; "
                "does not alter coordinates, receptor files, seeds, cfg hashes, "
                "job hashes, protocol_core_sha256, or blocker scoring rules."
            ),
            "source_v1_receipt_sha256": source_receipt_sha256,
            "smoke_insertion_tokens": insertion_tokens,
            "patched_files": patch_records,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(receipt_path, receipt)

        ready_path = output / "READY.json"
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        ready["schema_version"] = "pvrig.handoff.ready.v2"
        ready["package_version"] = receipt["package_version"]
        ready["handoff_receipt_sha256"] = sha256(receipt_path)
        ready["runtime_compatibility"] = "IMGT_INSERTION_CODES_SUPPORTED"
        atomic_json(ready_path, ready)

        report = {
            "schema_version": "pvrig.insertion_code_runtime_patch.v1",
            "status": "PASS_INSERTION_AWARE_RUNTIME_PATCH",
            "source_root": str(source),
            "source_ready_sha256": sha256(source / "READY.json"),
            "source_receipt_sha256": source_receipt_sha256,
            "output_root": str(output),
            "manifest_sha256": sha256(manifest),
            "job_count": sum(1 for _ in manifest.open(encoding="utf-8")) - 1,
            "first_smoke_job_id": row["job_id"],
            "first_smoke_insertion_tokens": insertion_tokens,
            "patched_files": patch_records,
            "coordinates_changed": False,
            "job_manifest_changed": False,
            "protocol_core_changed": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        atomic_json(
            output / "reports/INSERTION_CODE_RUNTIME_PATCH.json", report
        )
        report["ready_sha256"] = sha256(ready_path)
        report["receipt_sha256"] = sha256(receipt_path)
        atomic_json(
            output / "reports/INSERTION_CODE_RUNTIME_PATCH.json", report
        )
        sums_sha = rebuild_sha256sums(output)

        print(
            json.dumps(
                {
                    "status": "PASS_INSERTION_AWARE_RUNTIME_PATCH",
                    "output": str(output),
                    "manifest_sha256": sha256(manifest),
                    "ready_sha256": sha256(ready_path),
                    "receipt_sha256": sha256(receipt_path),
                    "sha256sums_sha256": sums_sha,
                    "first_smoke_job_id": row["job_id"],
                    "first_smoke_insertion_tokens": insertion_tokens,
                },
                sort_keys=True,
            )
        )
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
