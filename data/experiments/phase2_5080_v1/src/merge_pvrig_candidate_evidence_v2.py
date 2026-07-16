#!/usr/bin/env python3
"""Merge release-safe V4-D and deep-QC evidence into the 418-row v2 master.

This is a lineage-preserving update: it never derives binding, affinity, or
blocking claims from QC/structure checks.  The prospective V4-D test split is
sealed even when all other optional evidence is supplied.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DEFAULT_INPUT = EXP_DIR / "prepared/pvrig_candidate_evidence_master_v1/candidate_evidence_master.tsv"
DEFAULT_SPLIT = EXP_DIR / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv"
DEFAULT_OUTDIR = EXP_DIR / "prepared/pvrig_candidate_evidence_master_v2"
EXPECTED_ROWS = 418
EXPECTED_FULLQC_OPEN = 258
SEALED_STATUS = "SEALED_PROSPECTIVE_TEST_NOT_RELEASED"
CLAIM_BOUNDARY = (
    "V2 merges computational geometry and structural/QC provenance only; it does not "
    "report binder probability, affinity/Kd, competition, or experimental blocking."
)

# These additive columns make an absent optional input visible without overwriting
# a v1 fact or turning a structure/QC check into a biological claim.
V2_FIELDS = (
    "v4d_teacher_merge_status", "v4d_teacher_model_split",
    "tnp_merge_status", "tnp_psh", "tnp_ppc", "tnp_pnc",
    "igfold_merge_status", "igfold_coverage", "igfold_path", "igfold_status",
    "nbb2_merge_status", "nbb2_crosscheck_status",
    "igfold_nbb2_common_framework_ca_count", "igfold_nbb2_framework_ca_rmsd",
    "igfold_nbb2_cdr3_anchor_distance_delta",
)
TEACHER_FIELDS = {
    "r_8x6b": ("R_8X6B", "r_8x6b"),
    "r_9e6y": ("R_9E6Y", "r_9e6y"),
    "r_dual_mean": ("R_dual_mean", "r_dual_mean"),
    "r_dual_min": ("R_dual_min", "r_dual_min"),
    "r_dual_gap": ("R_dual_gap", "r_dual_gap"),
    "geometry_uncertainty": ("geometry_uncertainty", "seed_uncertainty", "teacher_uncertainty"),
    "native_cross_agreement": ("native_cross_support_agreement_mean", "native_cross_agreement"),
    "model_pair_consensus": ("model_pair_consensus_fraction_mean", "model_pair_consensus"),
    "successful_seeds_8x6b": ("successful_seed_count_8X6B", "successful_seeds_8x6b"),
    "successful_seeds_9e6y": ("successful_seed_count_9E6Y", "successful_seeds_9e6y"),
}


class MergeError(ValueError):
    """Raised when an input would break candidate identity or split sealing."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter_for(path)))


