#!/usr/bin/env python3
"""Build a deterministic, blinded execution package for the V2.5 PVRIG panel."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]

DEFAULT_PANEL = EXP_DIR / "data_splits/pvrig_v2_5_prospective_assay_panel.csv"
DEFAULT_TARGET_FASTA = DATA_ROOT / "model_data/pvrig_target_ectodomain_proxy_v1.fasta"
DEFAULT_OUTDIR = EXP_DIR / "assays/pvrig_v2_5_prospective_v1"

PACKAGE_VERSION = "pvrig_v2_5_prospective_assay_execution_v1"
RANDOMIZATION_SEED = 20260711
RUN_PLAN = (
    ("BIND_RUN_01", "DAY_BLOCK_01"),
    ("BIND_RUN_02", "DAY_BLOCK_02"),
    ("BIND_RUN_03", "DAY_BLOCK_03"),
)

PANEL_REQUIRED_COLUMNS = {
    "panel_order",
    "prospective_group_id",
    "group_type",
    "candidate_id",
    "candidate_role",
    "family_id",
    "vhh_sequence",
    "sequence_sha256",
    "target_id",
    "target_construct",
    "current_truth_status",
    "claim_boundary",
}


def normalize_sequence(value: object) -> str:
    sequence = "".join(str(value).split()).upper()
    if not sequence or any(residue not in "ACDEFGHIKLMNPQRSTVWY" for residue in sequence):
        raise ValueError(f"Invalid amino-acid sequence: {sequence[:40]!r}")
    return sequence


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_single_fasta(path: Path) -> tuple[str, str]:
    header = ""
    parts: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if header or parts:
                raise ValueError(f"Target FASTA must contain exactly one sequence: {path}")
            header = line[1:]
        else:
            parts.append(line)
    if not header:
        raise ValueError(f"Target FASTA is missing a header: {path}")
    return header, normalize_sequence("".join(parts))


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


def well_for_order(order: int) -> str:
    row_index, column_index = divmod(order - 1, 12)
    return f"{chr(ord('A') + row_index)}{column_index + 1:02d}"


def assay_sample_id(sequence_sha256: str) -> str:
    digest = sha256_text(f"{RANDOMIZATION_SEED}|{sequence_sha256}")[:12].upper()
    return f"PV25-{digest}"


def validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(PANEL_REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise ValueError(f"Panel is missing required columns: {missing}")
    if len(panel) != 24 or panel["prospective_group_id"].nunique() != 8:
        raise ValueError("Execution package requires the frozen 24-pair, 8-group panel")
    if not panel.groupby("prospective_group_id").size().eq(3).all():
        raise ValueError("Every prospective group must contain exactly three candidates")
    expected_group_counts = {
        "paired_mutation_effect": 5,
        "binder_nonblocker_enrichment": 2,
        "verified_nonbinder_confirmation": 1,
    }
    observed_group_counts = panel.groupby("group_type")["prospective_group_id"].nunique().to_dict()
    if observed_group_counts != expected_group_counts:
        raise ValueError(f"Prospective group-type composition changed: {observed_group_counts}")
    expected_roles = {
        "paired_mutation_effect": {
            "known_positive_reference",
            "conservative_mutant",
            "paratope_disruptive_mutant",
        },
        "binder_nonblocker_enrichment": {"de_novo_binding_and_competition_screen"},
        "verified_nonbinder_confirmation": {"negative_verification_candidate_not_current_negative"},
    }
    for group_id, group in panel.groupby("prospective_group_id"):
        group_type = str(group["group_type"].iloc[0])
        if group["group_type"].nunique() != 1 or set(group["candidate_role"].astype(str)) != expected_roles.get(group_type):
            raise ValueError(f"Prospective group role composition changed for {group_id}")
    if panel["candidate_id"].duplicated().any() or panel["sequence_sha256"].duplicated().any():
        raise ValueError("Candidate IDs and sequence hashes must be unique")

    panel = panel.copy().sort_values("panel_order").reset_index(drop=True)
    expected_orders = list(range(1, len(panel) + 1))
    if panel["panel_order"].astype(int).tolist() != expected_orders:
        raise ValueError("panel_order must be the contiguous range 1..24")
    for index, row in panel.iterrows():
        sequence = normalize_sequence(row["vhh_sequence"])
        observed = sha256_text(sequence)
        if observed != str(row["sequence_sha256"]):
            raise ValueError(f"Sequence hash mismatch for {row['candidate_id']}")
        panel.at[index, "vhh_sequence"] = sequence
    if panel["target_id"].nunique() != 1 or panel["target_construct"].nunique() != 1:
        raise ValueError("All panel rows must use one target ID and one target construct")
    if panel["current_truth_status"].astype(str).str.contains("VERIFIED_NONBINDER", case=False).any():
        raise ValueError("Unmeasured candidates cannot enter the package as verified non-binders")
    return panel


def build_identity_tables(panel: pd.DataFrame, target_sequence: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    target_hash = sha256_text(target_sequence)
    rows: list[dict[str, object]] = []
    for source in panel.to_dict(orient="records"):
        rows.append(
            {
                "package_version": PACKAGE_VERSION,
                "assay_sample_id": assay_sample_id(str(source["sequence_sha256"])),
                "panel_order": int(source["panel_order"]),
                "candidate_id": source["candidate_id"],
                "prospective_group_id": source["prospective_group_id"],
                "group_type": source["group_type"],
                "candidate_role": source["candidate_role"],
                "family_id": source["family_id"],
                "vhh_sequence": source["vhh_sequence"],
                "sequence_sha256": source["sequence_sha256"],
                "target_id": source["target_id"],
                "target_construct": source["target_construct"],
                "target_sequence": target_sequence,
                "target_sequence_sha256": target_hash,
                "current_truth_status": source["current_truth_status"],
                "claim_boundary": source["claim_boundary"],
            }
        )
    blinding_key = pd.DataFrame(rows)
    if blinding_key["assay_sample_id"].duplicated().any():
        raise ValueError("Blinded assay sample IDs must be unique")

    construct_manifest = blinding_key.copy()
    construct_manifest["gene_synthesis_status"] = "PENDING"
    construct_manifest["codon_optimized_dna_sequence"] = ""
    construct_manifest["expression_vector"] = ""
    construct_manifest["expression_host"] = ""
    construct_manifest["purification_tag"] = ""
    construct_manifest["expression_lot_id"] = ""
    construct_manifest["construct_notes"] = ""
    return blinding_key, construct_manifest


def build_run_schedule(blinding_key: pd.DataFrame) -> pd.DataFrame:
    sample_ids = blinding_key["assay_sample_id"].astype(str).tolist()
    target_id = str(blinding_key.iloc[0]["target_id"])
    target_construct = str(blinding_key.iloc[0]["target_construct"])
    target_hash = str(blinding_key.iloc[0]["target_sequence_sha256"])
    rows: list[dict[str, object]] = []
    for run_index, (run_id, day_block) in enumerate(RUN_PLAN, start=1):
        randomized = sample_ids.copy()
        random.Random(RANDOMIZATION_SEED + run_index).shuffle(randomized)
        for order, sample_id in enumerate(randomized, start=1):
            rows.append(
                {
                    "package_version": PACKAGE_VERSION,
                    "run_id": run_id,
                    "day_block": day_block,
                    "randomization_seed": RANDOMIZATION_SEED + run_index,
                    "randomized_order": order,
                    "sample_plate_well": well_for_order(order),
                    "assay_sample_id": sample_id,
                    "target_id": target_id,
                    "target_construct": target_construct,
                    "target_sequence_sha256": target_hash,
                    "binding_required": "YES",
                    "competition_if_verified_binder": "YES",
                    "functional_if_verified_blocker": "YES",
                }
            )
    schedule = pd.DataFrame(rows)
    for _, group in schedule.groupby("run_id"):
        if len(group) != 24 or group["assay_sample_id"].nunique() != 24:
            raise ValueError("Every independent run must contain every panel sample exactly once")
    if "candidate_id" in schedule.columns or "candidate_role" in schedule.columns:
        raise ValueError("Blinded run schedule exposed candidate identity")
    return schedule


def build_expression_qc_template(blinding_key: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for row in blinding_key.to_dict(orient="records"):
        rows.append(
            {
                "package_version": PACKAGE_VERSION,
                "assay_sample_id": row["assay_sample_id"],
                "sequence_sha256_expected": row["sequence_sha256"],
                "sequence_sha256_observed": "",
                "expression_lot_id": "",
                "expression_date": "",
                "expression_system": "",
                "vector_id": "",
                "purification_tag": "",
                "expression_yield_mg_per_l": "",
                "purity_fraction": "",
                "sec_monomer_fraction": "",
                "aggregation_fraction": "",
                "identity_method": "",
                "identity_call": "PENDING",
                "scientist_qc_call": "PENDING",
                "raw_data_path": "",
                "raw_data_sha256": "",
                "exclusion_reason": "",
                "notes": "",
            }
        )
    return pd.DataFrame(rows)


def build_binding_template(schedule: pd.DataFrame) -> pd.DataFrame:
    frame = schedule[["package_version", "run_id", "day_block", "randomized_order", "sample_plate_well", "assay_sample_id", "target_id", "target_construct", "target_sequence_sha256"]].copy()
    defaults = {
        "assay_method": "",
        "instrument_id": "",
        "operator_blinded_id": "",
        "assay_batch_id": "",
        "target_lot_id": "",
        "analyte_max_concentration_nM": "",
        "concentration_series_nM": "",
        "technical_replicates": "",
        "response_units": "",
        "response_at_max": "",
        "kd_value_M": "",
        "kd_qualifier": "",
        "fit_model": "",
        "fit_r2": "",
        "fit_qc_call": "PENDING",
        "concentration_dependent_binding_call": "PENDING",
        "scientist_binding_call": "PENDING",
        "raw_data_path": "",
        "raw_data_sha256": "",
        "notes": "",
    }
    for column, value in defaults.items():
        frame[column] = value
    return frame


def build_competition_template(schedule: pd.DataFrame) -> pd.DataFrame:
    frame = schedule[["package_version", "run_id", "day_block", "randomized_order", "sample_plate_well", "assay_sample_id", "target_id", "target_construct", "target_sequence_sha256"]].copy()
    defaults = {
        "verified_binder_eligibility": "PENDING",
        "assay_method": "",
        "instrument_id": "",
        "operator_blinded_id": "",
        "assay_batch_id": "",
        "pvrig_lot_id": "",
        "pvrl2_lot_id": "",
        "analyte_max_concentration_nM": "",
        "concentration_series_nM": "",
        "technical_replicates": "",
        "ic50_value_nM": "",
        "ic50_qualifier": "",
        "inhibition_at_max_fraction": "",
        "fit_model": "",
        "fit_r2": "",
        "fit_qc_call": "PENDING",
        "scientist_blocking_call": "PENDING",
        "raw_data_path": "",
        "raw_data_sha256": "",
        "notes": "",
    }
    for column, value in defaults.items():
        frame[column] = value
    return frame


def build_functional_template(schedule: pd.DataFrame) -> pd.DataFrame:
    frame = schedule[["package_version", "run_id", "day_block", "randomized_order", "sample_plate_well", "assay_sample_id", "target_id", "target_construct", "target_sequence_sha256"]].copy()
    defaults = {
        "verified_blocker_eligibility": "PENDING",
        "assay_method": "",
        "instrument_id": "",
        "operator_blinded_id": "",
        "assay_batch_id": "",
        "cell_or_reporter_lot_id": "",
        "analyte_max_concentration_nM": "",
        "concentration_series_nM": "",
        "technical_replicates": "",
        "ec50_value_nM": "",
        "ec50_qualifier": "",
        "normalized_effect_at_max": "",
        "viability_fraction": "",
        "fit_model": "",
        "fit_r2": "",
        "fit_qc_call": "PENDING",
        "scientist_functional_call": "PENDING",
        "raw_data_path": "",
        "raw_data_sha256": "",
        "notes": "",
    }
    for column, value in defaults.items():
        frame[column] = value
    return frame


def preregistration(panel_path: Path, target_path: Path, target_sequence: str) -> dict[str, object]:
    return {
        "schema_version": "pvrig_v2_5_assay_preregistration_v1",
        "package_version": PACKAGE_VERSION,
        "frozen_inputs": {
            "panel_filename": panel_path.name,
            "panel_sha256": sha256_file(panel_path),
            "target_fasta_filename": target_path.name,
            "target_fasta_sha256": sha256_file(target_path),
            "target_sequence_sha256": sha256_text(target_sequence),
        },
        "replication": {
            "minimum_independent_runs": 3,
            "minimum_distinct_day_blocks": 2,
            "scheduled_independent_runs": 3,
            "scheduled_distinct_day_blocks": 3,
            "randomization_seed": RANDOMIZATION_SEED,
            "consensus_rule": "all_valid_independent_runs_must_agree",
        },
        "manual_scientific_calls": {
            "expression_qc": ["PASS", "FAIL", "INCONCLUSIVE", "PENDING"],
            "binding": ["BINDER", "NONBINDER", "INCONCLUSIVE", "NOT_RUN", "PENDING"],
            "blocking": ["BLOCKER", "NONBLOCKER", "INCONCLUSIVE", "NOT_RUN", "PENDING"],
            "functional": ["POSITIVE", "NEGATIVE", "INCONCLUSIVE", "NOT_RUN", "PENDING"],
        },
        "hard_truth_gates": {
            "expression_failure_is_not_nonbinding": True,
            "assay_failure_is_not_nonbinding": True,
            "binding_is_not_blocking": True,
            "nonbinder_requires_qc_pass_and_absent_concentration_dependent_binding_in_all_valid_runs": True,
            "blocker_requires_verified_binding_before_competition_interpretation": True,
            "functional_claim_requires_verified_blocking_before_functional_interpretation": True,
            "mixed_calls_are_inconclusive": True,
            "raw_data_path_and_sha256_required_for_non_pending_calls": True,
        },
        "lab_parameters_to_freeze_before_first_measurement": {
            "minimum_expression_yield_mg_per_l": None,
            "minimum_purity_fraction": None,
            "minimum_sec_monomer_fraction": None,
            "maximum_aggregation_fraction": None,
            "binding_max_analyte_concentration_nM": None,
            "binding_response_detection_rule": None,
            "binding_fit_qc_rule": None,
            "competition_max_analyte_concentration_nM": None,
            "competition_effect_rule": None,
            "functional_max_analyte_concentration_nM": None,
            "minimum_functional_viability_fraction": None,
            "functional_effect_rule": None,
            "functional_viability_rule": None,
        },
        "claim_boundary": "templates_and_randomization_are_not_experimental_measurements",
    }


def build_readme() -> str:
    return """# PVRIG V2.5 Prospective Assay Execution Package

