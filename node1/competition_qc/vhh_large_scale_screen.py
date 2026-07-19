#!/usr/bin/env python3
"""Resumable cascade runner for large PVRIG VHH candidate libraries.

The runner keeps high-sensitivity blocker screening separate from competition
submission policy. It applies cheap hard gates to the full library, runs
AbNatiV/Sapiens/TNP only on survivors, and emits a bounded geometry shortlist.
No candidate becomes a final high-confidence blocker without imported
multi-baseline docking consensus evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shlex
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence

import vhh_competition_qc as qc


@dataclass(frozen=True)
class PreparedRecord:
    input_id: str
    canonical_id: str
    sequence: str
    sequence_sha256: str
    status: str
    reason: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fasta", type=Path)
    parser.add_argument("-o", "--outdir", type=Path, required=True)
    parser.add_argument(
        "--qc-bin",
        default="/data/qlyu/software/vhh_eval_tools/bin/vhh-competition-qc",
    )
    parser.add_argument(
        "--local-positive-cdr-csv",
        type=Path,
        default=Path("/data/qlyu/software/vhh_eval_tools/references/local_pvrig_positive_vhh_cdrs.csv"),
    )
    parser.add_argument("--stage", choices=["prepare", "fast", "full", "finalize", "all"], default="all")
    parser.add_argument("--fast-chunk-size", type=int, default=500)
    parser.add_argument("--full-chunk-size", type=int, default=100)
    parser.add_argument("--chunk-jobs", type=int, default=1)
    parser.add_argument("--full-chunk-jobs", type=int, default=1)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--tnp-ncores", type=int, default=4)
    parser.add_argument(
        "--full-run-tnp",
        action="store_true",
        help="Run TNP on the full shortlist; default defers it to final candidates.",
    )
    parser.add_argument("--identity-cache-size", type=int, default=200000)
    parser.add_argument(
        "--full-qc-limit",
        type=int,
        default=0,
        help="Maximum fast-stage survivors sent to full QC; 0 keeps all survivors.",
    )
    parser.add_argument("--geometry-limit", type=int, default=50)
    parser.add_argument("--geometry-pool-size", type=int, default=100)
    parser.add_argument("--geometry-cluster-limit", type=int, default=3)
    parser.add_argument("--skip-final-diversity", action="store_true")
    parser.add_argument("--cluster-identity", type=float, default=0.9)
    parser.add_argument("--muscle-bin", default="/data/qlyu/software/vhh_eval_tools/bin/muscle")
    parser.add_argument("--length-min", type=int, default=95)
    parser.add_argument("--length-max", type=int, default=160)
    parser.add_argument("--binder-summary", type=Path)
    parser.add_argument("--docking-summary", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.fast_chunk_size < 1 or args.full_chunk_size < 1:
        parser.error("chunk sizes must be >= 1")
    if args.chunk_jobs < 1 or args.full_chunk_jobs < 1 or args.workers < 1 or args.tnp_ncores < 1:
        parser.error("job/core counts must be >= 1")
    if args.full_qc_limit < 0 or args.geometry_limit < 1 or args.geometry_pool_size < args.geometry_limit:
        parser.error("full-qc-limit must be >= 0 and geometry-limit must be >= 1")
    if args.geometry_cluster_limit < 1:
        parser.error("geometry-cluster-limit must be >= 1")
    return args


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or not path.stat().st_size:
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def input_digest(records: list[qc.FastaRecord], args: argparse.Namespace) -> str:
    payload = {
        "records": [(record.name, record.sequence) for record in records],
        "length_min": args.length_min,
        "length_max": args.length_max,
        "fast_chunk_size": args.fast_chunk_size,
        "full_chunk_size": args.full_chunk_size,
        "full_qc_limit": args.full_qc_limit,
        "geometry_limit": args.geometry_limit,
        "geometry_pool_size": args.geometry_pool_size,
        "geometry_cluster_limit": args.geometry_cluster_limit,
        "skip_final_diversity": args.skip_final_diversity,
        "full_run_tnp": args.full_run_tnp,
    }
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def prepare_records(records: list[qc.FastaRecord], args: argparse.Namespace) -> list[PreparedRecord]:
    canonical_by_sequence: dict[str, str] = {}
    prepared: list[PreparedRecord] = []
    for record in records:
        sequence_hash = sha256_text(record.sequence)
        if not record.sequence or not set(record.sequence) <= qc.STANDARD_AA:
            status = "QUICK_REJECT"
            reason = "invalid_or_empty_sequence"
            canonical_id = record.name
        elif not args.length_min <= len(record.sequence) <= args.length_max:
            status = "QUICK_REJECT"
            reason = f"length_outside_{args.length_min}_{args.length_max}"
            canonical_id = record.name
        elif record.sequence in canonical_by_sequence:
            status = "DUPLICATE"
            reason = "exact_sequence_duplicate"
            canonical_id = canonical_by_sequence[record.sequence]
        else:
            status = "UNIQUE_READY"
            reason = ""
            canonical_id = record.name
            canonical_by_sequence[record.sequence] = canonical_id
        prepared.append(
            PreparedRecord(
                input_id=record.name,
                canonical_id=canonical_id,
                sequence=record.sequence,
                sequence_sha256=sequence_hash,
                status=status,
                reason=reason,
            )
        )
    return prepared


def chunked(items: list[qc.FastaRecord], size: int) -> list[list[qc.FastaRecord]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def write_chunks(root: Path, records: list[qc.FastaRecord], chunk_size: int) -> list[Path]:
    paths: list[Path] = []
    for index, chunk in enumerate(chunked(records, chunk_size), start=1):
        chunk_dir = root / f"chunk_{index:06d}"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        fasta = chunk_dir / "input.fasta"
        qc.write_fasta(fasta, chunk)
        paths.append(fasta)
    return paths


def prepare(args: argparse.Namespace) -> dict[str, object]:
    args.outdir.mkdir(parents=True, exist_ok=True)
    records = qc.parse_fasta(args.fasta)
    digest = input_digest(records, args)
    manifest_path = args.outdir / "cascade_manifest.json"
    if manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        if current.get("input_digest") != digest and not args.force:
            raise SystemExit(
                "Existing cascade_manifest.json was created for different input/config; "
                "use a new output directory or --force."
            )
    if args.force:
        for generated_dir in [args.outdir / "fast_chunks", args.outdir / "full_chunks"]:
            if generated_dir.exists():
                shutil.rmtree(generated_dir)
    prepared = prepare_records(records, args)
    unique = [qc.FastaRecord(row.canonical_id, row.sequence) for row in prepared if row.status == "UNIQUE_READY"]
    qc.write_fasta(args.outdir / "unique_candidates.fasta", unique)
    write_tsv(args.outdir / "input_map.tsv", [asdict(row) for row in prepared])
    write_tsv(
        args.outdir / "quick_rejects.tsv",
        [asdict(row) for row in prepared if row.status == "QUICK_REJECT"],
    )
    fast_chunks = write_chunks(args.outdir / "fast_chunks", unique, args.fast_chunk_size)
    manifest = {
        "schema_version": 1,
        "input_fasta": str(args.fasta),
        "input_digest": digest,
        "input_records": len(records),
        "unique_ready": len(unique),
        "duplicates": sum(row.status == "DUPLICATE" for row in prepared),
        "quick_rejects": sum(row.status == "QUICK_REJECT" for row in prepared),
        "fast_chunks": len(fast_chunks),
        "config": {
            "fast_chunk_size": args.fast_chunk_size,
            "full_chunk_size": args.full_chunk_size,
            "full_qc_limit": args.full_qc_limit,
            "geometry_limit": args.geometry_limit,
            "geometry_pool_size": args.geometry_pool_size,
            "geometry_cluster_limit": args.geometry_cluster_limit,
            "skip_final_diversity": args.skip_final_diversity,
            "full_run_tnp": args.full_run_tnp,
            "length_min": args.length_min,
            "length_max": args.length_max,
        },
    }
    write_json(manifest_path, manifest)
    update_state(args.outdir, "prepare", "complete", manifest)
    return manifest


def update_state(outdir: Path, stage: str, status: str, details: dict[str, object]) -> None:
    path = outdir / "cascade_state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"stages": {}}
    state.setdefault("stages", {})[stage] = {
        "status": status,
        "updated_epoch": time.time(),
        **details,
    }
    write_json(path, state)


def build_qc_command(args: argparse.Namespace, fasta: Path, outdir: Path, *, fast: bool) -> list[str]:
    command = [
        args.qc_bin,
        str(fasta),
        "-o",
        str(outdir),
        "--prefix",
        fasta.parent.name,
        "--workers",
        str(args.workers),
        "--tnp-ncores",
        str(args.tnp_ncores),
        "--identity-cache-size",
        str(args.identity_cache_size),
        "--gate-policy",
        "blocker_calibrated",
        "--skip-team-diversity",
        "--top-n",
        "100000000",
        "--reserve-n",
        "0",
    ]
    if args.local_positive_cdr_csv:
        command.extend(["--local-positive-cdr-csv", str(args.local_positive_cdr_csv)])
    if fast:
        command.extend(["--large-scale-fast"])
    elif not args.full_run_tnp:
        command.append("--skip-tnp")
    return command


def chunk_complete(fasta: Path, outdir: Path) -> bool:
    expected = len(qc.parse_fasta(fasta))
    rows = read_tsv(outdir / "portfolio_ranked.tsv")
    return expected > 0 and len(rows) == expected


def run_one_chunk(args: argparse.Namespace, fasta: Path, *, fast: bool) -> dict[str, object]:
    stage_name = "fast" if fast else "full"
    output = fasta.parent / "qc_out"
    marker = fasta.parent / "complete.json"
    if not args.force and marker.exists() and chunk_complete(fasta, output):
        return {"chunk": fasta.parent.name, "status": "reused", "elapsed_seconds": 0.0}
    command = build_qc_command(args, fasta, output, fast=fast)
    (fasta.parent / "command.sh").write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n" + shlex.join(command) + "\n",
        encoding="utf-8",
    )
    if args.plan_only:
        return {"chunk": fasta.parent.name, "status": "planned", "elapsed_seconds": 0.0}
    start = time.perf_counter()
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - start
    (fasta.parent / "runner.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (fasta.parent / "runner.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not chunk_complete(fasta, output):
        raise RuntimeError(
            f"{stage_name} chunk failed: {fasta.parent}; returncode={completed.returncode}"
        )
    result = {
        "chunk": fasta.parent.name,
        "status": "complete",
        "elapsed_seconds": round(elapsed, 3),
        "candidate_count": len(qc.parse_fasta(fasta)),
    }
    write_json(marker, result)
    return result


def run_chunk_stage(args: argparse.Namespace, *, fast: bool) -> list[dict[str, object]]:
    root = args.outdir / ("fast_chunks" if fast else "full_chunks")
    fastas = sorted(root.glob("chunk_*/input.fasta"))
    if not fastas:
        raise SystemExit(f"No chunk FASTAs found under {root}; run prepare/fast merge first.")
    stage_name = "fast" if fast else "full"
    update_state(args.outdir, stage_name, "running", {"chunks": len(fastas)})
    results: list[dict[str, object]] = []
    failures: list[str] = []
    stage_jobs = args.chunk_jobs if fast else args.full_chunk_jobs
    with ThreadPoolExecutor(max_workers=stage_jobs) as executor:
        futures = {executor.submit(run_one_chunk, args, fasta, fast=fast): fasta for fasta in fastas}
        for future in as_completed(futures):
            fasta = futures[future]
            try:
                results.append(future.result())
            except Exception as error:  # noqa: BLE001
                failures.append(f"{fasta.parent.name}: {error}")
    results.sort(key=lambda row: str(row["chunk"]))
    write_tsv(args.outdir / f"{stage_name}_chunk_status.tsv", results)
    if failures:
        update_state(args.outdir, stage_name, "failed", {"failures": failures})
        raise SystemExit("; ".join(failures))
    update_state(args.outdir, stage_name, "complete", {"chunks": len(results)})
    return results


def load_summary(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    rows = qc.read_csv_auto(path)
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = (
            row.get("candidate_id")
            or row.get("id")
            or row.get("name")
            or row.get("fasta_id")
            or row.get("molecule_name")
        )
        if candidate_id:
            output[candidate_id] = row
    return output


def binder_score(row: dict[str, str]) -> float:
    for key in [
        "binding_prior_consensus",
        "binder_score",
        "DeepNano_score",
        "deepnano_score",
        "binding_score",
        "score",
    ]:
        if str(row.get(key, "")).strip():
            return qc.parse_float(row[key], default=0.0)
    return 0.0


def merged_sort_key(row: dict[str, str]) -> tuple[bool, float, float, str]:
    return (
        row.get("hard_fail") == "True",
        -qc.parse_float(row.get("external_binder_score"), default=0.0),
        -qc.parse_float(row.get("final_score"), default=0.0),
        row.get("candidate_id", ""),
    )


def merge_chunk_portfolios(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in sorted(root.glob("chunk_*/qc_out/portfolio_ranked.tsv")):
        for row in read_tsv(path):
            candidate_id = row.get("candidate_id", "")
            if not candidate_id or candidate_id in seen:
                raise RuntimeError(f"Missing or duplicate candidate_id while merging: {candidate_id!r}")
            seen.add(candidate_id)
            rows.append(row)
    return rows


def annotate_binder(rows: list[dict[str, str]], summary: dict[str, dict[str, str]]) -> None:
    prior_fields = [
        "deepnano_binding_prior",
        "nabp_binding_prior",
        "nanobind_binding_prior",
        "nanobind_affinity_range",
        "binding_model_count",
        "binding_prior_consensus",
        "binding_model_disagreement",
        "binding_prior_status",
        "binding_prior_source",
    ]
    for row in rows:
        external = summary.get(row.get("candidate_id", ""), {})
        row["external_binder_score"] = f"{binder_score(external):.6f}" if external else ""
        row["external_binder_status"] = "AVAILABLE" if external else "NOT_PROVIDED"
        for field in prior_fields:
            row[field] = str(external.get(field, "")) if external else ""
        if external and not row["binding_prior_status"]:
            row["binding_prior_status"] = "LEGACY_SINGLE_SCORE"


def rows_to_fasta(path: Path, rows: Iterable[dict[str, str]]) -> None:
    qc.write_fasta(
        path,
        [qc.FastaRecord(row["candidate_id"], row.get("sequence", "")) for row in rows],
    )


def merge_fast(args: argparse.Namespace) -> list[dict[str, str]]:
    rows = merge_chunk_portfolios(args.outdir / "fast_chunks")
    annotate_binder(rows, load_summary(args.binder_summary))
    rows.sort(key=merged_sort_key)
    for rank, row in enumerate(rows, start=1):
        row["cascade_fast_rank"] = str(rank)
    write_tsv(args.outdir / "fast_merged.tsv", rows)
    survivors = [row for row in rows if row.get("hard_fail") != "True"]
    limit = args.full_qc_limit or len(survivors)
    shortlist = survivors[:limit]
    capped = survivors[limit:]
    rows_to_fasta(args.outdir / "full_qc_shortlist.fasta", shortlist)
    write_tsv(args.outdir / "full_qc_shortlist.tsv", shortlist)
    write_tsv(args.outdir / "full_qc_excluded_due_cap.tsv", capped)
    full_records = [qc.FastaRecord(row["candidate_id"], row.get("sequence", "")) for row in shortlist]
    write_chunks(args.outdir / "full_chunks", full_records, args.full_chunk_size)
    update_state(
        args.outdir,
        "merge_fast",
        "complete",
        {
            "merged": len(rows),
            "hard_pass": len(survivors),
            "full_shortlist": len(shortlist),
            "excluded_due_cap": len(capped),
        },
    )
    return shortlist


def select_geometry_with_diversity(
    args: argparse.Namespace,
    eligible: list[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    pool = eligible[: args.geometry_pool_size]
    if args.skip_final_diversity or len(pool) < 2:
        for index, row in enumerate(pool, start=1):
            row["global_diversity_status"] = "SKIPPED" if args.skip_final_diversity else "SINGLETON"
            row["global_intra_team_cluster_id"] = f"GLOBAL_{index:06d}"
            row["global_intra_team_cluster_size"] = "1"
            row["global_max_team_identity"] = ""
        return pool[: args.geometry_limit], pool[args.geometry_limit :]

    candidates = [
        {
            "id": row.get("candidate_id", ""),
            "sequence": row.get("sequence", ""),
            "imgt_cdr1": row.get("IMGT_CDR1", ""),
            "imgt_cdr2": row.get("IMGT_CDR2", ""),
            "imgt_cdr3": row.get("IMGT_CDR3", ""),
        }
        for row in pool
    ]
    diversity_args = argparse.Namespace(
        muscle_bin=args.muscle_bin,
        cluster_identity=args.cluster_identity,
    )
    team_rows, cluster_map, cluster_sizes = qc.compute_team_diversity(diversity_args, candidates)
    team_by_id = {row["candidate_id"]: row for row in team_rows}
    cluster_counts: dict[str, int] = {}
    selected: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    for row in pool:
        candidate_id = row.get("candidate_id", "")
        team = team_by_id.get(candidate_id, {})
        cluster_id = cluster_map.get(candidate_id, "")
        row["global_diversity_status"] = "COMPUTED_ON_GEOMETRY_POOL"
        row["global_intra_team_cluster_id"] = cluster_id
        row["global_intra_team_cluster_size"] = str(cluster_sizes.get(cluster_id, 1))
        row["global_max_team_identity"] = team.get("max_team_identity", "")
        row["global_nearest_team_neighbor"] = team.get("nearest_team_neighbor", "")
        used = cluster_counts.get(cluster_id, 0)
        if len(selected) < args.geometry_limit and used < args.geometry_cluster_limit:
            selected.append(row)
            cluster_counts[cluster_id] = used + 1
        else:
            excluded.append(row)
    return selected, excluded


def merge_full(args: argparse.Namespace) -> list[dict[str, str]]:
    rows = merge_chunk_portfolios(args.outdir / "full_chunks")
    annotate_binder(rows, load_summary(args.binder_summary))
    rows.sort(key=merged_sort_key)
    for rank, row in enumerate(rows, start=1):
        row["cascade_full_rank"] = str(rank)
    write_tsv(args.outdir / "full_merged.tsv", rows)
    eligible = [row for row in rows if row.get("hard_fail") != "True"]
    geometry, diversity_excluded = select_geometry_with_diversity(args, eligible)
    for rank, row in enumerate(geometry, start=1):
        row["geometry_rank"] = str(rank)
        row["geometry_status"] = "NEEDS_STRUCTURE_AND_DOCKING"
    write_tsv(args.outdir / "geometry_shortlist.tsv", geometry)
    write_tsv(args.outdir / "geometry_diversity_excluded.tsv", diversity_excluded)
    rows_to_fasta(args.outdir / "geometry_shortlist.fasta", geometry)
    update_state(
        args.outdir,
        "merge_full",
        "complete",
        {
            "merged": len(rows),
            "hard_pass": len(eligible),
            "geometry_pool": min(len(eligible), args.geometry_pool_size),
            "geometry_shortlist": len(geometry),
            "geometry_diversity_excluded": len(diversity_excluded),
        },
    )
    return geometry


def final_blocker_label(blocker_class: str) -> str:
    label = blocker_class.upper()
    if "CONSENSUS_BLOCKER_LIKE_A" in label:
        return "FINAL_POSITIVE_HIGH"
    if "SINGLE_BASELINE" in label or (
        "BLOCKER_LIKE_A" in label and "CONSENSUS_BLOCKER_LIKE_A" not in label
    ):
        return "FINAL_RECHECK_SINGLE_BASELINE"
    if "BLOCKER_PLAUSIBLE_B" in label:
        return "FINAL_POSITIVE_PLAUSIBLE"
    if "BINDER_LIKE_C" in label:
        return "FINAL_BINDER_NOT_BLOCKER"
    if "EVIDENCE" in label:
        return "FINAL_INSUFFICIENT_GEOMETRY"
    return "FINAL_INCOMPLETE_NEEDS_DOCKING"


def finalize(args: argparse.Namespace) -> list[dict[str, str]]:
    geometry = read_tsv(args.outdir / "geometry_shortlist.tsv")
    docking = load_summary(args.docking_summary)
    final_rows: list[dict[str, str]] = []
    for row in geometry:
        candidate_id = row.get("candidate_id", "")
        evidence = docking.get(candidate_id, {})
        blocker_class = (
            evidence.get("blocker_class")
            or evidence.get("top_model_consensus_class")
            or evidence.get("class")
            or "NOT_RUN"
        )
        merged = dict(row)
        merged["blocker_class"] = blocker_class
        merged["final_blocker_label"] = final_blocker_label(blocker_class)
        merged["docking_evidence_status"] = "IMPORTED" if evidence else "MISSING"
        for key in [
            "hotspot_overlap_count",
            "total_vhh_pvrl2_residue_pair_occlusion",
            "cdr3_pvrl2_residue_pair_occlusion",
            "cdr3_occlusion_fraction",
        ]:
            if key in evidence:
                merged[key] = evidence[key]
        final_rows.append(merged)
    priority = {
        "FINAL_POSITIVE_HIGH": 0,
        "FINAL_RECHECK_SINGLE_BASELINE": 1,
        "FINAL_POSITIVE_PLAUSIBLE": 2,
        "FINAL_BINDER_NOT_BLOCKER": 3,
        "FINAL_INSUFFICIENT_GEOMETRY": 4,
        "FINAL_INCOMPLETE_NEEDS_DOCKING": 5,
    }
    final_rows.sort(
        key=lambda row: (
            priority.get(row["final_blocker_label"], 99),
            qc.parse_int(row.get("geometry_rank"), default=10**9),
        )
    )
    for rank, row in enumerate(final_rows, start=1):
        row["final_rank"] = str(rank)
    write_tsv(args.outdir / "final_blocker_screen.tsv", final_rows)
    high = [row for row in final_rows if row["final_blocker_label"] == "FINAL_POSITIVE_HIGH"]
    rows_to_fasta(args.outdir / "final_positive_high.fasta", high)
    update_state(
        args.outdir,
        "finalize",
        "complete",
        {
            "geometry_candidates": len(final_rows),
            "docking_imported": sum(row["docking_evidence_status"] == "IMPORTED" for row in final_rows),
            "final_positive_high": len(high),
        },
    )
    return final_rows


def write_run_report(args: argparse.Namespace) -> None:
    state_path = args.outdir / "cascade_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    report = [
        "# Large-scale PVRIG VHH cascade run",
        "",
        f"Input: `{args.fasta}`",
        f"Output: `{args.outdir}`",
        "",
        "## Safety boundary",
        "",
        "- Fast/full sequence scores prioritize candidates but do not prove PVRIG-PVRL2 blocking.",
        "- Only `FINAL_POSITIVE_HIGH` has imported `CONSENSUS_BLOCKER_LIKE_A` geometry.",
        "- `FINAL_RECHECK_SINGLE_BASELINE` must be redocked or manually reviewed.",
        "- Exact duplicates are computed once and remain traceable in `input_map.tsv`.",
        "- Any `full_qc_excluded_due_cap.tsv` rows are capacity-deferred, not biological negatives.",
        "- O(N^2) team diversity is deferred from the full library and recomputed globally on the bounded geometry pool.",
        "- TNP is deferred by default because it is a developability annotation, not a blocker-biology hard gate.",
        "",
        "## Stage state",
        "",
        "```json",
        json.dumps(state, indent=2, sort_keys=True),
        "```",
    ]
    (args.outdir / "CASCADE_RUN_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.stage in {"prepare", "all"}:
        prepare(args)
    if args.stage in {"fast", "all"}:
        if not (args.outdir / "cascade_manifest.json").exists():
            prepare(args)
        run_chunk_stage(args, fast=True)
        if not args.plan_only:
            merge_fast(args)
    if args.stage in {"full", "all"} and not args.plan_only:
        if not (args.outdir / "full_qc_shortlist.fasta").exists():
            merge_fast(args)
        if qc.parse_fasta(args.outdir / "full_qc_shortlist.fasta"):
            run_chunk_stage(args, fast=False)
            merge_full(args)
        else:
            update_state(args.outdir, "full", "complete", {"chunks": 0, "reason": "no survivors"})
    if args.stage in {"finalize", "all"} and not args.plan_only:
        if (args.outdir / "geometry_shortlist.tsv").exists():
            finalize(args)
    write_run_report(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
