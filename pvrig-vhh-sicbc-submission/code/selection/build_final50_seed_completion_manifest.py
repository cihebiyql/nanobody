#!/usr/bin/env python3
"""Build an auditable Final50 common-four-seed docking completion manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


CANONICAL_SEEDS = (42, 917, 1931, 3047)
CONFORMATIONS = ("8x6b", "9e6y")
SUCCESS_STATES = {"SUCCESS", "PASS", "COMPLETE", "COMPLETED"}


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(payload: Any) -> str:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def load_build_module(protocol_root: Path) -> ModuleType:
    scripts = protocol_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    path = scripts / "build_docking_jobs.py"
    spec = importlib.util.spec_from_file_location("seed_completion_build_jobs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import protocol builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_seeds(
    rows: list[dict[str, str]],
) -> tuple[dict[str, set[int]], dict[tuple[str, int, str], dict[str, str]]]:
    successful: dict[str, dict[int, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    jobs: dict[tuple[str, int, str], dict[str, str]] = {}
    for row in rows:
        candidate = row.get("candidate_id") or row.get("entity_id") or ""
        seed_text = str(row.get("seed", "")).strip()
        conformation = str(row.get("conformation", "")).lower()
        if (
            not candidate
            or not seed_text.isdigit()
            or conformation not in CONFORMATIONS
            or str(row.get("state", "")).upper() not in SUCCESS_STATES
        ):
            continue
        seed = int(seed_text)
        successful[candidate][seed].add(conformation)
        jobs[(candidate, seed, conformation)] = row
    complete = {
        candidate: {
            seed
            for seed, conformations in seed_rows.items()
            if conformations == set(CONFORMATIONS)
        }
        for candidate, seed_rows in successful.items()
    }
    return complete, jobs


def safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--final50", type=Path, required=True)
    parser.add_argument("--old-manifest", type=Path, required=True)
    parser.add_argument("--old-results", type=Path, required=True)
    parser.add_argument("--c2-results", type=Path, required=True)
    parser.add_argument("--protocol-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    final50 = read_tsv(args.final50)
    if len(final50) != 50 or len({row["candidate_id"] for row in final50}) != 50:
        raise ValueError("Final50 must contain 50 unique candidates")
    old_manifest = read_tsv(args.old_manifest)
    old_results = read_tsv(args.old_results)
    c2_results = read_tsv(args.c2_results)
    complete, existing_jobs = complete_seeds(old_results + c2_results)
    existing_job_ids = {
        row["job_id"] for row in old_results + c2_results if row.get("job_id")
    }

    templates: dict[tuple[str, str], dict[str, str]] = {}
    for row in old_manifest:
        if row.get("seed") == "917" and row.get("conformation") in CONFORMATIONS:
            templates[(row["entity_id"], row["conformation"])] = row

    protocol_root = args.protocol_root.resolve()
    module = load_build_module(protocol_root)
    old_env = getattr(module, "root")
    # The imported module resolves its project root from this environment variable.
    import os

    os.environ["PVRIG_PROJECT_ROOT"] = str(protocol_root)
    core_hash = module.protocol_core_sha256()

    candidate_rows: list[dict[str, Any]] = []
    runnable_rows: list[dict[str, Any]] = []
    user_job_rows: list[dict[str, Any]] = []
    fasta_rows: list[dict[str, str]] = []
    priority = 0

    for row in final50:
        candidate = row["candidate_id"]
        current = sorted(complete.get(candidate, set()))
        missing = sorted(set(CANONICAL_SEEDS) - set(current))
        extras = sorted(set(current) - set(CANONICAL_SEEDS))
        candidate_rows.append(
            {
                "candidate_id": candidate,
                "sequence": row["sequence"],
                "sequence_sha256": row["sequence_sha256"],
                "final_rank": row.get("final_rank", ""),
                "route": row.get("route", ""),
                "panel_membership": row.get("panel_membership", ""),
                "current_complete_seed_ids": ",".join(map(str, current)),
                "current_complete_seed_count": len(current),
                "canonical_seed_ids": ",".join(map(str, CANONICAL_SEEDS)),
                "missing_canonical_seed_ids": ",".join(map(str, missing)),
                "missing_seed_count": len(missing),
                "extra_noncanonical_seed_ids": ",".join(map(str, extras)),
                "required_new_job_count": len(missing) * len(CONFORMATIONS),
                "completion_status": (
                    "NEEDS_DOCKING" if missing else "COMMON4_ALREADY_COMPLETE"
                ),
            }
        )
        if not missing:
            continue
        fasta_rows.append({"candidate_id": candidate, "sequence": row["sequence"]})
        for seed in missing:
            for conformation in CONFORMATIONS:
                template = templates.get((candidate, conformation))
                if template is None:
                    raise ValueError(
                        f"old manifest template missing: {candidate} {conformation}"
                    )
                if template["sequence_sha256"] != row["sequence_sha256"]:
                    raise ValueError(f"sequence hash mismatch: {candidate}")
                cfg_text = module.render_cfg(conformation, seed, core_hash)
                cfg_hash = sha256_text(cfg_text)
                basis = json.loads(template["job_hash_basis"])
                basis["seed"] = seed
                basis["cfg_hash"] = cfg_hash
                basis_text = canonical_json(basis)
                job_hash = sha256_text(basis_text)
                job_id = (
                    f"CANDIDATE_{safe_id(candidate)}_{conformation}_"
                    f"s{seed}_{job_hash[:12]}"
                )
                if job_id in existing_job_ids:
                    raise ValueError(f"planned job already exists: {job_id}")
                priority += 1
                planned = dict(template)
                planned.update(
                    {
                        "job_id": job_id,
                        "priority": str(priority),
                        "seed": str(seed),
                        "cfg_hash": cfg_hash,
                        "job_hash": job_hash,
                        "job_hash_basis": basis_text,
                        "docking_stage": "FINAL50_COMMON4_SEED_COMPLETION",
                        "repeat_selection_rank": row.get("final_rank", ""),
                    }
                )
                runnable_rows.append(planned)
                user_job_rows.append(
                    {
                        "planned_job_id": job_id,
                        "candidate_id": candidate,
                        "sequence": row["sequence"],
                        "sequence_sha256": row["sequence_sha256"],
                        "final_rank": row.get("final_rank", ""),
                        "route": row.get("route", ""),
                        "current_complete_seed_ids": ",".join(map(str, current)),
                        "missing_seed": seed,
                        "conformation": conformation,
                        "template_job_id": template["job_id"],
                        "template_monomer_source": template["monomer_source"],
                        "template_receptor_pdb": template["receptor_pdb"],
                        "protocol_core_sha256": core_hash,
                        "cfg_hash": cfg_hash,
                        "job_hash": job_hash,
                        "status": "PLANNED_NOT_RUN",
                    }
                )

    if len(candidate_rows) != 50:
        raise AssertionError("candidate completion table is not 50 rows")
    needing = [row for row in candidate_rows if row["completion_status"] == "NEEDS_DOCKING"]
    if len(needing) != 28 or len(runnable_rows) != 112:
        raise AssertionError(
            f"expected 28 candidates/112 jobs, found {len(needing)}/{len(runnable_rows)}"
        )
    if len({row["job_id"] for row in runnable_rows}) != len(runnable_rows):
        raise AssertionError("duplicate planned job ID")

    args.out.mkdir(parents=True, exist_ok=True)
    candidate_path = args.out / "FINAL50_COMMON4_SEED_COMPLETION_CANDIDATES.tsv"
    user_jobs_path = args.out / "FINAL50_MISSING_SEED_JOBS.tsv"
    runnable_path = args.out / "FINAL50_MISSING_SEED_JOBS_RUNNABLE.tsv"
    fasta_path = args.out / "FINAL50_NEEDS_SEED_COMPLETION_28.fasta"
    receipt_path = args.out / "SEED_COMPLETION_MANIFEST_RECEIPT.json"
    readme_path = args.out / "README_ZH.md"

    candidate_fields = [
        "candidate_id", "sequence", "sequence_sha256", "final_rank", "route",
        "panel_membership", "current_complete_seed_ids",
        "current_complete_seed_count", "canonical_seed_ids",
        "missing_canonical_seed_ids", "missing_seed_count",
        "extra_noncanonical_seed_ids", "required_new_job_count",
        "completion_status",
    ]
    user_job_fields = [
        "planned_job_id", "candidate_id", "sequence", "sequence_sha256",
        "final_rank", "route", "current_complete_seed_ids", "missing_seed",
        "conformation", "template_job_id", "template_monomer_source",
        "template_receptor_pdb", "protocol_core_sha256", "cfg_hash",
        "job_hash", "status",
    ]
    runnable_fields = list(old_manifest[0])
    write_tsv(candidate_path, candidate_rows, candidate_fields)
    write_tsv(user_jobs_path, user_job_rows, user_job_fields)
    write_tsv(runnable_path, runnable_rows, runnable_fields)
    with fasta_path.open("w", encoding="ascii", newline="\n") as handle:
        for row in fasta_rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    readme_path.write_text(
        "# Final50统一四seed补跑清单\n\n"
        "共同seed集合固定为 `42,917,1931,3047`。只有缺失的"
        "candidate×seed×conformation组合需要运行；每个seed必须分别完成"
        "`8x6b`和`9e6y`两个构象。\n\n"
        "- Final50：50条；\n"
        "- 已满足共同四seed：22条；\n"
        "- 需要补跑：28条；\n"
        "- 缺失seed：所有待补候选均缺少42和3047；\n"
        "- 新增docking jobs：28×2 seeds×2 conformations＝112；\n"
        "- 9条已有额外seed 3253，该证据保留但不能替代共同seed集合。\n\n"
        "`FINAL50_MISSING_SEED_JOBS_RUNNABLE.tsv`沿用冻结HADDOCK3协议、"
        "monomer、受体、AIR restraint和protocol core hash，可作为补跑输入。"
        "本清单本身不表示这些jobs已经运行。\n",
        encoding="utf-8",
    )

    receipt = {
        "schema_version": "pvrig.final50.common4_seed_completion_manifest.v1",
        "state": "READY_NOT_RUN",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonical_seeds": list(CANONICAL_SEEDS),
        "conformations": list(CONFORMATIONS),
        "final50_count": 50,
        "already_complete_candidates": 22,
        "candidates_needing_completion": 28,
        "planned_job_count": 112,
        "planned_jobs_by_seed": {"42": 56, "3047": 56},
        "planned_jobs_by_conformation": {"8x6b": 56, "9e6y": 56},
        "candidates_with_extra_seed_3253": 9,
        "protocol_core_sha256": core_hash,
        "input_hashes": {
            str(args.final50): sha256_file(args.final50),
            str(args.old_manifest): sha256_file(args.old_manifest),
            str(args.old_results): sha256_file(args.old_results),
            str(args.c2_results): sha256_file(args.c2_results),
        },
        "output_hashes": {
            candidate_path.name: sha256_file(candidate_path),
            user_jobs_path.name: sha256_file(user_jobs_path),
            runnable_path.name: sha256_file(runnable_path),
            fasta_path.name: sha256_file(fasta_path),
            readme_path.name: sha256_file(readme_path),
        },
        "claim_boundary": (
            "This receipt proves a missing-seed plan only; no planned docking "
            "job is claimed complete."
        ),
    }
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
