#!/usr/bin/env python3
"""Build an ID-closed sequence-level multi-metric release for the Node1 300k pool.

This stage deliberately stops before structure-dependent NBB2/TNP/Docking metrics.
Binding-model outputs are weak priors and are never used as hard biological labels.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import statistics
import time
from collections import Counter
from pathlib import Path


def open_table(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode, newline="")
    return path.open(mode, newline="")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_candidate_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def load_rows(
    path: Path,
    *,
    id_field: str,
    normalize_ids: bool = False,
) -> tuple[list[str], dict[str, dict[str, str]], dict[str, str]]:
    with open_table(path, "rt") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        if id_field not in fields:
            raise ValueError(f"{path}: missing ID field {id_field}")
        rows: dict[str, dict[str, str]] = {}
        raw_ids: dict[str, str] = {}
        for row in reader:
            raw_id = row[id_field]
            candidate_id = normalize_candidate_id(raw_id) if normalize_ids else raw_id
            if candidate_id in rows:
                raise ValueError(f"{path}: duplicate normalized candidate_id {candidate_id}")
            rows[candidate_id] = row
            raw_ids[candidate_id] = raw_id
    return fields, rows, raw_ids


def finite_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def quantile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile from an empty list")
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def bool_text(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "pass"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fast-qc", required=True, type=Path)
    parser.add_argument("--sapiens", required=True, type=Path)
    parser.add_argument("--abnativ", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected", type=int, default=300_000)
    args = parser.parse_args()

    fast_fields, fast, _ = load_rows(args.fast_qc, id_field="candidate_id")
    sapiens_fields, sapiens, _ = load_rows(args.sapiens, id_field="seq_id")
    abnativ_fields, abnativ, _ = load_rows(args.abnativ, id_field="seq_id")
    binding_fields, binding, binding_raw_ids = load_rows(
        args.binding,
        id_field="candidate_id",
        normalize_ids=True,
    )

    if len(fast) != args.expected or len(binding) != args.expected:
        raise ValueError(
            f"expected {args.expected} records: fast={len(fast)} binding={len(binding)}"
        )
    if set(fast) != set(binding):
        raise ValueError(
            "binding ID normalization did not close exactly against fast-QC IDs: "
            f"fast_only={len(set(fast) - set(binding))} "
            f"binding_only={len(set(binding) - set(fast))}"
        )

    hardpass_ids = {
        candidate_id
        for candidate_id, row in fast.items()
        if not bool_text(row.get("hard_fail", ""))
    }
    if set(sapiens) != hardpass_ids:
        raise ValueError(
            "Sapiens IDs do not exactly match fast-QC hard-pass IDs: "
            f"hardpass_only={len(hardpass_ids - set(sapiens))} "
            f"sapiens_only={len(set(sapiens) - hardpass_ids)}"
        )
    if set(abnativ) != hardpass_ids:
        raise ValueError(
            "AbNatiV IDs do not exactly match fast-QC hard-pass IDs: "
            f"hardpass_only={len(hardpass_ids - set(abnativ))} "
            f"abnativ_only={len(set(abnativ) - hardpass_ids)}"
        )

    deepnano_values = [
        value
        for row in binding.values()
        if (value := finite_float(row.get("deepnano_binding_prior", ""))) is not None
    ]
    nanobind_values = [
        value
        for row in binding.values()
        if (value := finite_float(row.get("nanobind_binding_prior", ""))) is not None
    ]
    disagreement_values = [
        value
        for row in binding.values()
        if (
            value := finite_float(
                row.get("binding_model_percentile_disagreement", "")
            )
        )
        is not None
    ]
    sapiens_values = [
        value
        for row in sapiens.values()
        if (value := finite_float(row.get("mean_self_probability", ""))) is not None
    ]
    abnativ_values = [
        value
        for row in abnativ.values()
        if row.get("abnativ_status") == "PASS"
        and (value := finite_float(row.get("AbNatiV VHH Score", ""))) is not None
    ]
    thresholds = {
        "deepnano_q20": quantile(deepnano_values, 0.20),
        "deepnano_q80": quantile(deepnano_values, 0.80),
        "nanobind_q20": quantile(nanobind_values, 0.20),
        "nanobind_q80": quantile(nanobind_values, 0.80),
        "binding_disagreement_q95": quantile(disagreement_values, 0.95),
        "sapiens_q05": quantile(sapiens_values, 0.05),
        "abnativ_pass_q05": quantile(abnativ_values, 0.05),
    }

    sapiens_output_fields = [
        field for field in sapiens_fields if field not in {"seq_id"}
    ]
    abnativ_output_fields = [
        field
        for field in abnativ_fields
        if field not in {"seq_id", "input_seq", "aligned_seq"}
    ]
    binding_output_fields = [
        field for field in binding_fields if field != "candidate_id"
    ]
    derived_fields = [
        "binding_raw_candidate_id",
        "sequence_hard_gate",
        "sequence_hard_gate_reason",
        "binding_weak_prior_tier",
        "developability_review_tier",
        "prestructure_sequence_tier",
        "multimetric_model_coverage",
        "structure_dependent_metrics_status",
    ]
    output_fields = list(fast_fields)
    output_fields += [f"sapiens_{field}" for field in sapiens_output_fields]
    output_fields += [f"abnativ_{field}" for field in abnativ_output_fields]
    output_fields += binding_output_fields + derived_fields

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "node1_generated300k_sequence_multimetric.tsv.gz"
    hardpass_fasta = args.output_dir / "node1_generated300k_hardpass.fasta.gz"
    priority_fasta = (
        args.output_dir / "node1_generated300k_priority_weak_binding_consensus.fasta.gz"
    )
    tier_counts: Counter[str] = Counter()
    binding_tier_counts: Counter[str] = Counter()
    developability_tier_counts: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()

    with (
        gzip.open(output, "wt", newline="", compresslevel=1) as table_handle,
        gzip.open(hardpass_fasta, "wt", compresslevel=1) as hardpass_handle,
        gzip.open(priority_fasta, "wt", compresslevel=1) as priority_handle,
    ):
        writer = csv.DictWriter(
            table_handle,
            fieldnames=output_fields,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for candidate_id in sorted(fast):
            frow = fast[candidate_id]
            brow = binding[candidate_id]
            srow = sapiens.get(candidate_id)
            arow = abnativ.get(candidate_id)
            hard_gate = (
                not bool_text(frow.get("hard_fail", ""))
                and bool_text(frow.get("standard_aa_only", ""))
                and bool_text(frow.get("ANARCI_status", ""))
                and frow.get("pass_similarity_filter") == "PASS"
            )

            deepnano = finite_float(brow.get("deepnano_binding_prior", ""))
            nanobind = finite_float(brow.get("nanobind_binding_prior", ""))
            disagreement = finite_float(
                brow.get("binding_model_percentile_disagreement", "")
            )
            if disagreement is not None and disagreement >= thresholds[
                "binding_disagreement_q95"
            ]:
                binding_tier = "HIGH_DISAGREEMENT_REVIEW"
            elif (
                deepnano is not None
                and nanobind is not None
                and deepnano >= thresholds["deepnano_q80"]
                and nanobind >= thresholds["nanobind_q80"]
            ):
                binding_tier = "HIGH_WEAK_PRIOR_CONSENSUS"
            elif (
                deepnano is not None
                and nanobind is not None
                and deepnano <= thresholds["deepnano_q20"]
                and nanobind <= thresholds["nanobind_q20"]
            ):
                binding_tier = "LOW_WEAK_PRIOR_CONSENSUS"
            else:
                binding_tier = "MIXED_WEAK_PRIOR"

            if not hard_gate:
                developability_tier = "NOT_EVALUATED_HARD_FAIL"
            elif arow is None or srow is None:
                developability_tier = "MODEL_COVERAGE_MISSING"
            elif arow.get("abnativ_status") != "PASS":
                developability_tier = "ABNATIV_TECHNICAL_NA_REVIEW"
            else:
                sapiens_score = finite_float(srow.get("mean_self_probability", ""))
                abnativ_score = finite_float(arow.get("AbNatiV VHH Score", ""))
                if (
                    sapiens_score is None
                    or abnativ_score is None
                    or sapiens_score < thresholds["sapiens_q05"]
                    or abnativ_score < thresholds["abnativ_pass_q05"]
                ):
                    developability_tier = "LOW_MODEL_TAIL_REVIEW"
                else:
                    developability_tier = "STANDARD"

            if not hard_gate:
                prestructure_tier = "HARD_FAIL"
            elif developability_tier != "STANDARD":
                prestructure_tier = "DEVELOPABILITY_REVIEW"
            elif binding_tier == "HIGH_WEAK_PRIOR_CONSENSUS":
                prestructure_tier = "PRIORITY_WEAK_BINDING_CONSENSUS"
            elif binding_tier == "LOW_WEAK_PRIOR_CONSENSUS":
                prestructure_tier = "ELIGIBLE_LOW_WEAK_PRIOR"
            else:
                prestructure_tier = "ELIGIBLE"

            merged = dict(frow)
            if srow is not None:
                merged.update(
                    {
                        f"sapiens_{field}": srow.get(field, "")
                        for field in sapiens_output_fields
                    }
                )
            if arow is not None:
                merged.update(
                    {
                        f"abnativ_{field}": arow.get(field, "")
                        for field in abnativ_output_fields
                    }
                )
            merged.update(
                {field: brow.get(field, "") for field in binding_output_fields}
            )
            merged.update(
                {
                    "binding_raw_candidate_id": binding_raw_ids[candidate_id],
                    "sequence_hard_gate": str(hard_gate),
                    "sequence_hard_gate_reason": (
                        "" if hard_gate else frow.get("reason_summary", "hard_fail")
                    ),
                    "binding_weak_prior_tier": binding_tier,
                    "developability_review_tier": developability_tier,
                    "prestructure_sequence_tier": prestructure_tier,
                    "multimetric_model_coverage": (
                        "sequence_descriptors;ANARCI;Sapiens;AbNatiV;DeepNano;NanoBind"
                    ),
                    "structure_dependent_metrics_status": (
                        "PENDING_NBB2_TNP_DOCKING_SURROGATE"
                    ),
                }
            )
            writer.writerow(merged)

            if hard_gate:
                hardpass_handle.write(f">{candidate_id}\n{frow['sequence']}\n")
            if prestructure_tier == "PRIORITY_WEAK_BINDING_CONSENSUS":
                priority_handle.write(f">{candidate_id}\n{frow['sequence']}\n")

            tier_counts[prestructure_tier] += 1
            binding_tier_counts[binding_tier] += 1
            developability_tier_counts[developability_tier] += 1
            route = (
                "rfantibody"
                if "source_rfantibody" in candidate_id
                else "fixed_pose_mpnn"
                if "source_fixed_pose_mpnn" in candidate_id
                else "other"
            )
            route_counts[route] += 1

    receipt = {
        "schema_version": "pvrig.node1_generated300k.sequence_multimetric.v1",
        "status": "READY_FOR_PRESTRUCTURE_SELECTION",
        "records": len(fast),
        "hardpass_records": len(hardpass_ids),
        "id_closure": {
            "fast_binding_exact_after_normalization": True,
            "hardpass_sapiens_exact": True,
            "hardpass_abnativ_exact": True,
            "binding_normalization": "replace each non [A-Za-z0-9_.-] character with underscore",
        },
        "thresholds_are_within_batch_review_tiers_not_biological_cutoffs": thresholds,
        "prestructure_sequence_tier_counts": dict(sorted(tier_counts.items())),
        "binding_weak_prior_tier_counts": dict(sorted(binding_tier_counts.items())),
        "developability_review_tier_counts": dict(
            sorted(developability_tier_counts.items())
        ),
        "route_counts": dict(sorted(route_counts.items())),
        "outputs": {
            output.name: sha256(output),
            hardpass_fasta.name: sha256(hardpass_fasta),
            priority_fasta.name: sha256(priority_fasta),
        },
        "scientific_boundaries": {
            "binding_models": "weak binding priors; not Kd, IC50, or blocking evidence",
            "Sapiens": "human-likeness proxy; not measured expression or purity",
            "AbNatiV": "VHH nativeness proxy; not measured expression or purity",
            "prestructure_tiers": "within-batch triage only; not a final candidate ranking",
            "pending": "NBB2, TNP, Docking surrogate and pose-based scoring require later stages",
        },
        "created_epoch": time.time(),
    }
    ready = args.output_dir / "READY.json"
    ready.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    sums = args.output_dir / "SHA256SUMS"
    sums.write_text(
        "\n".join(f"{digest}  {name}" for name, digest in receipt["outputs"].items())
        + "\n"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
