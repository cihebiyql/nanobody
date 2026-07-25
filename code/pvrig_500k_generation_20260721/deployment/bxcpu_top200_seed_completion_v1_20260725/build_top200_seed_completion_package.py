#!/usr/bin/env python3
"""Build a hash-closed 106-candidate/424-job Top200 seed-completion bundle."""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tarfile
from typing import Any, Iterable


PACKAGE_NAME = "pvrig_top200_common4_seed_completion106_handoff_v1_20260725"
EXPECTED_CANDIDATES = 106
EXPECTED_JOBS = 424
EXPECTED_SEEDS = {"42", "3047"}
EXPECTED_CONFORMATIONS = {"8x6b", "9e6y"}
EXPECTED_PROTOCOL_CORE = (
    "8c55751f66ac2930ce115a9419321a2b2bed220b61af2e1671f7ac6e6a2e33b3"
)


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def read_tsv(path: pathlib.Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise RuntimeError(f"missing TSV header: {path}")
    return fields, rows


def write_tsv(
    path: pathlib.Path, fields: list[str], rows: Iterable[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def validate_matrix(rows: list[dict[str, str]]) -> list[str]:
    if len(rows) != EXPECTED_JOBS:
        raise RuntimeError(f"expected {EXPECTED_JOBS} jobs, found {len(rows)}")
    if len({row["job_id"] for row in rows}) != EXPECTED_JOBS:
        raise RuntimeError("job IDs are blank or duplicated")
    candidates = sorted({row["entity_id"] for row in rows})
    if len(candidates) != EXPECTED_CANDIDATES:
        raise RuntimeError(
            f"expected {EXPECTED_CANDIDATES} candidates, found {len(candidates)}"
        )
    if {row["seed"] for row in rows} != EXPECTED_SEEDS:
        raise RuntimeError("seed matrix is not exactly 42/3047")
    if {row["conformation"] for row in rows} != EXPECTED_CONFORMATIONS:
        raise RuntimeError("conformation matrix is not exactly 8x6b/9e6y")
    matrix = collections.Counter(
        (row["entity_id"], row["seed"], row["conformation"]) for row in rows
    )
    if len(matrix) != EXPECTED_JOBS or set(matrix.values()) != {1}:
        raise RuntimeError("candidate/seed/conformation matrix is not exact")
    per_candidate = collections.Counter(row["entity_id"] for row in rows)
    if set(per_candidate.values()) != {4}:
        raise RuntimeError("every candidate must have exactly four jobs")
    if {row["protocol_core_sha256"] for row in rows} != {
        EXPECTED_PROTOCOL_CORE
    }:
        raise RuntimeError("protocol core hash drift")
    return candidates


def copy_static(template: pathlib.Path, output: pathlib.Path) -> None:
    for directory in ("config", "scripts"):
        shutil.copytree(template / directory, output / directory)
    for directory in ("inputs/normalized", "inputs/source"):
        shutil.copytree(template / directory, output / directory)
    (output / "reports").mkdir(parents=True)
    shutil.copy2(
        template / "reports/reference_normalization_summary.json",
        output / "reports/reference_normalization_summary.json",
    )
    shutil.copy2(
        template / "PROTOCOL_CORE_LOCK.json", output / "PROTOCOL_CORE_LOCK.json"
    )
    validator = output / "scripts/validate_protocol.py"
    validator_text = validator.read_text()
    validator_text = validator_text.replace(
        'EXPECTED_SEEDS = {"917", "1931"}',
        'EXPECTED_SEEDS = {"42", "3047"}',
    ).replace(
        "seed_set_is_not_917_1931",
        "seed_set_is_not_42_3047",
    )
    validator.write_text(validator_text)


def copy_monomers(
    rows: list[dict[str, str]],
    monomer_source_root: pathlib.Path,
    output: pathlib.Path,
) -> dict[str, str]:
    expected: dict[str, str] = {}
    for row in rows:
        candidate = row["entity_id"]
        observed = expected.setdefault(candidate, row["monomer_sha256"])
        if observed != row["monomer_sha256"]:
            raise RuntimeError(f"multiple monomer hashes for {candidate}")
    monomer_dir = output / "inputs/candidate_monomers"
    monomer_dir.mkdir(parents=True)
    for candidate, digest in sorted(expected.items()):
        source = monomer_source_root / f"{candidate}.pdb"
        destination = monomer_dir / source.name
        if not source.is_file():
            raise FileNotFoundError(source)
        if sha256(source) != digest:
            raise RuntimeError(f"source monomer hash mismatch: {candidate}")
        shutil.copy2(source, destination)
        if sha256(destination) != digest:
            raise RuntimeError(f"copied monomer hash mismatch: {candidate}")
    return expected


def make_shards(
    fields: list[str], rows: list[dict[str, str]], output: pathlib.Path
) -> list[int]:
    by_candidate: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    rank: dict[str, tuple[int, str]] = {}
    for row in rows:
        candidate = row["entity_id"]
        by_candidate[candidate].append(row)
        rank[candidate] = (int(row["candidate_priority_rank"]), candidate)
    ordered = sorted(by_candidate, key=lambda candidate: rank[candidate])
    if len(ordered) != EXPECTED_CANDIDATES:
        raise RuntimeError("unexpected candidate count while sharding")
    halves = (ordered[:53], ordered[53:])
    counts: list[int] = []
    shard_dir = output / "manifests/shards_exact_2"
    for index, candidate_ids in enumerate(halves):
        shard_rows = [
            row
            for candidate in candidate_ids
            for row in by_candidate[candidate]
        ]
        counts.append(len(shard_rows))
        write_tsv(shard_dir / f"shard_{index:02d}.tsv", fields, shard_rows)
    if counts != [212, 212]:
        raise RuntimeError(f"unexpected shard counts: {counts}")
    return counts


def make_sha256sums(root: pathlib.Path) -> None:
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            records.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(records) + "\n")


def archive_project(project: pathlib.Path, archive: pathlib.Path) -> None:
    temporary = archive.with_name(f".{archive.name}.partial.{os.getpid()}")
    temporary.unlink(missing_ok=True)
    with tarfile.open(temporary, "w:gz", compresslevel=3) as handle:
        handle.add(project, arcname=project.name, recursive=True)
    os.replace(temporary, archive)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--completion-root",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data/qlyu/projects/pvrig_top7500_dualpanel_screen_v1_20260724/"
            "run/top200_seed_completion_v1"
        ),
    )
    parser.add_argument(
        "--template-root",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data1/qlyu/projects/pvrig_top7500_c2_gap_recovery_v1_20260723/"
            "c2_new4220_dualreceptor_seed42_3047_handoff_v1"
        ),
    )
    parser.add_argument(
        "--monomer-source-root",
        type=pathlib.Path,
        default=pathlib.Path(
            "/data1/qlyu/projects/"
            "pvrig_priority_top7500_dualreceptor_multiseed_handoff_v3_20260722/"
            "inputs/candidate_monomers"
        ),
    )
    parser.add_argument(
        "--output-parent",
        type=pathlib.Path,
        default=pathlib.Path("/data1/qlyu/projects"),
    )
    args = parser.parse_args()

    output = args.output_parent / PACKAGE_NAME
    building = args.output_parent / f".{PACKAGE_NAME}.building.{os.getpid()}"
    archive = args.output_parent / f"{PACKAGE_NAME}.tar.gz"
    external_manifest = args.output_parent / f"{PACKAGE_NAME}.manifest.tsv"
    external_ready = args.output_parent / f"{PACKAGE_NAME}.READY.json"
    aggregation_gate = (
        args.output_parent / f"{PACKAGE_NAME}.AGGREGATION_COMPLETE.json"
    )
    build_receipt = args.output_parent / f"{PACKAGE_NAME}.BUILD_RECEIPT.json"
    if output.exists() or archive.exists():
        raise RuntimeError(f"refusing to overwrite existing output: {output}")
    if building.exists():
        shutil.rmtree(building)
    building.mkdir(parents=True)

    source_manifest = (
        args.completion_root / "TOP200_MISSING_SEED_JOBS_RUNNABLE.tsv"
    )
    fields, rows = read_tsv(source_manifest)
    candidates = validate_matrix(rows)
    copy_static(args.template_root, building)
    monomers = copy_monomers(rows, args.monomer_source_root, building)

    (building / "manifests").mkdir(exist_ok=True)
    shutil.copy2(source_manifest, building / "manifests/docking_jobs.tsv")
    write_tsv(
        building / "manifests/docking_jobs_seed42.tsv",
        fields,
        [row for row in rows if row["seed"] == "42"],
    )
    write_tsv(
        building / "manifests/docking_jobs_seed3047.tsv",
        fields,
        [row for row in rows if row["seed"] == "3047"],
    )
    write_tsv(building / "manifests/smoke_jobs.tsv", fields, rows[:2])
    shard_counts = make_shards(fields, rows, building)

    for name in (
        "TOP200_NEEDS_SEED_COMPLETION_106.tsv",
        "TOP200_NEEDS_SEED_COMPLETION_106.fasta",
        "TOP200_COMMON4_SEED_COMPLETION_CANDIDATES.tsv",
    ):
        shutil.copy2(args.completion_root / name, building / "inputs" / name)
    for name in (
        "SEED_COMPLETION_MANIFEST_RECEIPT.json",
        "RUNNABLE_MANIFEST_VALIDATION.json",
    ):
        shutil.copy2(args.completion_root / name, building / "reports" / name)

    cfg_hashes: dict[str, dict[str, str]] = {}
    for seed in sorted(EXPECTED_SEEDS, key=int):
        cfg_hashes[seed] = {}
        for conformation in sorted(EXPECTED_CONFORMATIONS):
            values = {
                row["cfg_hash"]
                for row in rows
                if row["seed"] == seed
                and row["conformation"] == conformation
            }
            if len(values) != 1:
                raise RuntimeError(
                    f"cfg hash is not unique for {seed}/{conformation}"
                )
            cfg_hashes[seed][conformation] = next(iter(values))
    write_json(
        building / "config/TWO_SEED_CFG_LOCK.json",
        {
            "schema_version": "pvrig.top200.two_seed_cfg_lock.v1",
            "status": "LOCKED",
            "seeds": [42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "cfg_payloads": {
                seed: {
                    conformation: {
                        "cfg_hash": cfg_hashes[seed][conformation],
                        "ncores": 4,
                    }
                    for conformation in ("8x6b", "9e6y")
                }
                for seed in ("42", "3047")
            },
            "protocol_core_sha256": EXPECTED_PROTOCOL_CORE,
        },
    )

    manifest_sha = sha256(building / "manifests/docking_jobs.tsv")
    receipt = {
        "schema_version": "pvrig.top200.common4_seed_completion_handoff.v1",
        "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
        "package_name": PACKAGE_NAME,
        "docking_started": False,
        "launch_authority": (
            "NONE: package materialization only; scheduler submission is handled "
            "by the separately hash-gated bxcpu runtime."
        ),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "counts": {
            "candidates": EXPECTED_CANDIDATES,
            "jobs": EXPECTED_JOBS,
            "shards": 2,
            "jobs_per_shard": shard_counts,
            "unique_job_hashes": len({row["job_hash"] for row in rows}),
            "unique_monomer_hashes": len(set(monomers.values())),
            "unique_sequence_hashes": len(
                {row["sequence_sha256"] for row in rows}
            ),
        },
        "protocol": {
            "protocol_core_sha256": EXPECTED_PROTOCOL_CORE,
            "seeds": [42, 3047],
            "conformations": ["8x6b", "9e6y"],
            "cfg_hashes": cfg_hashes,
            "technical_failure_semantics": "NA_not_negative",
        },
        "outputs": {
            "job_manifest_sha256": manifest_sha,
            "candidate_manifest_sha256": sha256(
                building / "inputs/TOP200_NEEDS_SEED_COMPLETION_106.tsv"
            ),
        },
        "aggregation_dependency": {
            "state": "COMPLETE",
            "seed_completion_receipt_sha256": sha256(
                args.completion_root / "SEED_COMPLETION_MANIFEST_RECEIPT.json"
            ),
            "runnable_validation_sha256": sha256(
                args.completion_root / "RUNNABLE_MANIFEST_VALIDATION.json"
            ),
        },
        "claim_boundary": (
            "Computational docking geometry only; not binding, Kd, IC50, "
            "expression, purity, or experimental blocking."
        ),
    }
    write_json(building / "HANDOFF_RECEIPT.json", receipt)
    receipt_sha = sha256(building / "HANDOFF_RECEIPT.json")

    ready = {
        "schema_version": "pvrig.top200.common4_seed_completion_ready.v1",
        "status": "READY_FOR_EXTERNAL_DOCKING_SUBMISSION",
        "counts": {
            "candidates": EXPECTED_CANDIDATES,
            "jobs": EXPECTED_JOBS,
            "shards": 2,
            "jobs_per_shard": shard_counts,
        },
        "anchors": {
            "manifest_sha256": manifest_sha,
            "receipt_sha256": receipt_sha,
        },
        "protocol_core_sha256": EXPECTED_PROTOCOL_CORE,
        "seeds": [42, 3047],
        "conformations": ["8x6b", "9e6y"],
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(building / "READY.json", ready)
    write_json(
        building / "DOCKING_PLAN.json",
        {
            "schema_version": "pvrig.top200.common4_seed_completion_plan.v1",
            "status": "READY",
            "candidate_count": EXPECTED_CANDIDATES,
            "job_count": EXPECTED_JOBS,
            "seeds": [42, 3047],
            "receptors": ["8x6b", "9e6y"],
            "two_shard_job_counts": shard_counts,
            "node_layout": {
                "nodes": 2,
                "cpus_per_node": 64,
                "concurrent_jobs_per_node": 16,
                "cpus_per_job": 4,
            },
            "technical_failure_semantics": "NA_not_negative",
        },
    )
    (building / "DO_NOT_REBUILD_JOB_MANIFEST.md").write_text(
        "# 冻结清单\n\n"
        "必须直接使用 `manifests/docking_jobs.tsv`；不得重新生成 Job ID、"
        "cfg、AIR 或 seed。\n"
    )
    (building / "README_ZH.md").write_text(
        "# Top200 公共四 seed 补齐包\n\n"
        "- 候选：106\n"
        "- 补跑 seed：42、3047\n"
        "- 受体：8X6B、9E6Y\n"
        "- 作业：424\n"
        "- 分片：2 × 212\n\n"
        "技术失败必须记为 NA，不得当作负样本；Docking 结果仅表示计算几何代理。\n"
    )

    validation_output = (
        building / "reports/PROTOCOL_VALIDATION_CANDIDATE_ONLY.json"
    )
    subprocess.run(
        [
            "python3",
            str(building / "scripts/validate_protocol.py"),
            "--protocol",
            str(building / "config/protocol_spec.json"),
            "--jobs",
            str(building / "manifests/docking_jobs.tsv"),
            "--out",
            str(validation_output),
            "--expected-total-jobs",
            str(EXPECTED_JOBS),
        ],
        check=True,
    )
    validation = json.loads(validation_output.read_text())
    if validation.get("status") != "PASS":
        raise RuntimeError("candidate-only protocol validation did not pass")

    make_sha256sums(building)
    os.replace(building, output)
    shutil.copy2(output / "manifests/docking_jobs.tsv", external_manifest)
    shutil.copy2(output / "READY.json", external_ready)
    archive_project(output, archive)

    aggregation_payload = {
        "schema_version": "pvrig.current_aggregation_gate.v1",
        "status": "PASS_CURRENT_AGGREGATION_COMPLETE",
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "evidence": {
            "seed_completion_receipt": {
                "path": str(
                    args.completion_root
                    / "SEED_COMPLETION_MANIFEST_RECEIPT.json"
                ),
                "sha256": sha256(
                    args.completion_root
                    / "SEED_COMPLETION_MANIFEST_RECEIPT.json"
                ),
            },
            "runnable_validation": {
                "path": str(
                    args.completion_root / "RUNNABLE_MANIFEST_VALIDATION.json"
                ),
                "sha256": sha256(
                    args.completion_root
                    / "RUNNABLE_MANIFEST_VALIDATION.json"
                ),
            },
        },
        "counts": {"candidates": EXPECTED_CANDIDATES, "jobs": EXPECTED_JOBS},
    }
    write_json(aggregation_gate, aggregation_payload)
    final_receipt = {
        "schema_version": "pvrig.top200.seed_completion_build.v1",
        "status": "PASS_HASH_CLOSED_PACKAGE",
        "package_root": str(output),
        "archive": {
            "path": str(archive),
            "bytes": archive.stat().st_size,
            "sha256": sha256(archive),
        },
        "manifest": {
            "path": str(external_manifest),
            "sha256": sha256(external_manifest),
        },
        "ready": {
            "path": str(external_ready),
            "sha256": sha256(external_ready),
        },
        "handoff_receipt": {
            "path": str(output / "HANDOFF_RECEIPT.json"),
            "sha256": sha256(output / "HANDOFF_RECEIPT.json"),
        },
        "aggregation_gate": {
            "path": str(aggregation_gate),
            "sha256": sha256(aggregation_gate),
        },
        "counts": {
            "candidates": EXPECTED_CANDIDATES,
            "jobs": EXPECTED_JOBS,
            "shards": 2,
            "jobs_per_shard": shard_counts,
        },
    }
    write_json(build_receipt, final_receipt)
    print(json.dumps(final_receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
