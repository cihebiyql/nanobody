#!/usr/bin/env python3
"""Compute the frozen V2.4 receptor-specific contact composite."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


FORMULA_VERSION = "pvrig_v2_4_contact_composite_v1_equal_weight_preregistered"
INPUT_COLUMNS = (
    "candidate_id",
    "hotspot_contact_mass_R8",
    "interface_specificity_R8",
    "hotspot_contact_mass_R9",
    "interface_specificity_R9",
)
OUTPUT_COLUMNS = (*INPUT_COLUMNS, "contact_score_R8", "contact_score_R9")


class ContactFormulaError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_and_validate_formula(path: Path) -> dict[str, Any]:
    formula = json.loads(path.read_text(encoding="utf-8"))
    if formula.get("formula_version") != FORMULA_VERSION:
        raise ContactFormulaError("formula_version_mismatch")
    if formula.get("receptors") != ["R8", "R9"]:
        raise ContactFormulaError("receptor_contract_mismatch")
    if formula.get("inputs_per_receptor") != [
        "hotspot_contact_mass",
        "interface_specificity",
    ]:
        raise ContactFormulaError("formula_input_contract_mismatch")
    weights = formula.get("weights")
    if weights != {"hotspot_contact_mass": 0.5, "interface_specificity": 0.5}:
        raise ContactFormulaError("formula_weights_not_frozen_equal_half")
    if formula.get("intercept") != 0.0 or formula.get("clipping") is not False:
        raise ContactFormulaError("formula_intercept_or_clipping_mismatch")
    if formula.get("label_access") is not False or formula.get("outer_result_tuning") is not False:
        raise ContactFormulaError("formula_claims_outer_label_access")
    if formula.get("input_domain") != {"maximum": 1.0, "minimum": 0.0}:
        raise ContactFormulaError("formula_input_domain_mismatch")
    return formula


def _bounded_float(row: Mapping[str, str], column: str, row_number: int) -> float:
    try:
        value = float(row[column])
    except (KeyError, TypeError, ValueError) as exc:
        raise ContactFormulaError(
            f"non_numeric_input:row={row_number}:column={column}"
        ) from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ContactFormulaError(
            f"input_outside_unit_interval:row={row_number}:column={column}:value={value}"
        )
    return value


def compute_rows(
    rows: Sequence[Mapping[str, str]], fieldnames: Sequence[str]
) -> list[dict[str, str]]:
    if tuple(fieldnames) != INPUT_COLUMNS:
        raise ContactFormulaError("exact_input_header_mismatch")
    if not rows:
        raise ContactFormulaError("empty_contact_input")
    output: list[dict[str, str]] = []
    candidate_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        candidate_id = str(row.get("candidate_id", ""))
        if not candidate_id:
            raise ContactFormulaError(f"blank_candidate_id:row={row_number}")
        if candidate_id in candidate_ids:
            raise ContactFormulaError(f"duplicate_candidate_id:{candidate_id}")
        candidate_ids.add(candidate_id)
        h8 = _bounded_float(row, "hotspot_contact_mass_R8", row_number)
        i8 = _bounded_float(row, "interface_specificity_R8", row_number)
        h9 = _bounded_float(row, "hotspot_contact_mass_R9", row_number)
        i9 = _bounded_float(row, "interface_specificity_R9", row_number)
        result = dict(row)
        result["contact_score_R8"] = format(0.5 * h8 + 0.5 * i8, ".17g")
        result["contact_score_R9"] = format(0.5 * h9 + 0.5 * i9, ".17g")
        output.append(result)
    return output


def run(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input_tsv).resolve()
    formula_path = Path(args.formula_json).resolve()
    output_path = Path(args.output_tsv).resolve()
    receipt_path = Path(args.receipt_json).resolve()
    if output_path.exists() or receipt_path.exists():
        raise ContactFormulaError("output_already_exists")
    load_and_validate_formula(formula_path)
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)
        fieldnames = list(reader.fieldnames or ())
    output_rows = compute_rows(rows, fieldnames)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=OUTPUT_COLUMNS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(output_rows)
    receipt = {
        "status": "PASS_FROZEN_CONTACT_COMPOSITE",
        "formula_version": FORMULA_VERSION,
        "formula_path": str(formula_path),
        "formula_receipt_sha256": sha256_file(formula_path),
        "input_tsv_sha256": sha256_file(input_path),
        "output_tsv_sha256": sha256_file(output_path),
        "candidate_count": len(output_rows),
        "outer_result_tuning": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-tsv", required=True)
    parser.add_argument("--formula-json", required=True)
    parser.add_argument("--output-tsv", required=True)
    parser.add_argument("--receipt-json", required=True)
    return parser


def main() -> int:
    print(json.dumps(run(build_parser().parse_args()), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
