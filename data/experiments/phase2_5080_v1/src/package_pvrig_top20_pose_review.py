#!/usr/bin/env python3
"""Package open-only V4-D Top20 poses for manual computational review.

Raw V4-D results are read only after every selected candidate has passed the
OPEN_TRAIN/OPEN_DEVELOPMENT split gate.  The resulting bundle is computational
pose-review material, not evidence of binding, affinity, competition, or
experimental blocking.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import shutil
import tarfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CLAIM_BOUNDARY = (
    "Computational pose review only; not evidence of binding, affinity, "
    "competition, blockade, or experimental blocking."
)
OPEN_SPLITS = {"OPEN_TRAIN", "OPEN_DEVELOPMENT"}
CONFORMATIONS = ("8x6b", "9e6y")
SEEDS = ("917", "1931", "3253")
REQUIRED_JOB_FIELDS = {
    "job_id", "entity_type", "entity_id", "conformation", "seed", "job_hash",
}
MANIFEST_FIELDS = (
    "candidate_id", "rank", "conformation", "seed", "job_id", "job_hash",
    "model", "HADDOCK_score", "geometry_8x6b_summary",
    "geometry_9e6y_summary", "source_sha256", "target_sha256",
    "bundle_relpath", "claim_boundary",
)


class ContractError(RuntimeError):
    """Raised when a V4-D pose-review contract is incomplete or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ContractError(f"Missing or empty table: {path}")
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        fields = list(reader.fieldnames or [])
        if not fields or len(fields) != len(set(fields)):
            raise ContractError(f"Invalid table header: {path}")
        rows = list(reader)
    if not rows:
        raise ContractError(f"Table has no rows: {path}")
    return fields, rows


def required_text(row: Mapping[str, Any], field: str) -> str:
    item = row.get(field)
    if item is None or str(item).strip() == "":
        raise ContractError(f"Missing {field}")
    return str(item).strip()


def safe_component(item: str, label: str) -> str:
    if not item or item in {".", ".."} or any(char in item for char in "/\\\x00"):
        raise ContractError(f"Unsafe {label}: {item!r}")
    return item


def finite_number(item: Any, label: str) -> int | float:
    if isinstance(item, bool):
        raise ContractError(f"Invalid numeric {label}: {item!r}")
    try:
        number = float(item)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"Invalid numeric {label}: {item!r}") from exc
    if not math.isfinite(number):
        raise ContractError(f"Non-finite numeric {label}: {item!r}")
    if number.is_integer():
        return int(number)
    return number


