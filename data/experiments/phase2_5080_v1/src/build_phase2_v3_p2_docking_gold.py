#!/usr/bin/env python3
"""Build and validate the Pilot64 PVRIG computational docking gold set.

The gold label is a reproducible summary of the frozen independent 8X6B and
9E6Y HADDOCK pipelines.  It is not experimental evidence of binding, affinity,
or PVRIG:PVRL2 blockade.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent

DEFAULT_SELECTION_MANIFEST = (
    EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv"
)
DEFAULT_PACKAGE_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package"
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/run_manifest.csv"
DEFAULT_POSTPROCESSED_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_postprocessed"
)
DEFAULT_SYNC_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_node1_selected"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_gold"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_docking_gold_audit.json"
DEFAULT_REPORT = EXP_DIR / "reports/PVRIG_V3_P2_DOCKING_GOLD_VALIDATION_ZH.md"

CLAIM_BOUNDARY = (
    "computational docking gold from frozen independent 8X6B/9E6Y HADDOCK "
    "pipelines; not experimental binding, affinity, or blocking truth"
)
RECEPTORS = ("8x6b", "9e6y")
SEED_ROLES = ("main", "replicate")
FROZEN_RIGIDBODY_SEEDS = {
    ("8x6b", "main"): 917,
    ("8x6b", "replicate"): 10917,
    ("9e6y", "main"): 20917,
    ("9e6y", "replicate"): 30917,
}
FROZEN_TOPOAA_SEED = 917
FROZEN_RIGIDBODY_TOLERANCE = 5.0
FROZEN_FLEXREF_TOLERANCE = 10.0
EXPECTED_PILOTS = 64
EXPECTED_REPLICATE_PILOTS = 16
EXPECTED_MAIN_RUNS = 128
EXPECTED_REPLICATE_RUNS = 32
EXPECTED_TOTAL_RUNS = 160
MIN_SELECTED_POSES = 8
MIN_POSE_CLUSTERS = 2
MODEL_RE = re.compile(r"cluster_(\d+)_model_(\d+)$")
VALID_BLOCKER_CLASSES = {
    "BLOCKER_LIKE_A",
    "BLOCKER_PLAUSIBLE_B",
    "BINDER_LIKE_C",
    "EVIDENCE_INFERENCE_ONLY_E",
}
TIER_TO_LEVEL = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    output_fields = list(fields)
    for row in rows:
        for field in row:
            if field not in output_fields:
                output_fields.append(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=output_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def parse_int(value: Any, field: str) -> int:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} is not numeric: {value!r}") from error
    if not parsed.is_integer():
        raise ValueError(f"{field} is not an integer: {value!r}")
    return int(parsed)


def parse_float(value: Any, field: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} is not numeric: {value!r}") from error
    if not math.isfinite(parsed):
        raise ValueError(f"{field} is not finite: {value!r}")
    return parsed


def pose_relevance(
    blocker_like_count: int,
    plausible_count: int,
    binder_like_count: int,
) -> int:
    """Map dual-baseline class counts to the preregistered ordinal relevance."""
    if blocker_like_count >= 2:
        return 4
    if blocker_like_count == 1:
        return 3
    if plausible_count >= 1:
        return 2
    if binder_like_count >= 1:
        return 1
    return 0


def pose_weight(rank: float, poses_in_same_cluster: int) -> float:
    if rank < 1 or poses_in_same_cluster < 1:
        raise ValueError("rank and poses_in_same_cluster must both be positive")
    return 1.0 / math.log2(rank + 1.0) / poses_in_same_cluster


def weighted_receptor_score(pose_rows: Sequence[Mapping[str, Any]]) -> float:
    weights = [float(row["pose_weight"]) for row in pose_rows]
    if not weights or sum(weights) <= 0:
        raise ValueError("At least one positive pose weight is required")
    return sum(weight * int(row["relevance"]) for weight, row in zip(weights, pose_rows)) / sum(weights)


def stable_tier(cluster_relevance: Mapping[str, int] | Iterable[tuple[str, int]]) -> tuple[str, int, int]:
    """Return the highest relevance supported by at least two unique clusters."""
    items = cluster_relevance.items() if isinstance(cluster_relevance, Mapping) else cluster_relevance
    maxima: dict[str, int] = {}
    for cluster_id, relevance in items:
        maxima[cluster_id] = max(maxima.get(cluster_id, 0), int(relevance))
    for relevance, tier in ((4, "G1"), (3, "G2"), (2, "G3"), (1, "G4")):
        support = sum(value >= relevance for value in maxima.values())
        if support >= 2:
            return tier, relevance, support
    return "G5", 0, len(maxima)


def average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    output = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = ((cursor + 1) + end) / 2.0
        for index in order[cursor:end]:
            output[index] = rank
        cursor = end
    return output


def pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    x_centered = [value - x_mean for value in x]
    y_centered = [value - y_mean for value in y]
    denominator = math.sqrt(
        sum(value * value for value in x_centered)
        * sum(value * value for value in y_centered)
    )
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(x_centered, y_centered)) / denominator


def spearman_with_ties(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y):
        raise ValueError("Spearman inputs must have equal length")
    return pearson(average_ranks(x), average_ranks(y))


def weighted_cohen_kappa(
    first: Sequence[str],
    second: Sequence[str],
    weighting: str = "quadratic",
) -> float | None:
    """Five-level weighted Cohen kappa with fixed preregistered G1..G5 order."""
    if len(first) != len(second):
        raise ValueError("Kappa inputs must have equal length")
    if not first:
        return None
    if weighting not in {"quadratic", "linear"}:
        raise ValueError("weighting must be 'quadratic' or 'linear'")
    levels = ["G1", "G2", "G3", "G4", "G5"]
    lookup = {value: index for index, value in enumerate(levels)}
    if any(value not in lookup for value in [*first, *second]):
        raise ValueError("Kappa tiers must be G1..G5")
    size = len(levels)
    total = len(first)
    observed = [[0.0] * size for _ in range(size)]
    left = [0.0] * size
    right = [0.0] * size
    for left_value, right_value in zip(first, second):
        i, j = lookup[left_value], lookup[right_value]
        observed[i][j] += 1.0 / total
        left[i] += 1.0 / total
        right[j] += 1.0 / total

    def cost(i: int, j: int) -> float:
        distance = abs(i - j) / (size - 1)
        return distance * distance if weighting == "quadratic" else distance

    observed_cost = sum(cost(i, j) * observed[i][j] for i in range(size) for j in range(size))
    expected_cost = sum(cost(i, j) * left[i] * right[j] for i in range(size) for j in range(size))
    if expected_cost == 0:
        return 1.0 if observed_cost == 0 else None
    return 1.0 - observed_cost / expected_cost


def cluster_from_model(model: str) -> str:
    match = MODEL_RE.fullmatch(model)
    if not match:
        raise ValueError(f"Unexpected HADDOCK model name: {model!r}")
    return f"cluster_{int(match.group(1))}"


def resolve_evidence_path(root: Path, row: Mapping[str, str], field: str, fallback: str) -> Path:
    relative = row.get(field, "").strip() or fallback
    path = Path(relative)
    return path if path.is_absolute() else root / path


def read_toml(path: Path) -> dict[str, Any]:
    """Read the scalar subset needed from HADDOCK cfg files on Python 3.10.

    HADDOCK's generated ``params.cfg`` files are TOML, but the production
    controller still uses Python 3.10 without ``tomllib``/``tomli``.  The gold
    gate only needs scalar module parameters, so multiline arrays and tables
    outside those modules can safely be ignored.
    """
    document: dict[str, Any] = {}
    current = document
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section or section.startswith("["):
                continue
            current = document
            for part in section.split("."):
                current = current.setdefault(part, {})
            continue
        if "=" not in line:
            continue
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key or not raw_value or raw_value in {"[", "{"}:
            continue
        lowered = raw_value.lower()
        if lowered in {"true", "false"}:
            value: Any = lowered == "true"
        else:
            try:
                value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError):
                try:
                    value = float(raw_value)
                    if value.is_integer() and not any(character in raw_value.lower() for character in (".", "e")):
                        value = int(value)
                except ValueError:
                    continue
        current[key] = value
    return document


def add_check(checks: dict[str, bool], errors: list[str], name: str, passed: bool, detail: str) -> None:
    checks[name] = bool(passed)
    if not passed:
        errors.append(f"{name}:{detail}")


def run_protocol_checks(
    row: Mapping[str, str],
    sync_root: Path,
) -> tuple[dict[str, Any], list[str]]:
    """Validate the declared protocol plus synced completion/config evidence."""
    run_id = row.get("run_id", "")
    receptor = row.get("receptor_id", "").lower()
    seed_role = row.get("seed_role", "").lower()
    checks: dict[str, bool] = {}
    errors: list[str] = []
    evidence: dict[str, Any] = {}
    expected_seed = FROZEN_RIGIDBODY_SEEDS.get((receptor, seed_role))
    if expected_seed is None:
        add_check(checks, errors, "known_receptor_seed_role", False, f"{receptor}/{seed_role}")
        return {"checks": checks, **evidence}, errors

    def declared_int(field: str, expected: int) -> None:
        try:
            actual = parse_int(row.get(field, ""), field)
            add_check(checks, errors, f"manifest_{field}", actual == expected, f"{actual}!={expected}")
        except ValueError as error:
            add_check(checks, errors, f"manifest_{field}", False, str(error))

    declared_int("iniseed", expected_seed)
    declared_int("rigidbody_iniseed", expected_seed)
    declared_int("topoaa_iniseed", FROZEN_TOPOAA_SEED)
    sampling = 0
    try:
        sampling = parse_int(row.get("rigidbody_sampling", ""), "rigidbody_sampling")
        add_check(checks, errors, "manifest_rigidbody_sampling", sampling > 0, str(sampling))
    except ValueError as error:
        add_check(checks, errors, "manifest_rigidbody_sampling", False, str(error))
    if sampling:
        declared_int("rigidbody_seed_start", expected_seed + 1)
        declared_int("rigidbody_seed_end", expected_seed + sampling)
    for field, expected in (
        ("rigidbody_tolerance", FROZEN_RIGIDBODY_TOLERANCE),
        ("flexref_tolerance", FROZEN_FLEXREF_TOLERANCE),
    ):
        try:
            actual = parse_float(row.get(field, ""), field)
            add_check(checks, errors, f"manifest_{field}", actual == expected, f"{actual}!={expected}")
        except ValueError as error:
            add_check(checks, errors, f"manifest_{field}", False, str(error))
    try:
        relaxed = parse_bool(row.get("tolerance_relaxed", ""))
        add_check(checks, errors, "manifest_no_tolerance_relaxation", not relaxed, str(relaxed))
        evidence["tolerance_relaxed"] = relaxed
    except ValueError as error:
        add_check(checks, errors, "manifest_no_tolerance_relaxation", False, str(error))
        evidence["tolerance_relaxed"] = True

    config_path = resolve_evidence_path(sync_root, row, "config_relpath", f"runs/{run_id}/{run_id}.cfg")
    completion_path = resolve_evidence_path(
        sync_root, row, "completion_relpath", f"runs/{run_id}/{run_id}.complete.json"
    )
    run_dir = resolve_evidence_path(sync_root, row, "run_dir_relpath", f"runs/{run_id}/run_{run_id}")
    evidence.update(
        {
            "config_path": str(config_path),
            "completion_path": str(completion_path),
            "run_dir": str(run_dir),
        }
    )
    add_check(checks, errors, "synced_config_present", config_path.is_file(), str(config_path))
    add_check(checks, errors, "synced_completion_present", completion_path.is_file(), str(completion_path))

    if config_path.is_file():
        try:
            config_sha = sha256_file(config_path)
            evidence["config_sha256_observed"] = config_sha
            add_check(
                checks,
                errors,
                "config_sha_matches_manifest",
                config_sha == row.get("config_sha256", ""),
                f"{config_sha}!={row.get('config_sha256', '')}",
            )
            config = read_toml(config_path)
            rigidbody = config.get("rigidbody", {})
            flexref = config.get("flexref", {})
            topoaa = config.get("topoaa", {})
            evidence["tolerance_relaxed"] = bool(evidence.get("tolerance_relaxed")) or (
                float(rigidbody.get("tolerance", math.inf)) > FROZEN_RIGIDBODY_TOLERANCE
                or float(flexref.get("tolerance", math.inf)) > FROZEN_FLEXREF_TOLERANCE
            )
            add_check(
                checks,
                errors,
                "config_rigidbody_iniseed",
                rigidbody.get("iniseed") == expected_seed,
                f"{rigidbody.get('iniseed')}!={expected_seed}",
            )
            add_check(
                checks,
                errors,
                "config_topoaa_iniseed",
                topoaa.get("iniseed") == FROZEN_TOPOAA_SEED,
                f"{topoaa.get('iniseed')}!={FROZEN_TOPOAA_SEED}",
            )
            add_check(
                checks,
                errors,
                "config_rigidbody_tolerance",
                float(rigidbody.get("tolerance", math.nan)) == FROZEN_RIGIDBODY_TOLERANCE,
                str(rigidbody.get("tolerance")),
            )
            add_check(
                checks,
                errors,
                "config_flexref_tolerance",
                float(flexref.get("tolerance", math.nan)) == FROZEN_FLEXREF_TOLERANCE,
                str(flexref.get("tolerance")),
            )
            add_check(
                checks,
                errors,
                "config_sampling_matches_manifest",
                rigidbody.get("sampling") == sampling,
                f"{rigidbody.get('sampling')}!={sampling}",
            )
        except Exception as error:  # malformed evidence must fail the gate, not abort the audit
            add_check(checks, errors, "config_parse", False, f"{type(error).__name__}:{error}")

    completion: dict[str, Any] = {}
    if completion_path.is_file():
        try:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            if completion.get("tolerance_relaxed") is not False:
                evidence["tolerance_relaxed"] = True
            evidence["completion_status"] = completion.get("status", "")
            evidence["completion_pose_count"] = completion.get("pose_count", "")
            evidence["completion_cluster_count"] = completion.get("cluster_count", "")
            add_check(checks, errors, "completion_run_id", completion.get("run_id") == run_id, str(completion.get("run_id")))
            add_check(
                checks,
                errors,
                "completion_status",
                completion.get("status") in {"PASS", "PASS_DOCKING_OUTPUT_COMPLETE"},
                str(completion.get("status")),
            )
            add_check(checks, errors, "completion_exit_code", completion.get("exit_code") == 0, str(completion.get("exit_code")))
            add_check(
                checks,
                errors,
                "completion_rigidbody_iniseed",
                completion.get("iniseed") == expected_seed,
                f"{completion.get('iniseed')}!={expected_seed}",
            )
            add_check(
                checks,
                errors,
                "completion_no_tolerance_relaxation",
                completion.get("tolerance_relaxed") is False,
                str(completion.get("tolerance_relaxed")),
            )
            add_check(
                checks,
                errors,
                "completion_haddock3_version_contract",
                completion.get("haddock3_version_contract") == row.get("haddock3_version_contract", ""),
                f"{completion.get('haddock3_version_contract')}!={row.get('haddock3_version_contract', '')}",
            )
            add_check(
                checks,
                errors,
                "completion_pose_count",
                parse_int(completion.get("pose_count", ""), "pose_count") >= MIN_SELECTED_POSES,
                str(completion.get("pose_count")),
            )
            add_check(
                checks,
                errors,
                "completion_cluster_count",
                parse_int(completion.get("cluster_count", ""), "cluster_count") >= MIN_POSE_CLUSTERS,
                str(completion.get("cluster_count")),
            )
            for field in ("config_sha256", "monomer_sha256", "receptor_sha256"):
                add_check(
                    checks,
                    errors,
                    f"completion_{field}",
                    completion.get(field) == row.get(field, ""),
                    f"{completion.get(field)}!={row.get(field, '')}",
                )
        except Exception as error:
            add_check(checks, errors, "completion_parse", False, f"{type(error).__name__}:{error}")

    params_path = run_dir / "1_rigidbody/params.cfg"
    io_path = run_dir / "1_rigidbody/io.json"
    add_check(checks, errors, "runtime_rigidbody_params_present", params_path.is_file(), str(params_path))
    if params_path.is_file():
        try:
            params_document = read_toml(params_path)
            params = params_document.get("rigidbody", params_document)
            add_check(
                checks,
                errors,
                "runtime_rigidbody_iniseed",
                params.get("iniseed") == expected_seed,
                f"{params.get('iniseed')}!={expected_seed}",
            )
            add_check(
                checks,
                errors,
                "runtime_rigidbody_tolerance",
                float(params.get("tolerance", math.nan)) == FROZEN_RIGIDBODY_TOLERANCE,
                str(params.get("tolerance")),
            )
            add_check(
                checks,
                errors,
                "runtime_rigidbody_sampling",
                params.get("sampling") == sampling,
                f"{params.get('sampling')}!={sampling}",
            )
        except Exception as error:
            add_check(checks, errors, "runtime_rigidbody_params_parse", False, f"{type(error).__name__}:{error}")
    add_check(checks, errors, "runtime_rigidbody_io_present", io_path.is_file(), str(io_path))
    if io_path.is_file():
        try:
            runtime_io = json.loads(io_path.read_text(encoding="utf-8"))
            outputs = runtime_io.get("output", [])
            observed_seeds = [parse_int(item.get("seed", ""), "runtime_output_seed") for item in outputs]
            expected_seeds = list(range(expected_seed + 1, expected_seed + sampling + 1))
            evidence["runtime_rigidbody_output_count"] = len(outputs)
            evidence["runtime_rigidbody_seed_start"] = min(observed_seeds) if observed_seeds else ""
            evidence["runtime_rigidbody_seed_end"] = max(observed_seeds) if observed_seeds else ""
            add_check(
                checks,
                errors,
                "runtime_rigidbody_output_count",
                len(outputs) == sampling,
                f"{len(outputs)}!={sampling}",
            )
            add_check(
                checks,
                errors,
                "runtime_rigidbody_seed_set",
                sorted(observed_seeds) == expected_seeds,
                f"observed={sorted(observed_seeds)};expected={expected_seeds}",
            )
        except Exception as error:
            add_check(checks, errors, "runtime_rigidbody_io_parse", False, f"{type(error).__name__}:{error}")
    evidence["checks"] = checks
    evidence["monomer_sha256"] = row.get("monomer_sha256", "")
    evidence["frozen_rigidbody_iniseed"] = expected_seed
    return evidence, errors


def indexed_rows(path: Path, label: str, errors: list[str]) -> dict[str, dict[str, str]]:
    if not path.is_file():
        errors.append(f"missing_{label}:{path}")
        return {}
    try:
        rows = read_csv(path)
    except Exception as error:
        errors.append(f"read_{label}:{type(error).__name__}:{error}")
        return {}
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        model = row.get("model", "").strip()
        if not model:
            errors.append(f"{label}_missing_model")
        elif model in output:
            errors.append(f"{label}_duplicate_model:{model}")
        else:
            output[model] = row
    return output


def evaluate_postprocessed_run(
    row: Mapping[str, str],
    postprocessed_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    run_id = row["run_id"]
    receptor = row["receptor_id"].lower()
    run_root = postprocessed_root / run_id
    reports = run_root / "reports"
    errors: list[str] = []
    consensus = indexed_rows(reports / f"{run_id}_dual_baseline_consensus.csv", "consensus", errors)
    classifications = {
        baseline: indexed_rows(
            reports / f"{run_id}_{baseline}_blocker_classification.csv",
            f"classification_{baseline}",
            errors,
        )
        for baseline in RECEPTORS
    }
    mechanisms = {
        baseline: indexed_rows(
            run_root / f"{baseline}_baseline/haddock3_top_model_mechanism_scores_{baseline}.csv",
            f"mechanism_{baseline}",
            errors,
        )
        for baseline in RECEPTORS
    }
    canonical = indexed_rows(
        reports / f"{run_id}_canonical_contact_summary.csv", "canonical_contact_summary", errors
    )
    model_set = set(consensus)
    for label, index in [
        *((f"classification_{key}", value) for key, value in classifications.items()),
        *((f"mechanism_{key}", value) for key, value in mechanisms.items()),
        ("canonical_contact_summary", canonical),
    ]:
        if set(index) != model_set:
            errors.append(
                f"model_set_{label}:missing={sorted(model_set-set(index))};extra={sorted(set(index)-model_set)}"
            )
    contact_failures = sum(item.get("status") != "PASS" for item in canonical.values())
    if len(canonical) != len(model_set):
        contact_failures += abs(len(model_set) - len(canonical))

    cluster_counts: Counter[str] = Counter()
    for model in model_set:
        try:
            cluster_counts[cluster_from_model(model)] += 1
        except ValueError as error:
            errors.append(str(error))
    poses: list[dict[str, Any]] = []
    required_mechanism = (
        "hotspot_overlap_count",
        "pvrig_vhh_contact_pair_count",
        "pvrl2_vhh_occluding_contact_count",
    )
    required_classification = (
        "hotspot_overlap_count",
        "total_vhh_pvrl2_residue_pair_occlusion",
        "cdr3_pvrl2_residue_pair_occlusion",
        "cdr3_occlusion_fraction",
        "blocker_class",
    )
    for model, consensus_row in sorted(consensus.items()):
        try:
            cluster = cluster_from_model(model)
            classes: list[str] = []
            for baseline in RECEPTORS:
                class_row = classifications[baseline].get(model, {})
                mechanism_row = mechanisms[baseline].get(model, {})
                missing_class = [field for field in required_classification if class_row.get(field, "") == ""]
                missing_mechanism = [field for field in required_mechanism if mechanism_row.get(field, "") == ""]
                if missing_class:
                    errors.append(f"classification_{baseline}_incomplete:{model}:{','.join(missing_class)}")
                if missing_mechanism:
                    errors.append(f"mechanism_{baseline}_incomplete:{model}:{','.join(missing_mechanism)}")
                blocker_class = class_row.get("blocker_class", "")
                if blocker_class not in VALID_BLOCKER_CLASSES:
                    errors.append(f"classification_{baseline}_invalid:{model}:{blocker_class}")
                classes.append(blocker_class)
            counts = Counter(classes)
            declared_counts = {
                "BLOCKER_LIKE_A": parse_int(consensus_row.get("blocker_like_count", ""), "blocker_like_count"),
                "BLOCKER_PLAUSIBLE_B": parse_int(consensus_row.get("plausible_count", ""), "plausible_count"),
                "BINDER_LIKE_C": parse_int(consensus_row.get("binder_like_count", ""), "binder_like_count"),
                "EVIDENCE_INFERENCE_ONLY_E": parse_int(consensus_row.get("evidence_only_count", ""), "evidence_only_count"),
            }
            if any(counts[key] != value for key, value in declared_counts.items()):
                errors.append(f"consensus_count_mismatch:{model}")
            baseline_count = parse_int(consensus_row.get("baseline_count", ""), "baseline_count")
            if baseline_count != 2 or sum(declared_counts.values()) != 2:
                errors.append(f"consensus_not_dual_baseline:{model}:{baseline_count}/{sum(declared_counts.values())}")
            rank = parse_float(consensus_row.get("best_haddock_rank", ""), "best_haddock_rank")
            relevance = pose_relevance(
                declared_counts["BLOCKER_LIKE_A"],
                declared_counts["BLOCKER_PLAUSIBLE_B"],
                declared_counts["BINDER_LIKE_C"],
            )
            weight = pose_weight(rank, cluster_counts[cluster])
            poses.append(
                {
                    "schema_version": "phase2_v3_p2_docking_gold_pose_v1",
                    "pilot_id": row["pilot_id"],
                    "source_candidate_id": row.get("source_candidate_id", ""),
                    "run_id": run_id,
                    "receptor_id": receptor,
                    "seed_role": row["seed_role"],
                    "model": model,
                    "cluster_id": cluster,
                    "receptor_cluster_id": f"{receptor}:{cluster}",
                    "haddock_rank": f"{rank:g}",
                    "blocker_like_count": declared_counts["BLOCKER_LIKE_A"],
                    "plausible_count": declared_counts["BLOCKER_PLAUSIBLE_B"],
                    "binder_like_count": declared_counts["BINDER_LIKE_C"],
                    "evidence_only_count": declared_counts["EVIDENCE_INFERENCE_ONLY_E"],
                    "relevance": relevance,
                    "poses_in_same_cluster": cluster_counts[cluster],
                    "rank_weight": f"{1.0 / math.log2(rank + 1.0):.10f}",
                    "pose_weight": f"{weight:.10f}",
                    "weighted_relevance": f"{weight * relevance:.10f}",
                    "baseline_classes": consensus_row.get("baseline_classes", ""),
                    "canonical_contact_status": canonical.get(model, {}).get("status", ""),
                    "canonical_residue_pair_count": canonical.get(model, {}).get("canonical_residue_pair_count", ""),
                    "claim_boundary": CLAIM_BOUNDARY,
                }
            )
        except Exception as error:
            errors.append(f"pose_{model}:{type(error).__name__}:{error}")

    cluster_count = len(cluster_counts)
    if len(poses) < MIN_SELECTED_POSES:
        errors.append(f"selected_poses:{len(poses)}<{MIN_SELECTED_POSES}")
    if cluster_count < MIN_POSE_CLUSTERS:
        errors.append(f"pose_clusters:{cluster_count}<{MIN_POSE_CLUSTERS}")
    score = weighted_receptor_score(poses) if poses else None
    tier, threshold, support = stable_tier(
        (pose["receptor_cluster_id"], int(pose["relevance"])) for pose in poses
    )
    evidence = {
        "selected_poses": len(poses),
        "pose_clusters": cluster_count,
        "r_receptor": score,
        "stable_tier": tier,
        "stable_relevance_threshold": threshold,
        "stable_supporting_clusters": support,
        "canonical_contact_pose_rows": len(canonical),
        "contact_failures": contact_failures,
    }
    return poses, evidence, errors


def manifest_contract(
    selection_rows: Sequence[Mapping[str, str]],
    run_rows: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Mapping[str, str]], list[str]]:
    errors: list[str] = []
    selection: dict[str, Mapping[str, str]] = {}
    for row in selection_rows:
        pilot_id = row.get("pilot_id", "")
        if not pilot_id or pilot_id in selection:
            errors.append(f"selection_duplicate_or_empty:{pilot_id}")
        else:
            selection[pilot_id] = row
    replicate = {
        pilot_id for pilot_id, row in selection.items() if parse_bool(row.get("replicate_seed_required", ""))
    }
    if len(selection) != EXPECTED_PILOTS:
        errors.append(f"selection_count:{len(selection)}!={EXPECTED_PILOTS}")
    if len(replicate) != EXPECTED_REPLICATE_PILOTS:
        errors.append(f"replicate_pilot_count:{len(replicate)}!={EXPECTED_REPLICATE_PILOTS}")

    runs_by_id: dict[str, Mapping[str, str]] = {}
    observed_keys: Counter[tuple[str, str, str]] = Counter()
    for row in run_rows:
        run_id = row.get("run_id", "")
        if not run_id or run_id in runs_by_id:
            errors.append(f"run_duplicate_or_empty:{run_id}")
        else:
            runs_by_id[run_id] = row
        key = (row.get("pilot_id", ""), row.get("receptor_id", "").lower(), row.get("seed_role", "").lower())
        observed_keys[key] += 1
    expected_keys = {
        (pilot_id, receptor, "main") for pilot_id in selection for receptor in RECEPTORS
    } | {
        (pilot_id, receptor, "replicate") for pilot_id in replicate for receptor in RECEPTORS
    }
    observed_set = set(observed_keys)
    if len(run_rows) != EXPECTED_TOTAL_RUNS:
        errors.append(f"run_count:{len(run_rows)}!={EXPECTED_TOTAL_RUNS}")
    for key, count in observed_keys.items():
        if count != 1:
            errors.append(f"run_key_count:{key}:{count}")
    if observed_set != expected_keys:
        errors.append(f"run_key_missing:{sorted(expected_keys-observed_set)}")
        errors.append(f"run_key_extra:{sorted(observed_set-expected_keys)}")
    return runs_by_id, errors


def combine_candidate(
    pilot: Mapping[str, str],
    receptor_rows: Sequence[Mapping[str, Any]],
    pose_rows: Sequence[Mapping[str, Any]],
    seed_role: str,
) -> dict[str, Any] | None:
    selected_receptors = {
        row["receptor_id"]: row
        for row in receptor_rows
        if row["pilot_id"] == pilot["pilot_id"] and row["seed_role"] == seed_role
    }
    if set(selected_receptors) != set(RECEPTORS):
        return None
    scores = [selected_receptors[receptor]["r_receptor_raw"] for receptor in RECEPTORS]
    if any(score is None for score in scores):
        return None
    selected_poses = [
        row
        for row in pose_rows
        if row["pilot_id"] == pilot["pilot_id"] and row["seed_role"] == seed_role
    ]
    tier, threshold, support = stable_tier(
        (row["receptor_cluster_id"], int(row["relevance"])) for row in selected_poses
    )
    first, second = float(scores[0]), float(scores[1])
    return {
        "schema_version": "phase2_v3_p2_docking_gold_candidate_v1",
        "pilot_rank": pilot.get("pilot_rank", ""),
        "pilot_id": pilot["pilot_id"],
        "source_cohort": pilot.get("source_cohort", ""),
        "source_candidate_id": pilot.get("source_candidate_id", ""),
        "parent_framework_cluster": pilot.get("parent_framework_cluster", ""),
        "seed_role": seed_role,
        "r_8x6b": f"{first:.10f}",
        "r_9e6y": f"{second:.10f}",
        "R_gold": f"{(first + second) / 2.0:.10f}",
        "conformer_disagreement": f"{abs(first-second):.10f}",
        "conformer_disagreement_interpretation": "observed dual-conformer pipeline disagreement (conformer plus sampling), not a pure causal conformer effect",
        "stable_tier": tier,
        "stable_relevance_threshold": threshold,
        "stable_supporting_clusters": support,
        "dg_a_pass": all(parse_bool(selected_receptors[receptor]["dg_a_pass"]) for receptor in RECEPTORS),
        "calibration_only": pilot.get("calibration_only", ""),
        "submission_eligible": pilot.get("submission_eligible", ""),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def pilot_gate(
    main_complete: int,
    replicate_complete: int,
    contact_failures: int,
    tolerance_relaxation: bool,
    spearman: float | None,
    quadratic_kappa: float | None,
    manifest_contract_pass: bool = True,
) -> dict[str, Any]:
    gates = {
        "manifest_contract": manifest_contract_pass,
        "main_dg_a_64_of_64": main_complete == EXPECTED_PILOTS,
        "replicate_receptor_runs_32_of_32": replicate_complete == EXPECTED_REPLICATE_RUNS,
        "contact_failures_zero": contact_failures == 0,
        "tolerance_relaxation_false": not tolerance_relaxation,
        "repeat_R_gold_spearman_ge_0_70": spearman is not None and spearman >= 0.70,
        "stable_tier_quadratic_kappa_ge_0_60": quadratic_kappa is not None and quadratic_kappa >= 0.60,
    }
    return {
        "status": "PASS_DOCKING_GOLD_VALIDATED" if all(gates.values()) else "FAIL_DOCKING_GOLD_NOT_VALIDATED",
        "gates": gates,
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def build_report(audit: Mapping[str, Any]) -> str:
    metrics = audit["repeatability"]
    lines = [
        "# PVRIG V3-P2 Docking Gold 验证报告",
        "",
        f"- 状态：`{audit['status']}`",
        f"- 主批次 DG-A 完整候选：{audit['counts']['main_candidates_dg_a_complete']}/64",
        f"- 重复 receptor run 完整：{audit['counts']['replicate_receptor_runs_dg_a_complete']}/32",
        f"- contact failures：{audit['counts']['contact_failures']}",
        f"- R_gold 重复 Spearman：{metrics['R_gold_spearman']}",
        f"- stable tier quadratic weighted kappa：{metrics['stable_tier_quadratic_kappa']}",
        f"- stable tier linear weighted kappa（次要）：{metrics['stable_tier_linear_kappa']}",
        "",
        "## 预注册门槛",
        "",
        "| 门槛 | 结果 |",
        "| --- | --- |",
    ]
    for name, passed in audit["gates"].items():
        lines.append(f"| `{name}` | {'PASS' if passed else 'FAIL'} |")
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            f"- {CLAIM_BOUNDARY}。",
            "- `conformer_disagreement` 是两条独立 receptor docking 管线的观测差异，同时包含构象与采样差异，不是纯构象因果效应。",
            "- 16 条重复序列的指标衡量端到端 docking 重复性，不代替实验绑定或阻断验证。",
            "",
        ]
    )
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    selection_rows = read_csv(args.selection_manifest)
    run_rows = read_csv(args.run_manifest)
    _runs_by_id, contract_errors = manifest_contract(selection_rows, run_rows)
    selection = {row["pilot_id"]: row for row in selection_rows}
    all_pose_rows: list[dict[str, Any]] = []
    receptor_rows: list[dict[str, Any]] = []
    global_tolerance_relaxation = False
    for manifest_row in run_rows:
        protocol, protocol_errors = run_protocol_checks(manifest_row, args.sync_root)
        poses, postprocess, postprocess_errors = evaluate_postprocessed_run(manifest_row, args.postprocessed_root)
        errors = [*protocol_errors, *postprocess_errors]
        completion_pose_count = protocol.get("completion_pose_count", "")
        completion_cluster_count = protocol.get("completion_cluster_count", "")
        if str(completion_pose_count).strip():
            try:
                if parse_int(completion_pose_count, "completion_pose_count") != postprocess["selected_poses"]:
                    errors.append(
                        f"completion_vs_postprocess_pose_count:{completion_pose_count}!={postprocess['selected_poses']}"
                    )
            except ValueError:
                pass
        if str(completion_cluster_count).strip():
            try:
                if parse_int(completion_cluster_count, "completion_cluster_count") != postprocess["pose_clusters"]:
                    errors.append(
                        f"completion_vs_postprocess_cluster_count:{completion_cluster_count}!={postprocess['pose_clusters']}"
                    )
            except ValueError:
                pass
        global_tolerance_relaxation |= bool(protocol.get("tolerance_relaxed", True))
        dg_a = not errors
        all_pose_rows.extend(poses)
        receptor_rows.append(
            {
                "schema_version": "phase2_v3_p2_docking_gold_receptor_v1",
                "pilot_id": manifest_row["pilot_id"],
                "source_candidate_id": manifest_row.get("source_candidate_id", ""),
                "run_id": manifest_row["run_id"],
                "receptor_id": manifest_row["receptor_id"].lower(),
                "seed_role": manifest_row["seed_role"].lower(),
                "rigidbody_iniseed": protocol.get("frozen_rigidbody_iniseed", ""),
                "monomer_sha256": protocol.get("monomer_sha256", ""),
                "selected_poses": postprocess["selected_poses"],
                "pose_clusters": postprocess["pose_clusters"],
                "r_receptor": "" if postprocess["r_receptor"] is None else f"{postprocess['r_receptor']:.10f}",
                "r_receptor_raw": postprocess["r_receptor"],
                "stable_tier": postprocess["stable_tier"],
                "stable_relevance_threshold": postprocess["stable_relevance_threshold"],
                "stable_supporting_clusters": postprocess["stable_supporting_clusters"],
                "canonical_contact_pose_rows": postprocess["canonical_contact_pose_rows"],
                "contact_failures": postprocess["contact_failures"],
                "tolerance_relaxed": protocol.get("tolerance_relaxed", True),
                "dg_a_pass": dg_a,
                "dg_a_failure_reasons": ";".join(errors),
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )

    # Enforce the same frozen monomer for the two receptor runs (and repeat) of each candidate.
    monomers: dict[str, set[str]] = defaultdict(set)
    for row in receptor_rows:
        if row["monomer_sha256"]:
            monomers[row["pilot_id"]].add(row["monomer_sha256"])
    bad_monomers = {pilot_id for pilot_id, hashes in monomers.items() if len(hashes) != 1}
    for row in receptor_rows:
        if row["pilot_id"] in bad_monomers or not row["monomer_sha256"]:
            row["dg_a_pass"] = False
            extra = "same_monomer_sha_across_receptors:false"
            row["dg_a_failure_reasons"] = ";".join(filter(None, [row["dg_a_failure_reasons"], extra]))

    main_candidates: list[dict[str, Any]] = []
    replicate_candidates: dict[str, dict[str, Any]] = {}
    for pilot_id, pilot in sorted(selection.items(), key=lambda item: int(item[1].get("pilot_rank", 10**9))):
        main = combine_candidate(pilot, receptor_rows, all_pose_rows, "main")
        if main is not None:
            main_candidates.append(main)
        replicate = combine_candidate(pilot, receptor_rows, all_pose_rows, "replicate")
        if replicate is not None:
            replicate_candidates[pilot_id] = replicate

    comparisons: list[dict[str, Any]] = []
    main_by_id = {row["pilot_id"]: row for row in main_candidates}
    for pilot_id in sorted(replicate_candidates, key=lambda value: int(selection[value].get("pilot_rank", 10**9))):
        main = main_by_id.get(pilot_id)
        repeat = replicate_candidates[pilot_id]
        if main is None:
            continue
        comparisons.append(
            {
                "schema_version": "phase2_v3_p2_docking_gold_replicate_comparison_v1",
                "pilot_id": pilot_id,
                "source_candidate_id": main["source_candidate_id"],
                "main_R_gold": main["R_gold"],
                "replicate_R_gold": repeat["R_gold"],
                "R_gold_delta": f"{float(repeat['R_gold'])-float(main['R_gold']):.10f}",
                "main_stable_tier": main["stable_tier"],
                "replicate_stable_tier": repeat["stable_tier"],
                "main_dg_a_pass": main["dg_a_pass"],
                "replicate_dg_a_pass": repeat["dg_a_pass"],
                "claim_boundary": CLAIM_BOUNDARY,
            }
        )
    spearman = spearman_with_ties(
        [float(row["main_R_gold"]) for row in comparisons],
        [float(row["replicate_R_gold"]) for row in comparisons],
    )
    quadratic_kappa = weighted_cohen_kappa(
        [row["main_stable_tier"] for row in comparisons],
        [row["replicate_stable_tier"] for row in comparisons],
        "quadratic",
    )
    linear_kappa = weighted_cohen_kappa(
        [row["main_stable_tier"] for row in comparisons],
        [row["replicate_stable_tier"] for row in comparisons],
        "linear",
    )
    main_complete = sum(parse_bool(row["dg_a_pass"]) for row in main_candidates)
    replicate_run_complete = sum(
        parse_bool(row["dg_a_pass"]) for row in receptor_rows if row["seed_role"] == "replicate"
    )
    contact_failures = sum(int(row["contact_failures"]) for row in receptor_rows)
    gate = pilot_gate(
        main_complete,
        replicate_run_complete,
        contact_failures,
        global_tolerance_relaxation,
        spearman,
        quadratic_kappa,
        manifest_contract_pass=not contract_errors,
    )

    args.outdir.mkdir(parents=True, exist_ok=True)
    pose_path = args.outdir / "phase2_v3_p2_docking_gold_pose.csv"
    receptor_path = args.outdir / "phase2_v3_p2_docking_gold_receptor.csv"
    candidate_path = args.outdir / "phase2_v3_p2_docking_gold_candidate.csv"
    comparison_path = args.outdir / "phase2_v3_p2_docking_gold_replicate_comparison.csv"
    write_csv(pose_path, all_pose_rows, ["schema_version", "pilot_id", "run_id", "receptor_id", "seed_role", "model"])
    serializable_receptors = [{key: value for key, value in row.items() if key != "r_receptor_raw"} for row in receptor_rows]
    write_csv(receptor_path, serializable_receptors, ["schema_version", "pilot_id", "run_id", "receptor_id", "seed_role"])
    write_csv(candidate_path, main_candidates, ["schema_version", "pilot_rank", "pilot_id", "source_candidate_id", "R_gold"])
    write_csv(comparison_path, comparisons, ["schema_version", "pilot_id", "source_candidate_id", "main_R_gold", "replicate_R_gold"])
    audit: dict[str, Any] = {
        "schema_version": "phase2_v3_p2_docking_gold_audit_v1",
        **gate,
        "inputs": {
            "selection_manifest": str(args.selection_manifest),
            "selection_manifest_sha256": sha256_file(args.selection_manifest),
            "run_manifest": str(args.run_manifest),
            "run_manifest_sha256": sha256_file(args.run_manifest),
            "postprocessed_root": str(args.postprocessed_root),
            "sync_root": str(args.sync_root),
        },
        "counts": {
            "selection_candidates": len(selection_rows),
            "run_manifest_rows": len(run_rows),
            "pose_rows": len(all_pose_rows),
            "receptor_rows": len(receptor_rows),
            "main_candidate_rows": len(main_candidates),
            "main_candidates_dg_a_complete": main_complete,
            "replicate_candidate_rows": len(replicate_candidates),
            "replicate_comparison_rows": len(comparisons),
            "replicate_receptor_runs_dg_a_complete": replicate_run_complete,
            "contact_failures": contact_failures,
        },
        "repeatability": {
            "R_gold_spearman": spearman,
            "stable_tier_quadratic_kappa": quadratic_kappa,
            "stable_tier_linear_kappa": linear_kappa,
        },
        "protocol": {
            "frozen_rigidbody_seeds": {
                f"{receptor}_{role}": seed for (receptor, role), seed in FROZEN_RIGIDBODY_SEEDS.items()
            },
            "topoaa_iniseed": FROZEN_TOPOAA_SEED,
            "rigidbody_tolerance": FROZEN_RIGIDBODY_TOLERANCE,
            "flexref_tolerance": FROZEN_FLEXREF_TOLERANCE,
            "tolerance_relaxation_observed": global_tolerance_relaxation,
        },
        "manifest_contract_errors": contract_errors,
        "failed_receptor_runs": [
            {"run_id": row["run_id"], "reasons": row["dg_a_failure_reasons"]}
            for row in receptor_rows
            if not parse_bool(row["dg_a_pass"])
        ],
        "outputs": {
            "pose_csv": str(pose_path),
            "pose_csv_sha256": sha256_file(pose_path),
            "receptor_csv": str(receptor_path),
            "receptor_csv_sha256": sha256_file(receptor_path),
            "candidate_csv": str(candidate_path),
            "candidate_csv_sha256": sha256_file(candidate_path),
            "replicate_comparison_csv": str(comparison_path),
            "replicate_comparison_csv_sha256": sha256_file(comparison_path),
            "audit_json": str(args.audit),
            "report_zh": str(args.report),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(build_report(audit), encoding="utf-8")
    audit["outputs"]["report_zh_sha256"] = sha256_file(args.report)
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return audit


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection-manifest", type=Path, default=DEFAULT_SELECTION_MANIFEST)
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST)
    parser.add_argument("--postprocessed-root", type=Path, default=DEFAULT_POSTPROCESSED_ROOT)
    parser.add_argument("--sync-root", type=Path, default=DEFAULT_SYNC_ROOT)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args(argv)


def main() -> None:
    audit = run(parse_args())
    print(json.dumps(audit, indent=2, sort_keys=True))
    if audit["status"] != "PASS_DOCKING_GOLD_VALIDATED":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
