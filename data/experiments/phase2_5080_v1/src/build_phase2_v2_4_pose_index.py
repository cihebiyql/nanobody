#!/usr/bin/env python3
"""Build an auditable V2.4 candidate-pose sidecar index.

The index records only candidate-specific pose provenance and validation status.
It verifies the selected candidate IDs, VHH chain A SHA256 identity, PVRIG chain B
identity, non-empty local PDB.gz top poses, and NBB2/geometry/HADDOCK run status.
It does not infer binding, blocking, or experimental activity.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DOCKING_ROOT = ROOT.parent / "docking/candidates/v2_4_top2"
DEFAULT_OUTPUT = ROOT / "experiments/phase2_5080_v1/data_splits/phase2_v2_4_candidate_pose_index.csv"
DEFAULT_AUDIT = ROOT / "experiments/phase2_5080_v1/audits/phase2_v2_4_candidate_pose_index.json"

SCHEMA_VERSION = "pvrig_vhh_phase2_v2_4_candidate_pose_index_v1"
EVIDENCE_BOUNDARY = "computational_pose_proxy_not_experimental_binding_or_blocker_claim"
PVRIG_CHAIN_B_EXPECTED_SHA256 = "957aff0c6a5a0f83c1bc4f137744cef872d6474eda4ad8e03325b0f5d63c7e4c"
OUTPUT_COLUMNS = [
    "schema_version",
    "candidate_id",
    "pose_id",
    "vhh_seq",
    "vhh_seq_sha256",
    "vhh_chain",
    "vhh_chain_a_exact_match",
    "pvrig_chain",
    "pvrig_chain_b_exact_match",
    "pvrig_chain_b_observed_sha256",
    "pvrig_chain_b_expected_sha256",
    "nbb2_status",
    "monomer_geometry_status",
    "monomer_ca_count",
    "haddock3_status",
    "haddock3_top_pose_pdb_gz_count_reported",
    "top_pose_pdb_gz_count_verified",
    "top_pose_paths_json",
    "top_pose_sha256_json",
    "top_pose_bytes_json",
    "haddock_best_model",
    "haddock_best_score",
    "haddock_best_cluster_id",
    "haddock_consensus_sum_of_ranks",
    "local_monomer",
    "local_haddock_top_dir",
    "remote_monomer",
    "remote_haddock_top_dir",
    "pose_index_status",
    "pose_index_notes",
    "pose_provenance_json",
    "evidence_boundary",
]


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "na", "n/a", "?", "."} else text


def normalize_sequence(value: Any) -> str:
    return "".join(ch for ch in clean(value).upper() if "A" <= ch <= "Z")


def sequence_sha256(sequence: Any) -> str:
    return hashlib.sha256(normalize_sequence(sequence).encode("ascii")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def read_tsv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty TSV: {path}")
    return pd.read_csv(path, sep="\t", dtype=str).fillna("")


def read_manifest(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Missing or empty candidate manifest: {path}")
    if path.suffix.lower() == ".json":
        return pd.DataFrame(json.loads(path.read_text(encoding="utf-8"))).fillna("")
    sep = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    return pd.read_csv(path, sep=sep, dtype=str).fillna("")


def ensure_unique(df: pd.DataFrame, key: str, label: str) -> None:
    if key not in df.columns:
        raise ValueError(f"{label} is missing required column {key}")
    duplicates = df.loc[df[key].astype(str).duplicated(), key].astype(str).tolist()
    if duplicates:
        raise ValueError(f"{label} has duplicate {key}: {duplicates[:5]}")


def truthy(value: Any) -> bool:
    return clean(value).lower() in {"true", "1", "yes", "y", "pass", "passed", "ok", "success"}


def nonempty_pdb_gz(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith(("ATOM  ", "HETATM")):
                    return True
    except OSError:
        return False
    return False


def top_pose_files(top_dir: Path) -> list[Path]:
    if not top_dir.exists():
        return []
    return sorted(path for path in top_dir.glob("*.pdb.gz") if path.is_file())


def load_score_tables(run_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    best: dict[str, str] = {}
    clustfcc = run_dir / "5_clustfcc/clustfcc.tsv"
    if clustfcc.exists() and clustfcc.stat().st_size > 0:
        with clustfcc.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        if rows:
            first = rows[0]
            best = {
                "model": clean(first.get("model_name")),
                "score": clean(first.get("score")),
                "cluster_id": clean(first.get("cluster_id")),
            }
    consensus: dict[str, str] = {}
    consensus_path = run_dir / "traceback/consensus.tsv"
    if consensus_path.exists() and consensus_path.stat().st_size > 0:
        with consensus_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        if rows:
            first = rows[0]
            consensus = {
                "model": clean(first.get("Model")),
                "sum_of_ranks": clean(first.get("Sum-of-Ranks")),
            }
    return best, consensus


def validation_lookup(sequence_validation: pd.DataFrame) -> dict[tuple[str, str, str], list[pd.Series]]:
    lookup: dict[tuple[str, str, str], list[pd.Series]] = {}
    for _, row in sequence_validation.iterrows():
        key = (clean(row.get("candidate_id")), clean(row.get("asset")), clean(row.get("chain")))
        lookup.setdefault(key, []).append(row)
    return lookup


def build_pose_index(docking_root: Path) -> pd.DataFrame:
    manifest_path = docking_root / "manifests/selected_candidates_manifest.json"
    run_status_path = docking_root / "reports/run_status.tsv"
    sequence_validation_path = docking_root / "reports/pdb_sequence_validation.tsv"

    manifest = read_manifest(manifest_path)
    run_status = read_tsv(run_status_path)
    sequence_validation = read_tsv(sequence_validation_path)
    ensure_unique(manifest, "candidate_id", "selected candidate manifest")
    ensure_unique(run_status, "candidate_id", "run status")

    validation = validation_lookup(sequence_validation)
    rows: list[dict[str, Any]] = []
    run_by_candidate = {clean(row["candidate_id"]): row for _, row in run_status.iterrows()}
    for _, candidate in manifest.sort_values("candidate_id", kind="stable").iterrows():
        candidate_id = clean(candidate.get("candidate_id"))
        if not candidate_id:
            raise ValueError("Selected candidate manifest contains an empty candidate_id")
        if candidate_id not in run_by_candidate:
            raise ValueError(f"Candidate {candidate_id} missing from run_status.tsv")
        status = run_by_candidate[candidate_id]
        if clean(status.get("candidate_id")) != candidate_id:
            raise ValueError(f"Candidate ID mismatch for {candidate_id}")

        expected_vhh_sha = clean(candidate.get("vhh_seq_sha256")).lower()
        observed_vhh_sha = clean(status.get("vhh_seq_sha256")).lower()
        top_dir = Path(clean(status.get("local_haddock_top_dir")))
        pose_paths = top_pose_files(top_dir)
        relpaths = [path.relative_to(docking_root).as_posix() if path.is_relative_to(docking_root) else str(path) for path in pose_paths]
        usable_pose_paths = [path for path in pose_paths if nonempty_pdb_gz(path)]

        vhh_rows = validation.get((candidate_id, "haddock_top_vhh_chainA", "A"), [])
        pvrig_rows = validation.get((candidate_id, "haddock_top_pvrig_chainB", "B"), [])
        vhh_exact = bool(vhh_rows) and all(
            truthy(row.get("exact_match")) and clean(row.get("observed_sha256")).lower() == expected_vhh_sha
            for row in vhh_rows
        )
        pvrig_exact = bool(pvrig_rows) and all(
            truthy(row.get("exact_match")) and clean(row.get("observed_sha256")).lower() == PVRIG_CHAIN_B_EXPECTED_SHA256
            for row in pvrig_rows
        )
        validation_relpaths = {clean(row.get("path")) for row in [*vhh_rows, *pvrig_rows]}
        pose_validation_complete = all(relpath in validation_relpaths for relpath in relpaths)

        best, consensus = load_score_tables(top_dir.parent)
        notes: list[str] = []
        if expected_vhh_sha != observed_vhh_sha:
            notes.append("candidate_vhh_sha_mismatch_between_manifest_and_run_status")
        if not vhh_exact:
            notes.append("vhh_chain_a_sequence_validation_failed")
        if not pvrig_exact:
            notes.append("pvrig_chain_b_sequence_validation_failed")
        if not pose_paths:
            notes.append("no_top_pose_pdb_gz_files")
        if len(usable_pose_paths) != len(pose_paths):
            notes.append("one_or_more_top_pose_pdb_gz_files_empty_or_unreadable")
        if not pose_validation_complete:
            notes.append("top_pose_sequence_validation_rows_incomplete")
        if not clean(status.get("haddock3_status")).lower().startswith("completed"):
            notes.append("haddock3_not_completed")
        if not clean(status.get("nbb2_status")).lower().startswith("completed"):
            notes.append("nbb2_not_completed")
        if not truthy(status.get("monomer_likely_sane_backbone")):
            notes.append("monomer_geometry_not_sane")

        row_status = "verified_pose_proxy" if not notes else "failed_validation"
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "candidate_id": candidate_id,
                "pose_id": clean(candidate.get("pose_id")),
                "vhh_seq": normalize_sequence(candidate.get("vhh_seq")),
                "vhh_seq_sha256": expected_vhh_sha,
                "vhh_chain": "A",
                "vhh_chain_a_exact_match": vhh_exact,
                "pvrig_chain": "B",
                "pvrig_chain_b_exact_match": pvrig_exact,
                "pvrig_chain_b_observed_sha256": clean(pvrig_rows[0].get("observed_sha256")).lower() if pvrig_rows else "",
                "pvrig_chain_b_expected_sha256": PVRIG_CHAIN_B_EXPECTED_SHA256,
                "nbb2_status": clean(status.get("nbb2_status")),
                "monomer_geometry_status": "sane_backbone" if truthy(status.get("monomer_likely_sane_backbone")) else "failed_or_unchecked",
                "monomer_ca_count": clean(status.get("monomer_ca_count")),
                "haddock3_status": clean(status.get("haddock3_status")),
                "haddock3_top_pose_pdb_gz_count_reported": clean(status.get("haddock3_top_pose_pdb_gz_count")),
                "top_pose_pdb_gz_count_verified": len(usable_pose_paths),
                "top_pose_paths_json": json_compact(relpaths),
                "top_pose_sha256_json": json_compact({path.name: file_sha256(path) for path in usable_pose_paths}),
                "top_pose_bytes_json": json_compact({path.name: path.stat().st_size for path in usable_pose_paths}),
                "haddock_best_model": best.get("model", ""),
                "haddock_best_score": best.get("score", ""),
                "haddock_best_cluster_id": best.get("cluster_id", ""),
                "haddock_consensus_sum_of_ranks": consensus.get("sum_of_ranks", ""),
                "local_monomer": clean(status.get("local_monomer")),
                "local_haddock_top_dir": clean(status.get("local_haddock_top_dir")),
                "remote_monomer": clean(status.get("remote_monomer")),
                "remote_haddock_top_dir": clean(status.get("remote_haddock_top_dir")),
                "pose_index_status": row_status,
                "pose_index_notes": ";".join(notes) if notes else "ok",
                "pose_provenance_json": json_compact(
                    {
                        "docking_root": str(docking_root),
                        "manifest": str(manifest_path),
                        "run_status": str(run_status_path),
                        "sequence_validation": str(sequence_validation_path),
                        "score_table": str(top_dir.parent / "5_clustfcc/clustfcc.tsv"),
                        "consensus_table": str(top_dir.parent / "traceback/consensus.tsv"),
                    }
                ),
                "evidence_boundary": EVIDENCE_BOUNDARY,
            }
        )
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if out["candidate_id"].duplicated().any():
        raise ValueError("Pose index contains duplicate candidate_id values")
    return out


def write_pose_index(docking_root: Path, output: Path, audit_json: Path | None = None) -> dict[str, Any]:
    index = build_pose_index(docking_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    index.to_csv(output, index=False)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "docking_root": str(docking_root),
        "output": str(output),
        "rows": int(len(index)),
        "verified_pose_proxy_rows": int((index["pose_index_status"] == "verified_pose_proxy").sum()),
        "failed_validation_rows": int((index["pose_index_status"] != "verified_pose_proxy").sum()),
        "evidence_boundary": EVIDENCE_BOUNDARY,
    }
    if audit_json is not None:
        audit_json.parent.mkdir(parents=True, exist_ok=True)
        audit_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docking-root", type=Path, default=DEFAULT_DOCKING_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    summary = write_pose_index(args.docking_root, args.output, args.audit_json)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