def nested(mapping: Mapping[str, Any], label: str, *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            raise ContractError(f"Missing {label}: {'.'.join(path)}")
        current = current[key]
    return current


def selected_open_rows(
    shortlist: Path, split_manifest: Path, expected_count: int,
) -> list[dict[str, str]]:
    _fields, shortlist_rows = read_table(shortlist)
    ranked: list[tuple[int, str, dict[str, str]]] = []
    for row in shortlist_rows:
        candidate_id = required_text(row, "candidate_id")
        safe_component(candidate_id, "candidate_id")
        try:
            rank = int(required_text(row, "rank"))
        except ValueError as exc:
            raise ContractError(f"Invalid rank for {candidate_id}") from exc
        if rank <= 0:
            raise ContractError(f"Non-positive rank for {candidate_id}")
        ranked.append((rank, candidate_id, row))
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = [row for _rank, _candidate, row in ranked[:expected_count]]
    if len(selected) != expected_count:
        raise ContractError(
            f"Expected {expected_count} shortlist candidates, found {len(selected)}"
        )
    identifiers = [row["candidate_id"] for row in selected]
    if len(set(identifiers)) != len(identifiers):
        raise ContractError("Top shortlist ranks contain duplicate candidate_id values")

    # This complete split gate intentionally precedes job-result path construction.
    _fields, split_rows = read_table(split_manifest)
    splits: dict[str, str] = {}
    for row in split_rows:
        candidate_id = required_text(row, "candidate_id")
        field = "model_split" if row.get("model_split") else "v4d_teacher_model_split"
        split = required_text(row, field).upper()
        if candidate_id in splits and splits[candidate_id] != split:
            raise ContractError(f"Conflicting split rows for {candidate_id}")
        splits[candidate_id] = split
    by_candidate = {row["candidate_id"]: row for row in selected}
    for candidate_id in identifiers:
        split = splits.get(candidate_id)
        if split is None:
            raise ContractError(f"Top candidate missing from split manifest: {candidate_id}")
        if split == "PROSPECTIVE_COMPUTATIONAL_TEST":
            raise ContractError(
                f"Refusing prospective computational test candidate: {candidate_id}"
            )
        if split not in OPEN_SPLITS:
            raise ContractError(
                f"Top candidate is not OPEN_TRAIN/OPEN_DEVELOPMENT: "
                f"{candidate_id} ({split})"
            )
        by_candidate[candidate_id]["_model_split"] = split
    return selected


def load_candidate_jobs(
    job_manifest: Path, candidate_ids: set[str],
) -> dict[tuple[str, str, str], dict[str, str]]:
    fields, rows = read_table(job_manifest)
    missing_fields = sorted(REQUIRED_JOB_FIELDS - set(fields))
    if missing_fields:
        raise ContractError(
            "Docking job manifest missing fields: " + ", ".join(missing_fields)
        )
    jobs: dict[tuple[str, str, str], dict[str, str]] = {}
    job_ids: set[str] = set()
    for row in rows:
        entity_id = required_text(row, "entity_id")
        if entity_id not in candidate_ids:
            continue
        entity_type = required_text(row, "entity_type").lower()
        if entity_type != "candidate":
            raise ContractError(
                f"Selected entity is not a candidate: {entity_id} ({entity_type})"
            )
        conformation = required_text(row, "conformation").lower()
        if conformation not in CONFORMATIONS:
            raise ContractError(f"Unsupported conformation: {conformation}")
        seed = required_text(row, "seed")
        if seed not in SEEDS:
            raise ContractError(f"Unsupported V4-D seed: {seed}")
        job_id = safe_component(required_text(row, "job_id"), "job_id")
        job_hash = required_text(row, "job_hash")
        key = (entity_id, conformation, seed)
        if key in jobs:
            raise ContractError(
                f"Duplicate job for {entity_id}/{conformation}/seed{seed}"
            )
        if job_id in job_ids:
            raise ContractError(f"Duplicate job_id among selected candidates: {job_id}")
        job_ids.add(job_id)
        jobs[key] = {
            "job_id": job_id,
            "job_hash": job_hash,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "conformation": conformation,
            "seed": seed,
        }
    expected = {
        (candidate_id, conformation, seed)
        for candidate_id in candidate_ids
        for conformation in CONFORMATIONS
        for seed in SEEDS
    }
    if set(jobs) != expected:
        missing = sorted("/".join(key) for key in expected - set(jobs))
        extra = sorted("/".join(key) for key in set(jobs) - expected)
        raise ContractError(
            f"Six-job closure failed; missing={missing}, extra={extra}"
        )
    return jobs


def clash_residue_pairs(score: Mapping[str, Any], pair: str) -> int | float:
    paths = (
        (f"{pair}_clashes_2p5a", "residue_pair_count"),
        (f"{pair}_clashes", "residue_pair_count"),
        ("clashes_2p5a", pair, "residue_pair_count"),
    )
    for path in paths:
        try:
            return finite_number(nested(score, f"{pair} residue-pair clashes", *path), f"{pair} residue-pair clashes")
        except ContractError:
            continue
    raise ContractError(f"Missing {pair} residue-pair clashes")


def compact_geometry(score: Mapping[str, Any]) -> dict[str, int | float | str]:
    reference_id = required_text(score, "reference_id").lower()
    if reference_id not in CONFORMATIONS:
        raise ContractError(f"Unsupported geometry reference_id: {reference_id}")
    return {
        "reference_id": reference_id,
        "hotspot_full_count": finite_number(
            nested(score, "hotspot full count", "hotspot_overlap", "full", "count"),
            "hotspot full count",
        ),
        "hotspot_anchor_count": finite_number(
            nested(score, "hotspot anchor count", "hotspot_overlap", "anchor", "count"),
            "hotspot anchor count",
        ),
        "hotspot_holdout_count": finite_number(
            nested(score, "hotspot holdout count", "hotspot_overlap", "holdout", "count"),
            "hotspot holdout count",
        ),
        "total_occlusion": finite_number(
            nested(score, "total occlusion", "vhh_pvrl2_occlusion", "residue_pair_count"),
            "total occlusion",
        ),
        "cdr3_occlusion": finite_number(
            nested(
                score, "CDR3 occlusion", "vhh_pvrl2_occlusion",
                "by_vhh_region_pair_count", "cdr3",
            ),
            "CDR3 occlusion",
        ),
        "cdr3_fraction": finite_number(
            nested(score, "CDR3 fraction", "vhh_pvrl2_occlusion", "cdr3_fraction"),
            "CDR3 fraction",
        ),
        "vhh_pvrig_clash_residue_pairs": clash_residue_pairs(score, "vhh_pvrig"),
        "vhh_pvrl2_clash_residue_pairs": clash_residue_pairs(score, "vhh_pvrl2"),
        "overlay_rmsd_a": finite_number(
            nested(score, "overlay RMSD", "overlay", "t_ca_rmsd_a"),
            "overlay RMSD",
        ),
    }


def source_pose(path_text: str, project_root: Path) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise ContractError(f"V4-D pose path is not absolute: {path_text}")
    root = project_root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"Pose path escapes project root: {path}") from exc
    if not path.is_file() or path.stat().st_size == 0:
        raise ContractError(f"Missing or empty pose: {path}")
    if not (path.name.endswith(".pdb.gz") or path.name.endswith(".pdb")):
        raise ContractError(f"Unsupported pose suffix: {path}")
    return path


