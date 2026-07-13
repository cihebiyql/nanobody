#!/usr/bin/env python3
"""Audit HETATM contamination in the PVRIG V1.1 docking smoke labels.

This is an independent, read-only diagnostic. It reproduces the current
ATOM+HETATM PVRL2 occlusion calculation, then changes only the PVRL2 record
filter to ATOM for a sensitivity classification comparison.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

DEFAULT_INPUT_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_postprocessed"
)
DEFAULT_RULES = (
    WORKSPACE_ROOT / "docking/success_case_validation/blocker_judgment_rules_v2.json"
)
DEFAULT_CLASSIFIER = (
    WORKSPACE_ROOT / "docking/success_case_validation/apply_blocker_judgment.py"
)
DEFAULT_SCORER = WORKSPACE_ROOT / "docking/scripts/score_cdr_region_occlusion.py"
DEFAULT_OUTPUT_CSV = (
    EXP_DIR / "audits/phase2_v3_p2_v1_1_hetatm_contamination_rows.csv"
)
DEFAULT_OUTPUT_JSON = (
    EXP_DIR / "audits/phase2_v3_p2_v1_1_hetatm_contamination_audit.json"
)
DEFAULT_OUTPUT_REPORT = (
    EXP_DIR / "reports/PVRIG_V3_P2_V1_1_HETATM_CONTAMINATION_REJECTION_ZH.md"
)

BASELINES = {
    "8x6b": {
        "reference": DATA_ROOT / "structures/8X6B.pdb",
        "pvrl2_chain": "A",
        "marker_reference_key": "8x6b_scoring_reference",
    },
    "9e6y": {
        "reference": DATA_ROOT / "structures/9E6Y.pdb",
        "pvrl2_chain": "D",
        "marker_reference_key": "9e6y_scoring_reference",
    },
}

SCHEMA_VERSION = "phase2_v3_p2_v1_1_hetatm_contamination_audit_v1"
ROW_SCHEMA_VERSION = "phase2_v3_p2_v1_1_hetatm_contamination_row_v1"
REJECTION_STATUS = "REJECT_V1_1_HETATM_CONTAMINATION_CONFIRMED"
CLAIM_BOUNDARY = (
    "Read-only V1.1 contamination and sensitivity audit. Protein-only "
    "recomputation diagnoses HETATM-driven changes under the current V1.1 "
    "classification rules; it is not a V1.2 calibrated label, a corrected "
    "Docking Gold set, experimental binding truth, or blocking truth."
)

CSV_FIELDS = [
    "schema_version",
    "run_id",
    "pilot_id",
    "source_candidate_id",
    "generation_receptor",
    "seed_role",
    "baseline",
    "model",
    "haddock_rank",
    "aligned_pose_path",
    "aligned_pose_sha256",
    "cdr_json_path",
    "cdr_json_sha256",
    "reference_pdb",
    "reference_sha256",
    "pvrl2_chain",
    "vhh_chain",
    "cdr1_range",
    "cdr2_range",
    "cdr3_range",
    "contact_cutoff_a",
    "reference_protein_atom_count",
    "reference_protein_residue_count",
    "reference_hetatm_atom_count",
    "reference_hetatm_residue_count",
    "reference_hoh_atom_count",
    "reference_hoh_residue_count",
    "reference_edo_atom_count",
    "reference_edo_residue_count",
    "reference_other_hetatm_atom_count",
    "reference_other_hetatm_residue_count",
    "current_total_residue_pair_occlusion",
    "recomputed_inclusive_total_residue_pair_occlusion",
    "protein_only_total_residue_pair_occlusion",
    "total_inflation_absolute",
    "total_current_to_protein_only_factor",
    "current_cdr3_residue_pair_occlusion",
    "recomputed_inclusive_cdr3_residue_pair_occlusion",
    "protein_only_cdr3_residue_pair_occlusion",
    "cdr3_inflation_absolute",
    "cdr3_current_to_protein_only_factor",
    "current_cdr3_fraction",
    "recomputed_inclusive_cdr3_fraction",
    "protein_only_cdr3_fraction",
    "fraction_delta_current_minus_protein_only",
    "hotspot_overlap_count",
    "current_v1_1_class",
    "recomputed_current_v1_1_class",
    "protein_only_sensitivity_class",
    "class_transition",
    "class_changed",
    "affected",
    "current_metric_reproduction_match",
    "current_class_reproduction_match",
    "source_consistency_pass",
    "claim_boundary",
]


@dataclass(frozen=True)
class Atom:
    record: str
    chain: str
    resname: str
    resseq: int | None
    icode: str
    resid: str
    xyz: tuple[float, float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--rules-json", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--classifier-path", type=Path, default=DEFAULT_CLASSIFIER)
    parser.add_argument("--scorer-path", type=Path, default=DEFAULT_SCORER)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_OUTPUT_REPORT)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        size = path.stat().st_size
        digest.update(f"{relative}\0{size}\0{file_hash}\n".encode("utf-8"))
        count += 1
        total_bytes += size
    return {"file_count": count, "total_bytes": total_bytes, "sha256": digest.hexdigest()}


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def read_csv_unique(path: Path, key: str = "model") -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        value = (row.get(key) or "").strip()
        if not value:
            raise ValueError(f"Missing {key} in {path}")
        if value in result:
            raise ValueError(f"Duplicate {key}={value!r} in {path}")
        result[value] = row
    return result


def require_float(value: Any, label: str, *, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid numeric value for {label}: {value!r}") from error
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Non-finite or negative value for {label}: {value!r}")
    if maximum is not None and number > maximum:
        raise ValueError(f"Value exceeds {maximum} for {label}: {value!r}")
    return number


def require_int(value: Any, label: str) -> int:
    number = require_float(value, label)
    if not number.is_integer():
        raise ValueError(f"Expected integer for {label}: {value!r}")
    return int(number)


def parse_range(spec: str) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"Invalid residue range: {spec!r}")
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    if not values:
        raise ValueError(f"Empty residue range: {spec!r}")
    return values


def atom_element(line: str) -> str:
    element = line[76:78].strip() if len(line) >= 78 else ""
    if element:
        return element.upper()
    return "".join(char for char in line[12:16].strip() if char.isalpha())[:1].upper()


def iter_heavy_atoms(
    path: Path,
    chain: str | None = None,
    records: frozenset[str] = frozenset({"ATOM", "HETATM"}),
) -> Iterable[Atom]:
    for line in path.read_text(errors="replace").splitlines():
        record = line[:6].strip()
        if record not in records or len(line) < 54:
            continue
        if chain is not None and line[21] != chain:
            continue
        if atom_element(line) == "H":
            continue
        try:
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
        except ValueError:
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                x, y, z = float(parts[6]), float(parts[7]), float(parts[8])
            except ValueError:
                continue
        try:
            resseq = int(line[22:26].strip())
        except ValueError:
            resseq = None
        resname = line[17:20].strip()
        icode = line[26].strip()
        resid = f"{line[21]}:{line[22:26].strip()}{icode}{resname}"
        yield Atom(record, line[21], resname, resseq, icode, resid, (x, y, z))


def reference_inventory(atoms: Sequence[Atom]) -> dict[str, int]:
    def count(record: str | None = None, resname: str | None = None) -> tuple[int, int]:
        selected = [
            atom
            for atom in atoms
            if (record is None or atom.record == record)
            and (resname is None or atom.resname == resname)
        ]
        return len(selected), len({atom.resid for atom in selected})

    protein_atoms, protein_residues = count("ATOM")
    hetatm_atoms, hetatm_residues = count("HETATM")
    hoh_atoms, hoh_residues = count("HETATM", "HOH")
    edo_atoms, edo_residues = count("HETATM", "EDO")
    other = [
        atom for atom in atoms if atom.record == "HETATM" and atom.resname not in {"HOH", "EDO"}
    ]
    return {
        "protein_atom_count": protein_atoms,
        "protein_residue_count": protein_residues,
        "hetatm_atom_count": hetatm_atoms,
        "hetatm_residue_count": hetatm_residues,
        "hoh_atom_count": hoh_atoms,
        "hoh_residue_count": hoh_residues,
        "edo_atom_count": edo_atoms,
        "edo_residue_count": edo_residues,
        "other_hetatm_atom_count": len(other),
        "other_hetatm_residue_count": len({atom.resid for atom in other}),
    }


def contact_pair_summaries(
    vhh_atoms: Sequence[Atom],
    pvrl2_atoms: Sequence[Atom],
    cutoff: float,
    cdr3: set[int],
) -> dict[str, dict[str, float | int]]:
    if cutoff <= 0 or not math.isfinite(cutoff):
        raise ValueError(f"Invalid contact cutoff: {cutoff}")
    if not vhh_atoms or not pvrl2_atoms:
        raise ValueError("Contact calculation requires non-empty VHH and PVRL2 atom sets")

    grid: dict[tuple[int, int, int], list[Atom]] = defaultdict(list)
    for atom in pvrl2_atoms:
        cell = tuple(math.floor(value / cutoff) for value in atom.xyz)
        grid[cell].append(atom)

    inclusive_pairs: set[tuple[str, str]] = set()
    inclusive_cdr3_pairs: set[tuple[str, str]] = set()
    protein_pairs: set[tuple[str, str]] = set()
    protein_cdr3_pairs: set[tuple[str, str]] = set()
    cutoff2 = cutoff * cutoff
    offsets = (-1, 0, 1)
    for vhh_atom in vhh_atoms:
        center = tuple(math.floor(value / cutoff) for value in vhh_atom.xyz)
        for dx in offsets:
            for dy in offsets:
                for dz in offsets:
                    for ref_atom in grid.get(
                        (center[0] + dx, center[1] + dy, center[2] + dz), []
                    ):
                        distance2 = sum(
                            (vhh_atom.xyz[index] - ref_atom.xyz[index]) ** 2
                            for index in range(3)
                        )
                        if distance2 > cutoff2:
                            continue
                        pair = (vhh_atom.resid, ref_atom.resid)
                        inclusive_pairs.add(pair)
                        if vhh_atom.resseq in cdr3:
                            inclusive_cdr3_pairs.add(pair)
                        if ref_atom.record == "ATOM":
                            protein_pairs.add(pair)
                            if vhh_atom.resseq in cdr3:
                                protein_cdr3_pairs.add(pair)

    def summarize(
        all_pairs: set[tuple[str, str]], cdr3_pairs: set[tuple[str, str]]
    ) -> dict[str, float | int]:
        return {
            "total_residue_pair_occlusion": len(all_pairs),
            "cdr3_residue_pair_occlusion": len(cdr3_pairs),
            "cdr3_fraction": len(cdr3_pairs) / len(all_pairs) if all_pairs else 0.0,
        }

    return {
        "inclusive": summarize(inclusive_pairs, inclusive_cdr3_pairs),
        "protein_only": summarize(protein_pairs, protein_cdr3_pairs),
    }


def threshold_value(text: str) -> float:
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if not match:
        raise ValueError(f"Cannot parse threshold from {text!r}")
    return float(match.group(0))


def load_rules(path: Path) -> dict[str, float]:
    payload = read_json_object(path)
    required = payload["classifier"]["BLOCKER_LIKE_A"]["required_for_vhh_docking"]
    return {
        "hotspot_min": threshold_value(required["hotspot_overlap_count"]),
        "total_min": threshold_value(required["total_vhh_pvrl2_residue_pair_occlusion"]),
        "cdr3_min": threshold_value(required["cdr3_pvrl2_residue_pair_occlusion"]),
        "cdr3_fraction_min": threshold_value(required["cdr3_occlusion_fraction"]),
        # These values are hardcoded in the current classifier and are hash-bound below.
        "binder_total_max": 50.0,
        "b_total_min": 500.0,
        "b_cdr3_min": 50.0,
        "b_fallback_total_min": 300.0,
        "b_fallback_hotspot_min": 10.0,
        "b_fallback_cdr3_min": 50.0,
    }


def classify_sensitivity(
    hotspot: float,
    total: float,
    cdr3: float,
    fraction: float,
    rules: dict[str, float],
) -> str:
    pass_hotspot = hotspot >= rules["hotspot_min"]
    if (
        pass_hotspot
        and total >= rules["total_min"]
        and cdr3 >= rules["cdr3_min"]
        and fraction >= rules["cdr3_fraction_min"]
    ):
        return "BLOCKER_LIKE_A"
    if pass_hotspot and total < rules["binder_total_max"]:
        return "BINDER_LIKE_C"
    if total >= rules["b_total_min"] and (pass_hotspot or cdr3 >= rules["b_cdr3_min"]):
        return "BLOCKER_PLAUSIBLE_B"
    if (
        total >= rules["b_fallback_total_min"]
        and hotspot >= rules["b_fallback_hotspot_min"]
        and cdr3 >= rules["b_fallback_cdr3_min"]
    ):
        return "BLOCKER_PLAUSIBLE_B"
    return "EVIDENCE_INFERENCE_ONLY_E"


def safe_factor(current: float, protein_only: float) -> float | None:
    return current / protein_only if protein_only else None


def close(left: float, right: float, *, tolerance: float = 1e-9) -> bool:
    return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def csv_number(value: float | int | None) -> str | int:
    if value is None:
        return ""
    if isinstance(value, int):
        return value
    return f"{value:.12g}"


def validate_marker_contract(
    marker: dict[str, Any],
    marker_path: Path,
    run_id: str,
    static_hashes: dict[str, str],
) -> None:
    if marker.get("status") != "PASS" or marker.get("run_id") != run_id:
        raise ValueError(f"Invalid postprocess marker identity/status: {marker_path}")
    if marker.get("protocol_id") != "DG_A_PILOT64_V1_1":
        raise ValueError(f"Unexpected protocol in {marker_path}")
    expected_toolchain = {
        "score_cdr_region_occlusion": static_hashes["current_occlusion_scorer"],
        "apply_blocker_judgment": static_hashes["current_classifier"],
    }
    for key, expected in expected_toolchain.items():
        actual = marker.get("toolchain_sha256", {}).get(key)
        if actual != expected:
            raise ValueError(f"Marker toolchain hash mismatch for {run_id}:{key}")
    for baseline, config in BASELINES.items():
        key = str(config["marker_reference_key"])
        actual = marker.get("reference_sha256", {}).get(key)
        if actual != static_hashes[f"reference_{baseline}"]:
            raise ValueError(f"Marker reference hash mismatch for {run_id}:{baseline}")


def validate_marker_artifact(
    marker: dict[str, Any],
    artifact_key: str,
    artifact_path: Path,
    run_dir: Path,
) -> None:
    entry = marker.get("artifacts", {}).get(artifact_key)
    if not isinstance(entry, dict):
        raise ValueError(f"Missing marker artifact {artifact_key} for {run_dir.name}")
    recorded_path = (run_dir / str(entry.get("relpath", ""))).resolve()
    if recorded_path != artifact_path.resolve():
        raise ValueError(f"Marker artifact path mismatch for {run_dir.name}:{artifact_key}")
    if entry.get("sha256") != sha256_file(artifact_path):
        raise ValueError(f"Marker artifact hash mismatch for {run_dir.name}:{artifact_key}")


def audit_rows(
    input_root: Path,
    rules_path: Path,
    classifier_path: Path,
    scorer_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_static = [input_root, rules_path, classifier_path, scorer_path]
    required_static.extend(Path(config["reference"]) for config in BASELINES.values())
    missing = [str(path) for path in required_static if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required audit inputs: {missing}")

    static_hashes = {
        "audit_script": sha256_file(Path(__file__).resolve()),
        "rules_json": sha256_file(rules_path),
        "current_classifier": sha256_file(classifier_path),
        "current_occlusion_scorer": sha256_file(scorer_path),
        **{
            f"reference_{baseline}": sha256_file(Path(config["reference"]))
            for baseline, config in BASELINES.items()
        },
    }
    rules = load_rules(rules_path)
    reference_cache: dict[tuple[Path, str], tuple[list[Atom], dict[str, int]]] = {}
    vhh_cache: dict[tuple[Path, str], list[Atom]] = {}
    rows: list[dict[str, Any]] = []
    run_markers: list[dict[str, Any]] = []

    run_dirs = sorted(path for path in input_root.iterdir() if path.is_dir())
    if not run_dirs:
        raise ValueError(f"No run directories found under {input_root}")
    for run_dir in run_dirs:
        run_id = run_dir.name
        marker_path = run_dir / "postprocess.complete.json"
        marker = read_json_object(marker_path)
        validate_marker_contract(marker, marker_path, run_id, static_hashes)
        run_markers.append(
            {
                "run_id": run_id,
                "path": str(marker_path),
                "sha256": sha256_file(marker_path),
                "selected_models": marker.get("counts", {}).get("selected_models"),
            }
        )

        rank_path = run_dir / "reports/haddock3_model_ranks.csv"
        validate_marker_artifact(marker, "ranks", rank_path, run_dir)
        rank_rows = read_csv_unique(rank_path)
        expected_marker_models = {
            str(item["model"]) for item in marker.get("selected_pose_files", [])
        }
        if set(rank_rows) != expected_marker_models:
            raise ValueError(f"Rank/marker model set mismatch for {run_id}")
        if marker.get("counts", {}).get("selected_models") != len(rank_rows):
            raise ValueError(f"Marker selected-model count mismatch for {run_id}")
        marker_ranks = {
            str(item["model"]): require_int(item.get("haddock_rank"), "marker rank")
            for item in marker.get("selected_pose_files", [])
        }
        csv_ranks = {
            model: require_int(row.get("haddock_rank"), "rank CSV")
            for model, row in rank_rows.items()
        }
        if marker_ranks != csv_ranks:
            raise ValueError(f"Marker/rank CSV rank map mismatch for {run_id}")

        for baseline, baseline_config in BASELINES.items():
            classification_path = (
                run_dir / "reports" / f"{run_id}_{baseline}_blocker_classification.csv"
            )
            mechanism_path = (
                run_dir
                / f"{baseline}_baseline"
                / f"haddock3_top_model_mechanism_scores_{baseline}.csv"
            )
            summary_path = (
                run_dir
                / f"{baseline}_baseline"
                / f"cdr3_occlusion_summary_{baseline}.csv"
            )
            json_dir = run_dir / f"{baseline}_baseline/json"
            validate_marker_artifact(
                marker, f"classification_{baseline}", classification_path, run_dir
            )
            validate_marker_artifact(
                marker, f"mechanism_{baseline}", mechanism_path, run_dir
            )
            classification_rows = read_csv_unique(classification_path)
            mechanism_rows = read_csv_unique(mechanism_path)
            summary_rows = read_csv_unique(summary_path)
            json_paths: dict[str, Path] = {}
            suffix = f"_{baseline}_cdr_occlusion.json"
            for path in json_dir.glob(f"*{suffix}"):
                model = path.name[: -len(suffix)]
                if model in json_paths:
                    raise ValueError(f"Duplicate CDR JSON for {run_id}/{baseline}/{model}")
                json_paths[model] = path
            model_sets = {
                "rank": set(rank_rows),
                "classification": set(classification_rows),
                "mechanism": set(mechanism_rows),
                "summary": set(summary_rows),
                "json": set(json_paths),
            }
            if len({frozenset(values) for values in model_sets.values()}) != 1:
                raise ValueError(f"Model set mismatch for {run_id}/{baseline}: {model_sets}")

            for model in sorted(rank_rows, key=lambda item: require_int(rank_rows[item]["haddock_rank"], "rank")):
                rank_row = rank_rows[model]
                class_row = classification_rows[model]
                mechanism_row = mechanism_rows[model]
                summary_row = summary_rows[model]
                cdr_json_path = json_paths[model]
                cdr_json = read_json_object(cdr_json_path)

                rank = require_int(rank_row.get("haddock_rank"), f"{run_id}/{model}/rank")
                ranks = [
                    require_int(row.get("haddock_rank"), f"{run_id}/{baseline}/{model}/rank")
                    for row in (class_row, mechanism_row, summary_row)
                ]
                if any(value != rank for value in ranks):
                    raise ValueError(f"Rank mismatch for {run_id}/{baseline}/{model}")

                current_total = require_int(
                    cdr_json.get("total_occluding_residue_pair_count"),
                    f"{run_id}/{baseline}/{model}/current_total",
                )
                regions = cdr_json.get("regions")
                if not isinstance(regions, dict) or not isinstance(regions.get("CDR3"), dict):
                    raise ValueError(f"Missing CDR3 region in {cdr_json_path}")
                current_cdr3 = require_int(
                    regions["CDR3"].get("occluding_residue_pair_count"),
                    f"{run_id}/{baseline}/{model}/current_cdr3",
                )
                current_fraction = require_float(
                    regions["CDR3"].get("occluding_residue_pair_fraction_of_total"),
                    f"{run_id}/{baseline}/{model}/current_fraction",
                    maximum=1.0,
                )
                hotspot = require_float(
                    class_row.get("hotspot_overlap_count"),
                    f"{run_id}/{baseline}/{model}/hotspot",
                )

                source_consistency = all(
                    [
                        require_int(
                            class_row.get("total_vhh_pvrl2_residue_pair_occlusion"),
                            "classification total",
                        )
                        == current_total,
                        require_int(
                            class_row.get("cdr3_pvrl2_residue_pair_occlusion"),
                            "classification CDR3",
                        )
                        == current_cdr3,
                        close(
                            require_float(class_row.get("cdr3_occlusion_fraction"), "classification fraction"),
                            current_fraction,
                            tolerance=1e-6,
                        ),
                        require_int(
                            summary_row.get("total_vhh_pvrl2_residue_pair_occlusion"),
                            "summary total",
                        )
                        == current_total,
                        require_int(summary_row.get("cdr3_residue_pair_occlusion"), "summary CDR3")
                        == current_cdr3,
                        close(
                            require_float(
                                summary_row.get("cdr3_residue_pair_occlusion_fraction"),
                                "summary fraction",
                            ),
                            current_fraction,
                        ),
                        require_float(mechanism_row.get("hotspot_overlap_count"), "mechanism hotspot")
                        == hotspot,
                        require_int(
                            mechanism_row.get("pvrl2_vhh_occluding_contact_count"),
                            "mechanism total",
                        )
                        == current_total,
                        require_float(summary_row.get("hotspot_overlap_count"), "summary hotspot")
                        == hotspot,
                        mechanism_row.get("baseline") == baseline,
                        summary_row.get("baseline") == baseline,
                        mechanism_row.get("generation_receptor")
                        == marker["generation_receptor"],
                        summary_row.get("generation_receptor")
                        == marker["generation_receptor"],
                    ]
                )
                if not source_consistency:
                    raise ValueError(f"Stored source mismatch for {run_id}/{baseline}/{model}")

                cdr_ranges = cdr_json.get("cdr_ranges")
                if not isinstance(cdr_ranges, dict):
                    raise ValueError(f"Missing CDR ranges in {cdr_json_path}")
                for region in ("CDR1", "CDR2", "CDR3"):
                    if not str(cdr_ranges.get(region, "")).strip():
                        raise ValueError(f"Missing {region} range in {cdr_json_path}")
                cdr3_range = parse_range(str(cdr_ranges["CDR3"]))

                pose_path = Path(str(cdr_json.get("pose_pdb", "")))
                reference_path = Path(str(cdr_json.get("reference_pdb", "")))
                vhh_chain = str(cdr_json.get("vhh_chain", ""))
                pvrl2_chain = str(cdr_json.get("ref_pvrl2_chain", ""))
                cutoff = require_float(cdr_json.get("contact_cutoff_a"), "contact cutoff")
                expected_reference = Path(baseline_config["reference"]).resolve()
                if reference_path.resolve() != expected_reference:
                    raise ValueError(f"Unexpected reference for {run_id}/{baseline}/{model}")
                if pvrl2_chain != baseline_config["pvrl2_chain"] or not vhh_chain:
                    raise ValueError(f"Unexpected chain mapping for {run_id}/{baseline}/{model}")
                if not pose_path.is_file() or not reference_path.is_file():
                    raise FileNotFoundError(f"Missing pose/reference for {run_id}/{baseline}/{model}")
                try:
                    pose_path.resolve().relative_to(run_dir.resolve())
                except ValueError as error:
                    raise ValueError(
                        f"Aligned pose escapes the postprocessed run root: {pose_path}"
                    ) from error
                source_consistency = source_consistency and all(
                    [
                        Path(str(mechanism_row.get("pose_pdb", ""))).resolve()
                        == pose_path.resolve(),
                        Path(str(mechanism_row.get("reference_pdb", ""))).resolve()
                        == reference_path.resolve(),
                        mechanism_row.get("vhh_chain") == vhh_chain,
                        mechanism_row.get("ref_pvrl2_chain") == pvrl2_chain,
                        close(
                            require_float(
                                mechanism_row.get("contact_cutoff_a"),
                                "mechanism contact cutoff",
                            ),
                            cutoff,
                        ),
                    ]
                )
                if not source_consistency:
                    raise ValueError(f"Stored source metadata mismatch for {run_id}/{baseline}/{model}")

                reference_key = (reference_path.resolve(), pvrl2_chain)
                if reference_key not in reference_cache:
                    reference_atoms = list(iter_heavy_atoms(reference_path, pvrl2_chain))
                    reference_cache[reference_key] = (
                        reference_atoms,
                        reference_inventory(reference_atoms),
                    )
                reference_atoms, inventory = reference_cache[reference_key]
                vhh_key = (pose_path.resolve(), vhh_chain)
                if vhh_key not in vhh_cache:
                    vhh_cache[vhh_key] = list(iter_heavy_atoms(pose_path, vhh_chain))
                contact = contact_pair_summaries(
                    vhh_cache[vhh_key], reference_atoms, cutoff, cdr3_range
                )
                inclusive = contact["inclusive"]
                protein = contact["protein_only"]
                recomputed_total = int(inclusive["total_residue_pair_occlusion"])
                recomputed_cdr3 = int(inclusive["cdr3_residue_pair_occlusion"])
                recomputed_fraction = float(inclusive["cdr3_fraction"])
                protein_total = int(protein["total_residue_pair_occlusion"])
                protein_cdr3 = int(protein["cdr3_residue_pair_occlusion"])
                protein_fraction = float(protein["cdr3_fraction"])

                metric_match = (
                    recomputed_total == current_total
                    and recomputed_cdr3 == current_cdr3
                    and close(recomputed_fraction, current_fraction)
                )
                if not metric_match:
                    raise ValueError(
                        "Independent inclusive reproduction mismatch for "
                        f"{run_id}/{baseline}/{model}: "
                        f"stored=({current_total},{current_cdr3},{current_fraction}) "
                        f"recomputed=({recomputed_total},{recomputed_cdr3},{recomputed_fraction})"
                    )

                current_class = str(class_row.get("blocker_class", "")).strip()
                recomputed_class = classify_sensitivity(
                    hotspot, recomputed_total, recomputed_cdr3, recomputed_fraction, rules
                )
                class_match = current_class == recomputed_class
                if not class_match:
                    raise ValueError(f"Current class reproduction mismatch for {run_id}/{baseline}/{model}")
                protein_class = classify_sensitivity(
                    hotspot, protein_total, protein_cdr3, protein_fraction, rules
                )
                total_delta = recomputed_total - protein_total
                cdr3_delta = recomputed_cdr3 - protein_cdr3
                fraction_delta = recomputed_fraction - protein_fraction
                affected = total_delta != 0 or cdr3_delta != 0 or not close(fraction_delta, 0.0)

                row = {
                    "schema_version": ROW_SCHEMA_VERSION,
                    "run_id": run_id,
                    "pilot_id": marker["pilot_id"],
                    "source_candidate_id": marker["source_candidate_id"],
                    "generation_receptor": marker["generation_receptor"],
                    "seed_role": marker["seed_role"],
                    "baseline": baseline,
                    "model": model,
                    "haddock_rank": rank,
                    "aligned_pose_path": str(pose_path),
                    "aligned_pose_sha256": sha256_file(pose_path),
                    "cdr_json_path": str(cdr_json_path),
                    "cdr_json_sha256": sha256_file(cdr_json_path),
                    "reference_pdb": str(reference_path),
                    "reference_sha256": static_hashes[f"reference_{baseline}"],
                    "pvrl2_chain": pvrl2_chain,
                    "vhh_chain": vhh_chain,
                    "cdr1_range": cdr_ranges["CDR1"],
                    "cdr2_range": cdr_ranges["CDR2"],
                    "cdr3_range": cdr_ranges["CDR3"],
                    "contact_cutoff_a": csv_number(cutoff),
                    **{f"reference_{key}": value for key, value in inventory.items()},
                    "current_total_residue_pair_occlusion": current_total,
                    "recomputed_inclusive_total_residue_pair_occlusion": recomputed_total,
                    "protein_only_total_residue_pair_occlusion": protein_total,
                    "total_inflation_absolute": total_delta,
                    "total_current_to_protein_only_factor": csv_number(
                        safe_factor(recomputed_total, protein_total)
                    ),
                    "current_cdr3_residue_pair_occlusion": current_cdr3,
                    "recomputed_inclusive_cdr3_residue_pair_occlusion": recomputed_cdr3,
                    "protein_only_cdr3_residue_pair_occlusion": protein_cdr3,
                    "cdr3_inflation_absolute": cdr3_delta,
                    "cdr3_current_to_protein_only_factor": csv_number(
                        safe_factor(recomputed_cdr3, protein_cdr3)
                    ),
                    "current_cdr3_fraction": csv_number(current_fraction),
                    "recomputed_inclusive_cdr3_fraction": csv_number(recomputed_fraction),
                    "protein_only_cdr3_fraction": csv_number(protein_fraction),
                    "fraction_delta_current_minus_protein_only": csv_number(fraction_delta),
                    "hotspot_overlap_count": csv_number(hotspot),
                    "current_v1_1_class": current_class,
                    "recomputed_current_v1_1_class": recomputed_class,
                    "protein_only_sensitivity_class": protein_class,
                    "class_transition": f"{current_class}->{protein_class}",
                    "class_changed": bool_text(current_class != protein_class),
                    "affected": bool_text(affected),
                    "current_metric_reproduction_match": bool_text(metric_match),
                    "current_class_reproduction_match": bool_text(class_match),
                    "source_consistency_pass": bool_text(source_consistency),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
                rows.append(row)

    if not rows:
        raise ValueError("Audit produced no rows")
    return rows, {
        "static_hashes": static_hashes,
        "rules": rules,
        "run_markers": run_markers,
        "run_count": len(run_dirs),
        "reference_inventory": {
            baseline: reference_cache[(Path(config["reference"]).resolve(), str(config["pvrl2_chain"]))][1]
            for baseline, config in BASELINES.items()
        },
    }


def write_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Cannot calculate a quantile of an empty sequence")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: Sequence[float]) -> dict[str, float | int | None]:
    finite = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not finite:
        return {"count": 0, "min": None, "median": None, "mean": None, "p90": None, "max": None}
    return {
        "count": len(finite),
        "min": min(finite),
        "median": statistics.median(finite),
        "mean": statistics.fmean(finite),
        "p90": quantile(finite, 0.90),
        "max": max(finite),
    }


def build_audit(
    rows: Sequence[dict[str, Any]],
    evidence: dict[str, Any],
    input_root: Path,
    before_snapshot: dict[str, Any],
    after_snapshot: dict[str, Any],
    output_csv: Path,
    output_json: Path,
    output_report: Path,
) -> dict[str, Any]:
    row_count = len(rows)
    current_classes = Counter(str(row["current_v1_1_class"]) for row in rows)
    protein_classes = Counter(str(row["protein_only_sensitivity_class"]) for row in rows)
    transitions = Counter(str(row["class_transition"]) for row in rows)
    changed_rows = [row for row in rows if row["class_changed"] == "true"]
    affected_rows = [row for row in rows if row["affected"] == "true"]
    total_factors = [
        float(row["total_current_to_protein_only_factor"])
        for row in rows
        if row["total_current_to_protein_only_factor"] != ""
    ]
    cdr3_factors = [
        float(row["cdr3_current_to_protein_only_factor"])
        for row in rows
        if row["cdr3_current_to_protein_only_factor"] != ""
    ]
    fraction_deltas = [float(row["fraction_delta_current_minus_protein_only"]) for row in rows]
    unchanged = before_snapshot == after_snapshot
    if not unchanged:
        raise RuntimeError("Input root changed during the read-only audit")

    baseline_counts: dict[str, Any] = {}
    for baseline in BASELINES:
        baseline_rows = [row for row in rows if row["baseline"] == baseline]
        baseline_counts[baseline] = {
            "rows": len(baseline_rows),
            "current_class_counts": dict(
                sorted(Counter(str(row["current_v1_1_class"]) for row in baseline_rows).items())
            ),
            "protein_only_sensitivity_class_counts": dict(
                sorted(
                    Counter(str(row["protein_only_sensitivity_class"]) for row in baseline_rows).items()
                )
            ),
        }

    identifier = lambda row: f"{row['run_id']}|{row['baseline']}|{row['model']}"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": REJECTION_STATUS if affected_rows else "PASS_NO_HETATM_EFFECT_DETECTED",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": {
            "input_root": str(input_root),
            "description": "8-run revised smoke rejection diagnostic only",
            "full_pilot64_gold_read_or_validated": False,
            "run_data_source_policy": (
                "The postprocessed root is the sole run/output source. Frozen reference PDBs, "
                "rules, classifier, and scorer are read-only static trust dependencies."
            ),
        },
        "decision": {
            "v1_1_training_use": "BLOCK",
            "reason": (
                "Current PVRL2 occlusion semantics count reference HETATM residues as PVRL2 "
                "residue-pair occlusion and materially change current-rule classifications."
            ),
            "protein_only_result_role": "sensitivity classification comparison only",
            "required_next_gate": (
                "Create a versioned protein-only scorer, recalibrate success cases and thresholds, "
                "then rerun smoke, repeatability, and Pilot64 validation."
            ),
        },
        "counts": {
            "runs": evidence["run_count"],
            "baseline_model_rows": row_count,
            "unique_aligned_poses": len({row["aligned_pose_sha256"] for row in rows}),
            "current_metric_reproduced_rows": sum(
                row["current_metric_reproduction_match"] == "true" for row in rows
            ),
            "current_class_reproduced_rows": sum(
                row["current_class_reproduction_match"] == "true" for row in rows
            ),
            "source_consistency_pass_rows": sum(row["source_consistency_pass"] == "true" for row in rows),
            "total_count_inflation_rows": sum(int(row["total_inflation_absolute"]) > 0 for row in rows),
            "cdr3_count_inflation_rows": sum(int(row["cdr3_inflation_absolute"]) > 0 for row in rows),
            "fraction_changed_rows": sum(
                not close(float(row["fraction_delta_current_minus_protein_only"]), 0.0)
                for row in rows
            ),
            "affected_rows": len(affected_rows),
            "affected_fraction": len(affected_rows) / row_count,
            "class_changed_rows": len(changed_rows),
            "class_changed_fraction": len(changed_rows) / row_count,
        },
        "reference_inventory_heavy_atoms": {
            baseline: {
                "path": str(BASELINES[baseline]["reference"]),
                "sha256": evidence["static_hashes"][f"reference_{baseline}"],
                "pvrl2_chain": BASELINES[baseline]["pvrl2_chain"],
                **inventory,
            }
            for baseline, inventory in evidence["reference_inventory"].items()
        },
        "metric_definitions": {
            "contact_cutoff": "distance <= per-model contact_cutoff_a (currently 4.5 A)",
            "current": "PVRL2 reference ATOM and HETATM heavy atoms",
            "protein_only": "same calculation with PVRL2 reference ATOM heavy atoms only",
            "inflation_absolute": "current inclusive count - protein-only count",
            "current_to_protein_only_factor": (
                "current inclusive count / protein-only count; null in JSON and blank in CSV "
                "when protein-only denominator is zero"
            ),
            "fraction_delta": "current CDR3 fraction - protein-only CDR3 fraction; signed, not monotonic",
            "distribution_p90": "linear interpolation at position (n - 1) * 0.90",
        },
        "distributions": {
            "total_current_to_protein_only_factor": distribution(total_factors),
            "cdr3_current_to_protein_only_factor": distribution(cdr3_factors),
            "fraction_delta_current_minus_protein_only": distribution(fraction_deltas),
        },
        "class_counts": {
            "current_v1_1": dict(sorted(current_classes.items())),
            "protein_only_sensitivity": dict(sorted(protein_classes.items())),
            "by_baseline": baseline_counts,
        },
        "class_transition_counts": dict(sorted(transitions.items())),
        "changed_class_transition_counts": dict(
            sorted(Counter(str(row["class_transition"]) for row in changed_rows).items())
        ),
        "affected_row_identifiers": [identifier(row) for row in affected_rows],
        "class_changed_row_identifiers": [identifier(row) for row in changed_rows],
        "hashes": {
            **evidence["static_hashes"],
            "output_csv": sha256_file(output_csv),
            "run_markers": evidence["run_markers"],
        },
        "input_root_integrity": {
            "before": before_snapshot,
            "after": after_snapshot,
            "unchanged": unchanged,
        },
        "artifacts": {
            "row_csv": str(output_csv),
            "audit_json": str(output_json),
            "chinese_report": str(output_report),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }


def fmt_metric(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NA"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def write_report(path: Path, audit: dict[str, Any], audit_json_sha256: str) -> None:
    counts = audit["counts"]
    total_dist = audit["distributions"]["total_current_to_protein_only_factor"]
    cdr3_dist = audit["distributions"]["cdr3_current_to_protein_only_factor"]
    fraction_dist = audit["distributions"]["fraction_delta_current_minus_protein_only"]
    references = audit["reference_inventory_heavy_atoms"]
    current = audit["class_counts"]["current_v1_1"]
    protein = audit["class_counts"]["protein_only_sensitivity"]
    lines = [
        "# PVRIG V3-P2 V1.1 HETATM 污染拒绝诊断",
        "",
        f"- 审计状态：`{audit['status']}`",
        "- 范围：当前 8-run revised smoke；未读取、未验证完整 Pilot64 Gold 输出。",
        f"- 行数：{counts['baseline_model_rows']} 个 `run × baseline × model` 记录。",
        f"- 只读性：输入树审计前后 SHA256 快照一致 = `{str(audit['input_root_integrity']['unchanged']).lower()}`。",
        "",
        "## 结论",
        "",
        "当前 V1.1 遮挡计分把参考 PVRL2 链中的水和配体 `HETATM` 当作 PVRL2 残基，",
        "并计入 total/CDR3 residue-pair occlusion。该语义已经在全量 Pilot64 运行前被本审计拒绝，",
        "因此当前 V1.1 路径不得冻结为训练用 Docking Gold。",
        "",
        "这里的 protein-only 结果仅是 **sensitivity classification comparison（敏感性分类比较）**。",
        "它不是 V1.2 校准标签、不是 corrected Docking Gold，也不是实验结合或阻断真值。",
        "",
        "## 独立复现门",
        "",
        f"- 当前 inclusive total/CDR3/fraction 精确复现：{counts['current_metric_reproduced_rows']}/{counts['baseline_model_rows']}。",
        f"- 当前分类逻辑独立复现：{counts['current_class_reproduced_rows']}/{counts['baseline_model_rows']}。",
        f"- CSV/JSON/mechanism/rank 来源一致：{counts['source_consistency_pass_rows']}/{counts['baseline_model_rows']}。",
        "- 复算仅改变参考 PVRL2 的 record filter：`ATOM + HETATM` → `ATOM`；altloc、坐标、CDR 范围、4.5 Å cutoff 和 hotspot 均不变。",
        "",
        "## 参考结构污染清单",
        "",
        "| baseline | PVRL2 chain | protein ATOM / residues | HETATM / residues | HOH / residues | EDO / residues | other |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for baseline in BASELINES:
        item = references[baseline]
        lines.append(
            f"| {baseline.upper()} | {item['pvrl2_chain']} | "
            f"{item['protein_atom_count']} / {item['protein_residue_count']} | "
            f"{item['hetatm_atom_count']} / {item['hetatm_residue_count']} | "
            f"{item['hoh_atom_count']} / {item['hoh_residue_count']} | "
            f"{item['edo_atom_count']} / {item['edo_residue_count']} | "
            f"{item['other_hetatm_atom_count']} / {item['other_hetatm_residue_count']} |"
        )
    lines.extend(
        [
            "",
            "## 污染影响",
            "",
            f"- total count 受影响：{counts['total_count_inflation_rows']}/{counts['baseline_model_rows']}。",
            f"- CDR3 count 受影响：{counts['cdr3_count_inflation_rows']}/{counts['baseline_model_rows']}。",
            f"- CDR3 fraction 改变：{counts['fraction_changed_rows']}/{counts['baseline_model_rows']}。",
            f"- 当前规则下分类变化：{counts['class_changed_rows']}/{counts['baseline_model_rows']}（{counts['class_changed_fraction']:.2%}）。",
            "",
            "| 指标 | min | median | mean | p90 | max |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            "| current/protein-only total factor | "
            + " | ".join(fmt_metric(total_dist[key]) for key in ("min", "median", "mean", "p90", "max"))
            + " |",
            "| current/protein-only CDR3 factor | "
            + " | ".join(fmt_metric(cdr3_dist[key]) for key in ("min", "median", "mean", "p90", "max"))
            + " |",
            "| current fraction - protein-only fraction | "
            + " | ".join(fmt_metric(fraction_dist[key], 5) for key in ("min", "median", "mean", "p90", "max"))
            + " |",
            "",
            "fraction delta 有正有负，不能统一描述为 fraction 膨胀。",
            "",
            "## 当前规则下的敏感性分类比较",
            "",
            "| class | current V1.1 | protein-only sensitivity |",
            "| --- | ---: | ---: |",
        ]
    )
    for label in sorted(set(current) | set(protein)):
        lines.append(f"| `{label}` | {current.get(label, 0)} | {protein.get(label, 0)} |")
    lines.extend(["", "分类 transition：", ""])
    for transition, count in audit["changed_class_transition_counts"].items():
        lines.append(f"- `{transition}`：{count}")
    lines.extend(
        [
            "",
            "变化行：",
            "",
            *[f"- `{identifier}`" for identifier in audit["class_changed_row_identifiers"]],
            "",
            "## 科学处置",
            "",
            "1. 保留当前 V1.1 scorer、postprocessor 和 smoke 输出不变，作为被拒绝版本的 provenance。",
            "2. 新建版本化 protein-only scorer；不能在原文件上修补。",
            "3. 用 11 条成功案例和匹配 decoy 重新校准连续指标、A/B/C/E 阈值与双 baseline 规则。",
            "4. 重跑 8-run smoke，并重新执行独立双构象、重复性和数值闭环门。",
            "5. 只有新版本通过后才运行/冻结 Pilot64 Gold；本报告中的 sensitivity class 不得直接训练。",
            "",
            "## 证据与边界",
            "",
            f"- 行级 CSV：`{audit['artifacts']['row_csv']}`",
            f"- 机器审计 JSON：`{audit['artifacts']['audit_json']}`",
            f"- CSV SHA256：`{audit['hashes']['output_csv']}`",
            f"- JSON SHA256：`{audit_json_sha256}`",
            f"- 当前 scorer SHA256：`{audit['hashes']['current_occlusion_scorer']}`",
            f"- 当前 classifier SHA256：`{audit['hashes']['current_classifier']}`",
            f"- rules SHA256：`{audit['hashes']['rules_json']}`",
            "",
            f"> {audit['claim_boundary']}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_root = args.input_root.resolve()
    before_snapshot = tree_digest(input_root)
    rows, evidence = audit_rows(
        input_root,
        args.rules_json.resolve(),
        args.classifier_path.resolve(),
        args.scorer_path.resolve(),
    )
    after_snapshot = tree_digest(input_root)
    write_csv(args.output_csv, rows)
    audit = build_audit(
        rows,
        evidence,
        input_root,
        before_snapshot,
        after_snapshot,
        args.output_csv,
        args.output_json,
        args.output_report,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_report(args.output_report, audit, sha256_file(args.output_json))
    print(
        json.dumps(
            {
                "status": audit["status"],
                "runs": audit["counts"]["runs"],
                "rows": audit["counts"]["baseline_model_rows"],
                "affected_rows": audit["counts"]["affected_rows"],
                "class_changed_rows": audit["counts"]["class_changed_rows"],
                "output_csv": str(args.output_csv),
                "output_json": str(args.output_json),
                "output_report": str(args.output_report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