This directory is a deterministic, blinded handoff package for the frozen
24-pair panel. It contains no experimental measurements.

## Required order

1. Freeze every null value in `assay_preregistration.json` before the first run.
2. Complete construct identity, expression, purification, and SEC QC.
3. Measure binding for all 24 samples in all three randomized run blocks.
4. Run competition only for QC-passed verified binders.
5. Run the functional assay only for verified blockers.
6. Run `analyze_pvrig_v2_5_assay_results.py` after each data update.

`blinding_key.csv` is coordinator-only. Instrument operators should receive
`assay_run_schedule_blinded.csv` and the applicable result template, not the
candidate identities or roles.

Expression or assay failure is exclusion evidence, never a nonbinder label.
Binding is not blocking. The analyzer only aggregates explicit scientist calls;
it does not invent assay thresholds or replace review of raw curves.
"""


def write_fasta(blinding_key: pd.DataFrame, path: Path) -> None:
    lines: list[str] = []
    for row in blinding_key.to_dict(orient="records"):
        lines.extend([f">{row['assay_sample_id']}", str(row["vhh_sequence"])])
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def ensure_safe_to_rebuild(outdir: Path) -> None:
    if not outdir.exists():
        return
    manifest_path = outdir / "package_manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("preregistration_frozen"):
            raise ValueError("Refusing to rebuild a package after lab preregistration was frozen")
        expected = manifest.get("frozen_artifacts", {}).get("assay_preregistration.json")
        prereg_path = outdir / "assay_preregistration.json"
        if expected and prereg_path.is_file() and sha256_file(prereg_path) != expected:
            raise ValueError("Refusing to overwrite an edited but not yet frozen preregistration")

    result_calls = {
        "expression_qc_results.csv": "scientist_qc_call",
        "binding_results.csv": "scientist_binding_call",
        "competition_results.csv": "scientist_blocking_call",
        "functional_results.csv": "scientist_functional_call",
    }
    for filename, column in result_calls.items():
        path = outdir / filename
        if not path.is_file():
            continue
        frame = pd.read_csv(path, keep_default_na=False, dtype=str)
        if column in frame.columns and frame[column].astype(str).str.strip().str.upper().ne("PENDING").any():
            raise ValueError(f"Refusing to overwrite non-pending assay results in {filename}")

    construct_path = outdir / "construct_manifest.csv"
    if construct_path.is_file():
        constructs = pd.read_csv(construct_path, keep_default_na=False, dtype=str)
        mutable = [
            "codon_optimized_dna_sequence",
            "expression_vector",
            "expression_host",
            "purification_tag",
            "expression_lot_id",
            "construct_notes",
        ]
        if "gene_synthesis_status" in constructs.columns and constructs["gene_synthesis_status"].str.upper().ne("PENDING").any():
            raise ValueError("Refusing to overwrite construct-order progress")
        if any(
            column in constructs.columns and constructs[column].astype(str).str.strip().ne("").any()
            for column in mutable
        ):
            raise ValueError("Refusing to overwrite edited construct-manifest fields")


def build_package(panel_path: Path, target_path: Path, outdir: Path) -> dict[str, object]:
    ensure_safe_to_rebuild(outdir)
    panel = validate_panel(pd.read_csv(panel_path))
    _, target_sequence = read_single_fasta(target_path)
    blinding_key, construct_manifest = build_identity_tables(panel, target_sequence)
    schedule = build_run_schedule(blinding_key)

    outdir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, pd.DataFrame] = {
        "blinding_key.csv": blinding_key,
        "construct_manifest.csv": construct_manifest,
        "assay_run_schedule_blinded.csv": schedule,
        "expression_qc_results.csv": build_expression_qc_template(blinding_key),
        "binding_results.csv": build_binding_template(schedule),
        "competition_results.csv": build_competition_template(schedule),
        "functional_results.csv": build_functional_template(schedule),
    }
    for filename, frame in artifacts.items():
        write_csv(frame, outdir / filename)

    write_fasta(blinding_key, outdir / "panel_blinded.fasta")
    (outdir / "assay_preregistration.json").write_text(
        json.dumps(preregistration(panel_path, target_path, target_sequence), indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    (outdir / "README.md").write_text(build_readme(), encoding="ascii")

    manifest_names = sorted(
        [*artifacts, "README.md", "assay_preregistration.json", "panel_blinded.fasta"]
    )
    manifest_files = [outdir / name for name in manifest_names]
    artifact_hashes = {path.name: sha256_file(path) for path in manifest_files}
    frozen_names = {
        "README.md",
        "assay_preregistration.json",
        "assay_run_schedule_blinded.csv",
        "blinding_key.csv",
        "panel_blinded.fasta",
    }
    manifest = {
        "schema_version": "pvrig_v2_5_assay_package_manifest_v1",
        "package_version": PACKAGE_VERSION,
        "artifact_count": len(manifest_files),
        "artifacts": artifact_hashes,
        "frozen_artifacts": {name: artifact_hashes[name] for name in sorted(frozen_names)},
        "mutable_templates_initial_sha256": {
            name: digest for name, digest in artifact_hashes.items() if name not in frozen_names
        },
        "counts": {
            "panel_candidates": len(blinding_key),
            "prospective_groups": int(blinding_key["prospective_group_id"].nunique()),
            "scheduled_runs": int(schedule["run_id"].nunique()),
            "scheduled_day_blocks": int(schedule["day_block"].nunique()),
            "scheduled_sample_runs": len(schedule),
        },
        "status": "READY_FOR_LAB_PREREGISTRATION",
        "measurement_status": "NO_EXPERIMENTAL_RESULTS_RECORDED",
    }
    (outdir / "package_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--target-fasta", type=Path, default=DEFAULT_TARGET_FASTA)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = build_package(args.panel, args.target_fasta, args.outdir)
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