def load_job_models(
    results_root: Path,
    project_root: Path,
    job: Mapping[str, str],
    models_per_job: int,
) -> list[dict[str, Any]]:
    result_path = results_root.resolve() / job["job_id"] / "job_result.json"
    if not result_path.is_file():
        raise ContractError(f"Missing fixed V4-D result path: {result_path}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Malformed job_result.json: {result_path}") from exc
    if not isinstance(payload, Mapping):
        raise ContractError(f"job_result.json is not an object: {result_path}")
    if required_text(payload, "state").upper() != "SUCCESS":
        raise ContractError(f"Job result is not SUCCESS: {job['job_id']}")
    if required_text(payload, "job_id") != job["job_id"]:
        raise ContractError(f"job_id mismatch for {job['job_id']}")
    if required_text(payload, "job_hash") != job["job_hash"]:
        raise ContractError(f"job_hash mismatch for {job['job_id']}")
    identity_fields = {
        "entity_type": job["entity_type"],
        "entity_id": job["entity_id"],
        "dock_conformation": job["conformation"],
        "seed": job["seed"],
    }
    for field, expected in identity_fields.items():
        if required_text(payload, field).lower() != expected.lower():
            raise ContractError(
                f"{field} identity mismatch for {job['job_id']}: "
                f"{payload.get(field)!r} != {expected!r}"
            )
    selected_count_raw = payload.get("selected_model_count")
    if isinstance(selected_count_raw, bool) or not isinstance(selected_count_raw, int):
        raise ContractError(f"Invalid selected_model_count for {job['job_id']}")
    pose_scores = payload.get("pose_scores")
    if not isinstance(pose_scores, list):
        raise ContractError(f"pose_scores is not a list for {job['job_id']}")
    if selected_count_raw != len(pose_scores):
        raise ContractError(
            f"selected_model_count mismatch for {job['job_id']}: "
            f"{selected_count_raw} != {len(pose_scores)}"
        )
    if selected_count_raw < models_per_job:
        raise ContractError(
            f"Job has fewer than {models_per_job} selected models: {job['job_id']}"
        )

    models: list[dict[str, Any]] = []
    pose_paths: set[Path] = set()
    model_names: set[str] = set()
    for index, raw in enumerate(pose_scores, start=1):
        if not isinstance(raw, Mapping):
            raise ContractError(f"Non-object pose_scores[{index}] for {job['job_id']}")
        pose = source_pose(required_text(raw, "pose"), project_root)
        if pose in pose_paths:
            raise ContractError(f"Duplicate pose path for {job['job_id']}: {pose}")
        pose_paths.add(pose)
        if pose.name in model_names:
            raise ContractError(f"Duplicate pose filename for {job['job_id']}: {pose.name}")
        model_names.add(pose.name)
        haddock_io = raw.get("haddock_io")
        if not isinstance(haddock_io, Mapping):
            raise ContractError(f"Missing haddock_io for {job['job_id']}/{pose.name}")
        haddock_score = finite_number(
            nested(haddock_io, "HADDOCK score", "score"), "HADDOCK score"
        )
        scores = raw.get("scores")
        if not isinstance(scores, list) or len(scores) != 2:
            raise ContractError(
                f"Expected scores[2] for {job['job_id']}/{pose.name}"
            )
        by_reference: dict[str, dict[str, int | float | str]] = {}
        for score in scores:
            if not isinstance(score, Mapping):
                raise ContractError(f"Non-object geometry score for {job['job_id']}")
            summary = compact_geometry(score)
            reference_id = str(summary["reference_id"])
            if reference_id in by_reference:
                raise ContractError(
                    f"Duplicate reference_id for {job['job_id']}/{pose.name}: {reference_id}"
                )
            by_reference[reference_id] = summary
        if set(by_reference) != set(CONFORMATIONS):
            raise ContractError(
                f"Incomplete 2x2 references for {job['job_id']}/{pose.name}"
            )
        models.append(
            {
                "model": pose.name,
                "source": pose,
                "haddock_score": haddock_score,
                "geometry_8x6b_summary": json.dumps(
                    by_reference["8x6b"], ensure_ascii=True,
                    separators=(",", ":"), sort_keys=True,
                ),
                "geometry_9e6y_summary": json.dumps(
                    by_reference["9e6y"], ensure_ascii=True,
                    separators=(",", ":"), sort_keys=True,
                ),
            }
        )
    return sorted(models, key=lambda model: (float(model["haddock_score"]), model["model"]))