def index_rows(rows: Iterable[dict[str, str]], source: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id", row.get("id", "")).strip()
        if not candidate_id:
            raise MergeError(f"{source}:candidate_id_missing")
        if candidate_id in indexed:
            raise MergeError(f"{source}:duplicate_candidate_id:{candidate_id}")
        indexed[candidate_id] = row
    return indexed


def first_value(row: dict[str, str], names: Sequence[str]) -> str:
    for name in names:
        value = row.get(name, "")
        if value not in (None, ""):
            return str(value)
    return ""


def geometry_uncertainty(source: dict[str, str], candidate_id: str) -> str:
    """Use a supplied aggregate uncertainty or the teacher's two seed SDs."""
    direct = first_value(source, TEACHER_FIELDS["geometry_uncertainty"])
    if direct:
        return direct
    values = [
        first_value(source, ("seed_sd_8X6B", "seed_sd_8x6b")),
        first_value(source, ("seed_sd_9E6Y", "seed_sd_9e6y")),
    ]
    if not all(values):
        raise MergeError(f"v4d_teacher:required_metric_missing:geometry_uncertainty:{candidate_id}")
    try:
        parsed = [float(value) for value in values]
    except ValueError as exc:
        raise MergeError(f"v4d_teacher:invalid_seed_sd:{candidate_id}") from exc
    if not all(math.isfinite(value) and value >= 0.0 for value in parsed):
        raise MergeError(f"v4d_teacher:invalid_seed_sd:{candidate_id}")
    return f"{sum(parsed) / len(parsed):.9g}"


def verify_optional_identity(
    evidence: dict[str, dict[str, str]], master: dict[str, dict[str, str]], source: str,
) -> None:
    unknown = sorted(set(evidence) - set(master))
    if unknown:
        raise MergeError(f"{source}:unknown_candidate_id:{unknown[0]}")
    for candidate_id, row in evidence.items():
        expected = master[candidate_id]
        evidence_hash = first_value(row, ("sequence_sha256", "sequence_hash"))
        if evidence_hash and evidence_hash != expected["sequence_sha256"]:
            raise MergeError(f"{source}:sequence_hash_mismatch:{candidate_id}")
        sequence = first_value(row, ("sequence", "vhh_sequence"))
        if sequence and sequence != expected["sequence"]:
            raise MergeError(f"{source}:sequence_mismatch:{candidate_id}")


def read_optional(path: Path | None, master: dict[str, dict[str, str]], label: str) -> dict[str, dict[str, str]]:
    if path is None:
        return {}
    if not path.is_file():
        raise MergeError(f"{label}:not_a_file:{path}")
    evidence = index_rows(read_rows(path), label)
    verify_optional_identity(evidence, master, label)
    return evidence


def merge_v4d_teacher(
    rows: list[dict[str, str]], split: dict[str, dict[str, str]], teacher: dict[str, dict[str, str]],
) -> None:
    fullqc = {row["candidate_id"]: row for row in rows if row["source_cohort"] == "FULLQC290_PRIMARY"}
    if set(fullqc) != set(split):
        raise MergeError("v4d_split:does_not_close_fullqc290_ids")
    open_ids = {candidate_id for candidate_id, row in split.items() if row.get("model_split") in {"OPEN_TRAIN", "OPEN_DEVELOPMENT"}}
    test_ids = {candidate_id for candidate_id, row in split.items() if row.get("model_split") == "PROSPECTIVE_COMPUTATIONAL_TEST"}
    if len(open_ids) != EXPECTED_FULLQC_OPEN or len(test_ids) != 32:
        raise MergeError(f"v4d_split:expected_258_open_and_32_test_got:{len(open_ids)}:{len(test_ids)}")
    if teacher:
        leaked = sorted(set(teacher) & test_ids)
        if leaked:
            raise MergeError(f"v4d_teacher:sealed_test_id_present:{leaked[0]}")
        if set(teacher) != open_ids:
            missing = sorted(open_ids - set(teacher))
            extra = sorted(set(teacher) - open_ids)
            raise MergeError(f"v4d_teacher:must_exactly_cover_258_open_ids:missing={missing[:1]}:extra={extra[:1]}")
    for candidate_id, row in fullqc.items():
        split_name = split[candidate_id]["model_split"]
        row["v4d_teacher_model_split"] = split_name
        if candidate_id in test_ids:
            row["geometry_status"] = SEALED_STATUS
            row["v4d_teacher_merge_status"] = SEALED_STATUS
            continue
        if not teacher:
            row["geometry_status"] = "PENDING_V4D_OPEN_TEACHER_INPUT"
            row["v4d_teacher_merge_status"] = "PENDING_V4D_OPEN_TEACHER_INPUT"
            continue
        source = teacher[candidate_id]
        for target, aliases in TEACHER_FIELDS.items():
            if target == "geometry_uncertainty":
                row[target] = geometry_uncertainty(source, candidate_id)
                continue
            value = first_value(source, aliases)
            if not value:
                raise MergeError(f"v4d_teacher:required_metric_missing:{target}:{candidate_id}")
            row[target] = value
        row["geometry_status"] = "OPEN_AVAILABLE_V4D_COMPUTATIONAL_GEOMETRY"
        row["v4d_teacher_merge_status"] = "MERGED_OPEN_TEACHER_258"


def merge_tnp(rows: list[dict[str, str]], evidence: dict[str, dict[str, str]]) -> None:
    for row in rows:
        source = evidence.get(row["candidate_id"])
        if source is None:
            row["tnp_merge_status"] = "PENDING_TNP_SUMMARY_INPUT" if not evidence else "PENDING_TNP_ROW_NOT_SUPPLIED"
            continue
        flags = first_value(source, ("tnp_flags", "TNP_flags", "flags"))
        if not flags:
            flag_fields = ("tnp_L_flag", "tnp_L3_flag", "tnp_C_flag", "tnp_PSH_flag", "tnp_PPC_flag", "tnp_PNC_flag")
            flags = ";".join(
                f"{field.removeprefix('tnp_')}={source[field]}"
                for field in flag_fields if source.get(field, "")
            )
        row["tnp_flags"] = flags
        row["tnp_psh"] = first_value(source, ("PSH", "psh", "tnp_psh", "tnp_PSH"))
        row["tnp_ppc"] = first_value(source, ("PPC", "ppc", "tnp_ppc", "tnp_PPC"))
        row["tnp_pnc"] = first_value(source, ("PNC", "pnc", "tnp_pnc", "tnp_PNC"))
        row["tnp_status"] = first_value(source, ("tnp_status", "L3_developability", "final_verdict", "status")) or "AVAILABLE_TNP_QC"
        row["tnp_merge_status"] = "MERGED_TNP_QC_ONLY"


def merge_igfold(rows: list[dict[str, str]], evidence: dict[str, dict[str, str]]) -> None:
    for row in rows:
        source = evidence.get(row["candidate_id"])
        if source is None:
            row["igfold_merge_status"] = "PENDING_IGFOLD_SUMMARY_INPUT" if not evidence else "PENDING_IGFOLD_ROW_NOT_SUPPLIED"
            continue
        row["igfold_coverage"] = first_value(source, ("igfold_coverage", "coverage", "coverage_fraction"))
        row["igfold_path"] = first_value(source, ("igfold_path", "path", "output_path", "pdb_path"))
        row["igfold_status"] = first_value(source, ("igfold_status", "L4_structure_stability", "final_verdict", "status")) or "AVAILABLE"
        row["igfold_merge_status"] = "MERGED_IGFOLD_STRUCTURE_QC_ONLY"


def merge_nbb2(rows: list[dict[str, str]], evidence: dict[str, dict[str, str]]) -> None:
    for row in rows:
        source = evidence.get(row["candidate_id"])
        if source is None:
            row["nbb2_merge_status"] = "PENDING_NBB2_AUDIT_INPUT" if not evidence else "PENDING_NBB2_ROW_NOT_SUPPLIED"
            continue
        status = first_value(source, ("nbb2_crosscheck_status", "crosscheck_status", "status")) or "AVAILABLE"
        row["nbb2_crosscheck_status"] = status
        row["nbb2_merge_status"] = "MERGED_NBB2_STRUCTURE_CROSSCHECK_ONLY"
        row["structure_crosscheck_status"] = status
        row["igfold_nbb2_common_framework_ca_count"] = first_value(
            source, ("common_framework_ca_count", "igfold_nbb2_common_framework_ca_count")
        )
        row["igfold_nbb2_framework_ca_rmsd"] = first_value(
            source, ("framework_ca_rmsd", "igfold_nbb2_framework_ca_rmsd")
        )
        row["igfold_nbb2_cdr3_anchor_distance_delta"] = first_value(
            source, ("cdr3_anchor_distance_delta", "igfold_nbb2_cdr3_anchor_distance_delta")
        )


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def write_sha256s(path: Path, files: Sequence[Path]) -> None:
    path.write_text("".join(f"{sha256_file(file)}  {file.name}\n" for file in files), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    base_rows = read_rows(args.input)
    if not base_rows:
        raise MergeError("master:empty")
    fields = list(base_rows[0])
    if "candidate_id" not in fields or "sequence" not in fields or "sequence_sha256" not in fields:
        raise MergeError("master:required_identity_columns_missing")
    rows = [dict(row) for row in base_rows]
    master = index_rows(rows, "master")
    if len(rows) != EXPECTED_ROWS or len(master) != EXPECTED_ROWS:
        raise MergeError(f"master:expected_418_unique_rows_got:{len(rows)}:{len(master)}")
    for row in rows:
        if sha256_text(row["sequence"]) != row["sequence_sha256"]:
            raise MergeError(f"master:sequence_hash_mismatch:{row['candidate_id']}")
    if len({row["sequence_sha256"] for row in rows}) != EXPECTED_ROWS:
        raise MergeError("master:sequence_sha256_not_unique")
    for field in V2_FIELDS:
        if field not in fields:
            fields.append(field)
        for row in rows:
            row.setdefault(field, "")

    split = index_rows(read_rows(args.v4d_split), "v4d_split")
    verify_optional_identity(split, master, "v4d_split")
    teacher = read_optional(args.v4d_open_teacher, master, "v4d_teacher")
    tnp = read_optional(args.tnp_summary, master, "tnp_summary")
    igfold = read_optional(args.igfold_summary, master, "igfold_summary")
    nbb2 = read_optional(args.igfold_nbb2_audit, master, "igfold_nbb2_audit")
    merge_v4d_teacher(rows, split, teacher)
    merge_tnp(rows, tnp)
    merge_igfold(rows, igfold)
    merge_nbb2(rows, nbb2)

    args.outdir.mkdir(parents=True, exist_ok=True)
    master_path = args.outdir / "candidate_evidence_master.tsv"
    schema_path = args.outdir / "candidate_evidence_schema.json"
    audit_path = args.outdir / "candidate_evidence_lineage_audit.json"
    sums_path = args.outdir / "SHA256SUMS"
    write_tsv(master_path, fields, rows)
    schema = {
        "schema_version": "pvrig_candidate_evidence_master_v2",
        "primary_key": "candidate_id", "sequence_identity_key": "sequence_sha256",
        "row_count_required": EXPECTED_ROWS, "field_count": len(fields),
        "v2_additive_fields": list(V2_FIELDS),
        "v4d_open_policy": {"open_rows": EXPECTED_FULLQC_OPEN, "sealed_test_rows": 32, "sealed_status": SEALED_STATUS},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    source_paths = {"master_v1": args.input, "v4d_split": args.v4d_split}
    for name, value in (("v4d_open_teacher", args.v4d_open_teacher), ("tnp_summary", args.tnp_summary), ("igfold_summary", args.igfold_summary), ("igfold_nbb2_audit", args.igfold_nbb2_audit)):
        if value is not None:
            source_paths[name] = value
    audit = {
        "schema_version": "pvrig_candidate_evidence_lineage_audit_v2",
        "status": "PASS_V2_MERGE",
        "row_count": len(rows),
        "unique_candidate_id_count": len(master),
        "unique_sequence_sha256_count": len({row["sequence_sha256"] for row in rows}),
        "sequence_hash_verified_count": len(rows),
        "cohort_counts": dict(Counter(row["source_cohort"] for row in rows)),
        "v4d": {"open_teacher_rows": sum(row["v4d_teacher_merge_status"] == "MERGED_OPEN_TEACHER_258" for row in rows), "sealed_test_rows": sum(row["v4d_teacher_merge_status"] == SEALED_STATUS for row in rows), "split_counts": dict(Counter(row["v4d_teacher_model_split"] for row in rows if row["v4d_teacher_model_split"]))},
        "deep_qc": {"tnp_merged_rows": sum(row["tnp_merge_status"] == "MERGED_TNP_QC_ONLY" for row in rows), "igfold_merged_rows": sum(row["igfold_merge_status"] == "MERGED_IGFOLD_STRUCTURE_QC_ONLY" for row in rows), "nbb2_merged_rows": sum(row["nbb2_merge_status"] == "MERGED_NBB2_STRUCTURE_CROSSCHECK_ONLY" for row in rows)},
        "sources": {name: {"path": str(path), "sha256": sha256_file(path)} for name, path in source_paths.items()},
        "outputs": {"master": {"path": str(master_path), "sha256": sha256_file(master_path)}, "schema": {"path": str(schema_path), "sha256": sha256_file(schema_path)}},
        "claim_boundary": CLAIM_BOUNDARY,
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_sha256s(sums_path, (master_path, schema_path, audit_path))
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--v4d-split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--v4d-open-teacher", type=Path)
    parser.add_argument("--tnp-summary", type=Path)
    parser.add_argument("--igfold-summary", type=Path)
    parser.add_argument("--igfold-nbb2-audit", type=Path)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main() -> int:
    audit = run(parse_args())
    print(json.dumps({"status": audit["status"], "rows": audit["row_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
