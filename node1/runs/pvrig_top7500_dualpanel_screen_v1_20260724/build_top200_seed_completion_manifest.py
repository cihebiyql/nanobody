#!/usr/bin/env python3
"""Build an auditable Top200 common-four-seed docking completion manifest."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_final50_seed_completion_manifest import (
    CANONICAL_SEEDS,
    CONFORMATIONS,
    canonical_json,
    complete_seeds,
    load_build_module,
    read_tsv,
    safe_id,
    sha256_file,
    sha256_text,
    write_tsv,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top200", type=Path, required=True)
    parser.add_argument("--old-manifest", type=Path, required=True)
    parser.add_argument("--old-results", type=Path, required=True)
    parser.add_argument("--c2-results", type=Path, required=True)
    parser.add_argument("--protocol-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    top200 = read_tsv(args.top200)
    if len(top200) != 200 or len({row["candidate_id"] for row in top200}) != 200:
        raise ValueError("Top200 must contain 200 unique candidates")

    old_manifest = read_tsv(args.old_manifest)
    old_results = read_tsv(args.old_results)
    c2_results = read_tsv(args.c2_results)
    complete, _ = complete_seeds(old_results + c2_results)
    existing_job_ids = {
        row["job_id"] for row in old_results + c2_results if row.get("job_id")
    }

    templates: dict[tuple[str, str], dict[str, str]] = {}
    for row in old_manifest:
        if row.get("seed") == "917" and row.get("conformation") in CONFORMATIONS:
            templates[(row["entity_id"], row["conformation"])] = row

    protocol_root = args.protocol_root.resolve()
    os.environ["PVRIG_PROJECT_ROOT"] = str(protocol_root)
    module = load_build_module(protocol_root)
    core_hash = module.protocol_core_sha256()

    candidate_rows: list[dict[str, object]] = []
    runnable_rows: list[dict[str, object]] = []
    user_job_rows: list[dict[str, object]] = []
    fasta_rows: list[dict[str, str]] = []
    priority = 0

    for row in sorted(top200, key=lambda item: int(item["top200_rank"])):
        candidate = row["candidate_id"]
        current = sorted(complete.get(candidate, set()))
        missing = sorted(set(CANONICAL_SEEDS) - set(current))
        extras = sorted(set(current) - set(CANONICAL_SEEDS))
        candidate_rows.append(
            {
                "candidate_id": candidate,
                "sequence": row["sequence"],
                "sequence_sha256": row["sequence_sha256"],
                "top200_rank": row["top200_rank"],
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
                        "docking_stage": "TOP200_COMMON4_SEED_COMPLETION",
                        "repeat_selection_rank": row["top200_rank"],
                    }
                )
                runnable_rows.append(planned)
                user_job_rows.append(
                    {
                        "planned_job_id": job_id,
                        "candidate_id": candidate,
                        "sequence": row["sequence"],
                        "sequence_sha256": row["sequence_sha256"],
                        "top200_rank": row["top200_rank"],
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

    needing = [
        row for row in candidate_rows if row["completion_status"] == "NEEDS_DOCKING"
    ]
    expected_jobs = sum(int(row["required_new_job_count"]) for row in needing)
    if len(runnable_rows) != expected_jobs:
        raise AssertionError(
            f"job count mismatch: expected {expected_jobs}, got {len(runnable_rows)}"
        )
    if len({row["job_id"] for row in runnable_rows}) != len(runnable_rows):
        raise AssertionError("duplicate planned job ID")

    args.out.mkdir(parents=True, exist_ok=True)
    candidate_path = args.out / "TOP200_COMMON4_SEED_COMPLETION_CANDIDATES.tsv"
    needing_path = args.out / f"TOP200_NEEDS_SEED_COMPLETION_{len(needing)}.tsv"
    user_jobs_path = args.out / "TOP200_MISSING_SEED_JOBS.tsv"
    runnable_path = args.out / "TOP200_MISSING_SEED_JOBS_RUNNABLE.tsv"
    fasta_path = args.out / f"TOP200_NEEDS_SEED_COMPLETION_{len(needing)}.fasta"
    receipt_path = args.out / "SEED_COMPLETION_MANIFEST_RECEIPT.json"
    readme_path = args.out / "README_ZH.md"

    candidate_fields = [
        "candidate_id",
        "sequence",
        "sequence_sha256",
        "top200_rank",
        "route",
        "panel_membership",
        "current_complete_seed_ids",
        "current_complete_seed_count",
        "canonical_seed_ids",
        "missing_canonical_seed_ids",
        "missing_seed_count",
        "extra_noncanonical_seed_ids",
        "required_new_job_count",
        "completion_status",
    ]
    user_job_fields = [
        "planned_job_id",
        "candidate_id",
        "sequence",
        "sequence_sha256",
        "top200_rank",
        "route",
        "current_complete_seed_ids",
        "missing_seed",
        "conformation",
        "template_job_id",
        "template_monomer_source",
        "template_receptor_pdb",
        "protocol_core_sha256",
        "cfg_hash",
        "job_hash",
        "status",
    ]
    runnable_fields = list(old_manifest[0])
    write_tsv(candidate_path, candidate_rows, candidate_fields)
    write_tsv(needing_path, needing, candidate_fields)
    write_tsv(user_jobs_path, user_job_rows, user_job_fields)
    write_tsv(runnable_path, runnable_rows, runnable_fields)
    with fasta_path.open("w", encoding="ascii", newline="\n") as handle:
        for row in fasta_rows:
            handle.write(f">{row['candidate_id']}\n{row['sequence']}\n")

    seed_counts = Counter(str(row["missing_seed"]) for row in user_job_rows)
    conformation_counts = Counter(str(row["conformation"]) for row in user_job_rows)
    extra_3253 = sum(
        "3253" in str(row["extra_noncanonical_seed_ids"]).split(",")
        for row in candidate_rows
    )
    readme_path.write_text(
        "# Top200统一四seed补跑清单\n\n"
        "共同seed集合固定为 `42,917,1931,3047`。只运行缺失的"
        "candidate×seed×conformation组合；每个seed必须分别完成"
        "`8x6b`和`9e6y`两个构象。\n\n"
        f"- Top200：{len(candidate_rows)}条；\n"
        f"- 已满足共同四seed：{len(candidate_rows) - len(needing)}条；\n"
        f"- 需要补跑：{len(needing)}条；\n"
        f"- 新增docking jobs：{len(runnable_rows)}个；\n"
        f"- 已有额外seed 3253的候选：{extra_3253}条；该证据保留，"
        "但不能替代共同seed集合。\n\n"
        "`TOP200_MISSING_SEED_JOBS_RUNNABLE.tsv`沿用冻结HADDOCK3协议、"
        "monomer、受体、AIR restraint和protocol core hash。"
        "本清单不表示这些jobs已经运行。\n",
        encoding="utf-8",
    )

    receipt = {
        "schema_version": "pvrig.top200.common4_seed_completion_manifest.v1",
        "state": "READY_NOT_RUN",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "canonical_seeds": list(CANONICAL_SEEDS),
        "conformations": list(CONFORMATIONS),
        "top200_count": len(candidate_rows),
        "already_complete_candidates": len(candidate_rows) - len(needing),
        "candidates_needing_completion": len(needing),
        "planned_job_count": len(runnable_rows),
        "planned_jobs_by_seed": dict(sorted(seed_counts.items())),
        "planned_jobs_by_conformation": dict(sorted(conformation_counts.items())),
        "candidates_with_extra_seed_3253": extra_3253,
        "protocol_core_sha256": core_hash,
        "input_hashes": {
            str(args.top200): sha256_file(args.top200),
            str(args.old_manifest): sha256_file(args.old_manifest),
            str(args.old_results): sha256_file(args.old_results),
            str(args.c2_results): sha256_file(args.c2_results),
        },
        "output_hashes": {
            candidate_path.name: sha256_file(candidate_path),
            needing_path.name: sha256_file(needing_path),
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