def write_tsv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=MANIFEST_FIELDS, delimiter="\t",
            lineterminator="\n", extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


def write_sha256sums(outdir: Path) -> Path:
    output = outdir / "SHA256SUMS"
    excluded = {"SHA256SUMS", "pose_review_bundle.tar.gz"}
    paths = sorted(
        path for path in outdir.rglob("*")
        if path.is_file() and path.name not in excluded
    )
    output.write_text(
        "".join(
            f"{sha256_file(path)}  {path.relative_to(outdir).as_posix()}\n"
            for path in paths
        ),
        encoding="ascii",
    )
    return output


def write_archive(outdir: Path) -> Path:
    archive = outdir / "pose_review_bundle.tar.gz"
    with archive.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as bundle:
                for path in sorted(outdir.rglob("*")):
                    if path.is_file() and path != archive:
                        arcname = path.relative_to(outdir).as_posix()
                        info = bundle.gettarinfo(str(path), arcname=arcname)
                        info.mtime = 0
                        with path.open("rb") as handle:
                            bundle.addfile(info, handle)
    return archive


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shortlist", type=Path, required=True)
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument("--job-manifest", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument(
        "--project-root", type=Path,
        help="V4-D project root; defaults to results-root.parent.",
    )
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=20)
    parser.add_argument("--models-per-job", type=int, default=4)
    parser.add_argument("--poses-per-job", type=int, default=3)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if (
        args.expected_count <= 0
        or args.models_per_job < 4
        or args.poses_per_job != 3
        or args.poses_per_job > args.models_per_job
    ):
        raise ContractError(
            "expected-count > 0, models-per-job >= 4, and poses-per-job = 3 are required"
        )
    if args.outdir.exists() and any(args.outdir.iterdir()):
        raise ContractError(f"Refusing to overwrite non-empty outdir: {args.outdir}")
    project_root = (args.project_root or args.results_root.parent).resolve()
    results_root = args.results_root.resolve()
    try:
        results_root.relative_to(project_root)
    except ValueError as exc:
        raise ContractError("results-root must be inside project-root") from exc

    selected = selected_open_rows(
        args.shortlist, args.split_manifest, args.expected_count
    )
    ranks = {row["candidate_id"]: row["rank"] for row in selected}
    jobs = load_candidate_jobs(args.job_manifest, set(ranks))

    # Validate all 6 * N raw jobs and source poses before creating the output tree.
    prepared: list[
        tuple[tuple[str, str, str], dict[str, str], list[dict[str, Any]]]
    ] = []
    for key in sorted(jobs):
        job = jobs[key]
        models = load_job_models(
            results_root, project_root, job, args.models_per_job
        )
        prepared.append((key, job, models[: args.poses_per_job]))

    args.outdir.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict[str, str]] = []
    for (candidate_id, conformation, seed), job, models in prepared:
        destination_dir = args.outdir / candidate_id / conformation / seed
        destination_dir.mkdir(parents=True, exist_ok=True)
        for model in models:
            destination = destination_dir / model["model"]
            shutil.copyfile(model["source"], destination)
            source_hash = sha256_file(model["source"])
            target_hash = sha256_file(destination)
            if source_hash != target_hash:
                raise ContractError(f"Copy hash mismatch: {destination}")
            manifest_rows.append(
                {
                    "candidate_id": candidate_id,
                    "rank": ranks[candidate_id],
                    "conformation": conformation,
                    "seed": seed,
                    "job_id": job["job_id"],
                    "job_hash": job["job_hash"],
                    "model": model["model"],
                    "HADDOCK_score": str(model["haddock_score"]),
                    "geometry_8x6b_summary": model["geometry_8x6b_summary"],
                    "geometry_9e6y_summary": model["geometry_9e6y_summary"],
                    "source_sha256": source_hash,
                    "target_sha256": target_hash,
                    "bundle_relpath": destination.relative_to(args.outdir).as_posix(),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
    manifest_rows.sort(
        key=lambda row: (
            int(row["rank"]), row["conformation"], int(row["seed"]),
            float(row["HADDOCK_score"]), row["model"],
        )
    )
    manifest_path = args.outdir / "pose_review_manifest.tsv"
    write_tsv(manifest_path, manifest_rows)
    audit = {
        "schema_version": "pvrig_top20_pose_review_bundle_v2",
        "status": "PASS_OPEN_ONLY_V4D_POSE_REVIEW",
        "claim_boundary": CLAIM_BOUNDARY,
        "expected_candidate_count": args.expected_count,
        "candidate_count": len(ranks),
        "required_conformations": list(CONFORMATIONS),
        "required_seeds": [int(seed) for seed in SEEDS],
        "required_jobs_per_candidate": 6,
        "successful_job_count": len(jobs),
        "models_per_job_minimum": args.models_per_job,
        "poses_per_job": args.poses_per_job,
        "manifest_pose_count": len(manifest_rows),
        "project_root": str(project_root),
        "results_root": str(results_root),
        "input_sha256": {
            "packager": sha256_file(Path(__file__).resolve()),
            "shortlist": sha256_file(args.shortlist),
            "split_manifest": sha256_file(args.split_manifest),
            "job_manifest": sha256_file(args.job_manifest),
        },
        "split_counts": dict(
            sorted(Counter(row["_model_split"] for row in selected).items())
        ),
        "outputs": {
            "manifest": manifest_path.name,
            "audit": "pose_review_audit.json",
            "sha256sums": "SHA256SUMS",
            "archive": "pose_review_bundle.tar.gz",
        },
    }
    audit_path = args.outdir / "pose_review_audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_sha256sums(args.outdir)
    write_archive(args.outdir)
    return audit


def main(argv: Sequence[str] | None = None) -> int:
    audit = run(parse_args(argv))
    print(json.dumps(audit, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
