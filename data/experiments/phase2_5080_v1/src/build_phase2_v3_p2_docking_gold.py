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
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent
DOCKING_SCRIPTS = WORKSPACE_ROOT / "docking/scripts"
WORKFLOW_DIR = WORKSPACE_ROOT / "docking/success_case_validation"

DEFAULT_SELECTION_MANIFEST = (
    EXP_DIR / "data_splits/pvrig_v3_p2/dual_docking_pilot64_manifest.csv"
)
DEFAULT_PACKAGE_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_package_v2"
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/run_manifest.csv"
DEFAULT_POSTPROCESSED_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_postprocessed"
)
DEFAULT_SYNC_ROOT = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_node1_selected"
DEFAULT_OUTDIR = EXP_DIR / "runs/pvrig_v3_p2/dual_docking_pilot64_v2_gold"
DEFAULT_AUDIT = EXP_DIR / "audits/phase2_v3_p2_docking_gold_v2_audit.json"
DEFAULT_REPORT = EXP_DIR / "reports/PVRIG_V3_P2_DOCKING_GOLD_V2_VALIDATION_ZH.md"

CLAIM_BOUNDARY = (
    "computational docking gold from frozen independent 8X6B/9E6Y HADDOCK "
    "pipelines; not experimental binding, affinity, or blocking truth"
)
RECEPTORS = ("8x6b", "9e6y")
SEED_ROLES = ("main", "replicate")
PROTOCOL_ID = "DG_A_PILOT64_V1_1"
FROZEN_EXTERNAL_TRUST_ANCHORS = {
    "selection_manifest": "e67fcab05d93cd3f274c76cc435e9f4b649ace255e230129865d913fa8be3755",
    "run_manifest": "e8a420471f68f646c82063ea3254347859f155409cad413a971f37d30b3278a9",
    "package_audit": "9a347b8200b5bb1d06c76e52cf34aa0393facc04e24314d45f333725e3f28280",
    "content_manifest": "efa89e6b05406128b046b0189f236a2273ab3670fd783224d9b1bab786eba624",
}
POSTPROCESS_TOOLCHAIN_PATHS = {
    "postprocessor": SCRIPT_DIR / "process_phase2_v3_p2_dual_docking_pilot.py",
    "align_pdb_by_chain": DOCKING_SCRIPTS / "align_pdb_by_chain.py",
    "score_pvrig_vhh_pose": DOCKING_SCRIPTS / "score_pvrig_vhh_pose.py",
    "score_cdr_region_occlusion": DOCKING_SCRIPTS / "score_cdr_region_occlusion.py",
    "apply_blocker_judgment": WORKFLOW_DIR / "apply_blocker_judgment.py",
    "summarize_multibaseline_judgment": WORKFLOW_DIR / "summarize_multibaseline_judgment.py",
}
POSTPROCESS_REFERENCE_PATHS = {
    "hotspot_csv": DATA_ROOT / "structures/PVRIG_hotspot_set_v1.csv",
    "numbering_reconciliation_csv": DATA_ROOT / "structures/PVRIG_numbering_reconciliation.csv",
    "8x6b_scoring_reference": DATA_ROOT / "structures/8X6B.pdb",
    "9e6y_scoring_reference": DATA_ROOT / "structures/9E6Y.pdb",
}
FROZEN_POSTPROCESS_TOOLCHAIN_SHA256 = {
    "postprocessor": "52f90996be89e8e2ea200ebd1cc17935566d3397cc05d8d8ef85d138aa933c6b",
    "align_pdb_by_chain": "e6b863979db5a1ac6702ae7f04da49d3d425069a070fc441221341a202a9d7f7",
    "score_pvrig_vhh_pose": "a5ca4117ba6a5d449711fcd1198ae09c77508532fe7c0cc73d23d57b02eb15ec",
    "score_cdr_region_occlusion": "c5e419daec19e6e38b6a52bfc63e0d6100c9c16f27b46a60235dc0f6a438982f",
    "apply_blocker_judgment": "c5f6f96d4821863dd14dc201807d8c863226876507df36a9e78b7a47e7df2654",
    "summarize_multibaseline_judgment": "058ee1a2405fcb253057c813b9a5bb2e9dced99a2bb81be6560ed89885493317",
}
FROZEN_POSTPROCESS_REFERENCE_SHA256 = {
    "hotspot_csv": "9e5e82ad1f8193efbbb72865a632528c6b6a08d8a686c5b3e8ac74d2fd1564dd",
    "numbering_reconciliation_csv": "d7decf3be4a19dd9da2a42d9c8825a0b5d95ca350aea553b0933ad5c30c3c552",
    "8x6b_scoring_reference": "b9a930e44f61ee2ba35b4f8f739bc9431eb1944dad2e2344bd9c9a7ad13bb868",
    "9e6y_scoring_reference": "fb05ec77e439b8e1f43bfa12d7eb60f05f2c53e2099f06442f6c9ced32d98316",
}
FROZEN_RIGIDBODY_SEEDS = {
    ("8x6b", "main"): 917,
    ("8x6b", "replicate"): 10917,
    ("9e6y", "main"): 20917,
    ("9e6y", "replicate"): 30917,
}
FROZEN_TOPOAA_SEED = 917
FROZEN_RIGIDBODY_TOLERANCE = 5.0
FROZEN_FLEXREF_TOLERANCE = 20.0
FROZEN_EMREF_TOLERANCE = 20.0
STAGE_IO_RELPATHS = {
    "topoaa": "0_topoaa/io.json",
    "rigidbody": "1_rigidbody/io.json",
    "seletop": "2_seletop/io.json",
    "flexref": "3_flexref/io.json",
    "emref": "4_emref/io.json",
    "final": "6_seletopclusts/io.json",
}
STAGE_OUTPUT_REQUIREMENTS = {
    "topoaa": ("eq", 2),
    "rigidbody": ("ge", 38),
    "seletop": ("eq", 10),
    "flexref": ("ge", 8),
    "emref": ("ge", 8),
    "final": ("ge", 8),
}
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
POSTPROCESS_MARKER_SCHEMA = "phase2_v3_p2_dual_docking_run_postprocess_v1_1"
POSTPROCESS_ARTIFACT_KEYS = (
    "consensus",
    "classification_8x6b",
    "classification_9e6y",
    "mechanism_8x6b",
    "mechanism_9e6y",
    "canonical_contact_summary",
    "canonical_contact_pairs",
    "ranks",
)
POSTPROCESS_COUNT_FIELDS = (
    "selected_models",
    "pose_clusters",
    "consensus_rows",
    "classification_8x6b_rows",
    "classification_9e6y_rows",
    "mechanism_8x6b_rows",
    "mechanism_9e6y_rows",
    "canonical_contact_pose_rows",
    "canonical_contact_pair_rows",
    "contact_failures",
)


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


def hash_named_paths(paths: Mapping[str, Path]) -> dict[str, str]:
    return {
        name: sha256_file(path)
        for name, path in paths.items()
        if path.is_file()
    }


def current_postprocess_toolchain_hashes() -> dict[str, str]:
    return hash_named_paths(POSTPROCESS_TOOLCHAIN_PATHS)


def current_postprocess_reference_hashes() -> dict[str, str]:
    return hash_named_paths(POSTPROCESS_REFERENCE_PATHS)


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


def validate_package_closure(
    selection_manifest: Path,
    run_manifest: Path,
    trust_anchors: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate the package audit as the root of the frozen input closure."""
    package_root = run_manifest.resolve().parent.parent
    audit_path = package_root / "package_audit.json"
    checks: dict[str, bool] = {}
    errors: list[str] = []
    evidence: dict[str, Any] = {
        "package_root": str(package_root),
        "package_audit": str(audit_path),
    }
    anchors = dict(FROZEN_EXTERNAL_TRUST_ANCHORS if trust_anchors is None else trust_anchors)
    trust_anchor_checks: dict[str, bool] = {}
    add_check(checks, errors, "package_audit_present", audit_path.is_file(), str(audit_path))
    if not audit_path.is_file():
        evidence["checks"] = checks
        return evidence, errors
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if not isinstance(audit, dict):
            raise ValueError("package audit is not an object")
    except Exception as error:
        add_check(checks, errors, "package_audit_parse", False, f"{type(error).__name__}:{error}")
        evidence["checks"] = checks
        return evidence, errors
    evidence["package_audit_sha256"] = sha256_file(audit_path)
    evidence["package_audit_payload"] = audit
    add_check(
        checks,
        errors,
        "package_audit_schema",
        audit.get("schema_version") == "phase2_v3_p2_pilot64_package_audit_v1_1",
        str(audit.get("schema_version")),
    )
    add_check(checks, errors, "package_audit_protocol", audit.get("protocol_id") == PROTOCOL_ID, str(audit.get("protocol_id")))
    add_check(
        checks,
        errors,
        "package_audit_status",
        audit.get("status") == "PASS_PILOT64_DUAL_DOCKING_PACKAGE_READY",
        str(audit.get("status")),
    )
    add_check(
        checks,
        errors,
        "package_audit_no_per_candidate_override",
        audit.get("per_candidate_failure_tolerance_override") is False,
        str(audit.get("per_candidate_failure_tolerance_override")),
    )
    add_check(
        checks,
        errors,
        "package_audit_no_tolerance_relaxation",
        audit.get("tolerance_relaxed") is False,
        str(audit.get("tolerance_relaxed")),
    )
    if selection_manifest.is_file():
        observed = sha256_file(selection_manifest)
        add_check(
            checks,
            errors,
            "package_selection_manifest_sha256",
            observed == audit.get("pilot_manifest_sha256"),
            f"{observed}!={audit.get('pilot_manifest_sha256')}",
        )
    else:
        add_check(checks, errors, "package_selection_manifest_sha256", False, str(selection_manifest))

    declared_files = (
        ("run_manifest", "run_manifest_sha256"),
        ("protocol_manifest", "protocol_manifest_sha256"),
        ("monomer_manifest", "monomer_manifest_sha256"),
        ("package_content_hash_manifest", "package_content_hash_manifest_sha256"),
    )
    resolved: dict[str, Path] = {}
    for path_field, hash_field in declared_files:
        relative = str(audit.get(path_field, ""))
        path = package_root / relative
        resolved[path_field] = path
        safe = bool(relative) and not Path(relative).is_absolute() and package_root in path.resolve().parents
        add_check(checks, errors, f"package_{path_field}_safe_path", safe, relative)
        present = safe and path.is_file()
        add_check(checks, errors, f"package_{path_field}_present", present, str(path))
        if present:
            observed = sha256_file(path)
            add_check(
                checks,
                errors,
                f"package_{path_field}_sha256",
                observed == audit.get(hash_field),
                f"{observed}!={audit.get(hash_field)}",
            )
    add_check(
        checks,
        errors,
        "package_run_manifest_is_evaluated_manifest",
        resolved.get("run_manifest", Path()).resolve() == run_manifest.resolve(),
        f"{resolved.get('run_manifest')}!={run_manifest}",
    )

    observed_anchor_hashes = {
        "selection_manifest": sha256_file(selection_manifest) if selection_manifest.is_file() else "",
        "run_manifest": sha256_file(run_manifest) if run_manifest.is_file() else "",
        "package_audit": sha256_file(audit_path),
        "content_manifest": (
            sha256_file(resolved["package_content_hash_manifest"])
            if resolved.get("package_content_hash_manifest", Path()).is_file()
            else ""
        ),
    }
    for name, expected in anchors.items():
        observed = observed_anchor_hashes.get(name, "")
        passed = observed == expected
        trust_anchor_checks[name] = passed
        add_check(checks, errors, f"frozen_trust_anchor_{name}", passed, f"{observed}!={expected}")
    evidence["trust_anchor_checks"] = trust_anchor_checks
    evidence["observed_trust_anchor_sha256"] = observed_anchor_hashes

    content_path = resolved.get("package_content_hash_manifest")
    if content_path and content_path.is_file():
        try:
            with content_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            declared: dict[str, str] = {}
            for item in rows:
                relative = item.get("path", "")
                digest = item.get("sha256", "")
                target = package_root / relative
                if (
                    not relative
                    or relative in declared
                    or Path(relative).is_absolute()
                    or package_root not in target.resolve().parents
                ):
                    errors.append(f"content_invalid_or_duplicate_path:{relative}")
                    continue
                declared[relative] = digest
                if not target.is_file():
                    errors.append(f"content_missing:{relative}")
                else:
                    observed = sha256_file(target)
                    if observed != digest:
                        errors.append(f"content_sha256_mismatch:{relative}:{observed}!={digest}")
            run_rows = read_csv(run_manifest)
            immutable_expected = {
                str(audit[field])
                for field in ("run_manifest", "protocol_manifest", "monomer_manifest", "controller")
                if audit.get(field)
            }
            for run_row in run_rows:
                for field in (
                    "config_relpath",
                    "monomer_relpath",
                    "receptor_relpath",
                    "restraint_relpath",
                    "hotspot_relpath",
                ):
                    relative = run_row.get(field, "").strip()
                    if relative:
                        immutable_expected.add(relative)
            exact = set(declared) == immutable_expected
            add_check(
                checks,
                errors,
                "content_manifest_exact_file_set",
                exact,
                f"missing={sorted(immutable_expected-set(declared))};extra={sorted(set(declared)-immutable_expected)}",
            )
            immutable_observed: set[str] = set()
            for dirname in ("monomers", "receptors", "restraints", "hotspots", "scripts"):
                directory = package_root / dirname
                if directory.is_dir():
                    immutable_observed.update(
                        str(path.relative_to(package_root)) for path in directory.rglob("*") if path.is_file()
                    )
            manifests_dir = package_root / "manifests"
            content_relative = str(content_path.relative_to(package_root))
            if manifests_dir.is_dir():
                immutable_observed.update(
                    str(path.relative_to(package_root))
                    for path in manifests_dir.rglob("*")
                    if path.is_file() and str(path.relative_to(package_root)) != content_relative
                )
            runs_dir = package_root / "runs"
            if runs_dir.is_dir():
                immutable_observed.update(
                    str(path.relative_to(package_root)) for path in runs_dir.glob("*/*.cfg") if path.is_file()
                )
            immutable_exact = immutable_observed == immutable_expected
            add_check(
                checks,
                errors,
                "immutable_input_exact_file_set",
                immutable_exact,
                f"missing={sorted(immutable_expected-immutable_observed)};"
                f"extra={sorted(immutable_observed-immutable_expected)}",
            )
            if not immutable_exact:
                errors.append(
                    "immutable_input_set_mismatch:"
                    f"missing={sorted(immutable_expected-immutable_observed)};"
                    f"extra={sorted(immutable_observed-immutable_expected)}"
                )
            add_check(
                checks,
                errors,
                "content_manifest_all_hashes",
                not any(error.startswith(("content_missing:", "content_sha256_mismatch:", "content_invalid_or_duplicate_path:")) for error in errors),
                "one or more content entries failed",
            )
            evidence["content_manifest_rows"] = len(rows)
        except Exception as error:
            add_check(checks, errors, "content_manifest_parse", False, f"{type(error).__name__}:{error}")
    evidence["checks"] = checks
    return evidence, errors


def run_protocol_checks(
    row: Mapping[str, str],
    sync_root: Path,
    package_root: Path | None = None,
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

    add_check(
        checks,
        errors,
        "manifest_protocol_id",
        row.get("protocol_id") == PROTOCOL_ID,
        f"{row.get('protocol_id')}!={PROTOCOL_ID}",
    )

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
        ("emref_tolerance", FROZEN_EMREF_TOLERANCE),
    ):
        try:
            actual = parse_float(row.get(field, ""), field)
            add_check(checks, errors, f"manifest_{field}", actual == expected, f"{actual}!={expected}")
        except ValueError as error:
            add_check(checks, errors, f"manifest_{field}", False, str(error))
    try:
        override = parse_bool(row.get("per_candidate_failure_tolerance_override", ""))
        add_check(
            checks,
            errors,
            "manifest_no_per_candidate_failure_tolerance_override",
            not override,
            str(override),
        )
        evidence["per_candidate_failure_tolerance_override"] = override
    except ValueError as error:
        add_check(
            checks,
            errors,
            "manifest_no_per_candidate_failure_tolerance_override",
            False,
            str(error),
        )
        evidence["per_candidate_failure_tolerance_override"] = True
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

    if package_root is not None:
        for path_field, hash_field in (
            ("config_relpath", "config_sha256"),
            ("monomer_relpath", "monomer_sha256"),
            ("receptor_relpath", "receptor_sha256"),
        ):
            relative = row.get(path_field, "")
            path = package_root / relative
            safe = bool(relative) and not Path(relative).is_absolute() and package_root.resolve() in path.resolve().parents
            add_check(checks, errors, f"package_{path_field}_safe_path", safe, relative)
            present = safe and path.is_file()
            add_check(checks, errors, f"package_{path_field}_present", present, str(path))
            if present:
                observed = sha256_file(path)
                add_check(
                    checks,
                    errors,
                    f"package_{hash_field}",
                    observed == row.get(hash_field, ""),
                    f"{observed}!={row.get(hash_field, '')}",
                )

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
            emref = config.get("emref", {})
            seletop = config.get("seletop", {})
            topoaa = config.get("topoaa", {})
            config_override = (
                float(rigidbody.get("tolerance", math.inf)) != FROZEN_RIGIDBODY_TOLERANCE
                or float(flexref.get("tolerance", math.inf)) != FROZEN_FLEXREF_TOLERANCE
                or float(emref.get("tolerance", math.inf)) != FROZEN_EMREF_TOLERANCE
            )
            evidence["per_candidate_failure_tolerance_override"] = bool(
                evidence.get("per_candidate_failure_tolerance_override")
            ) or config_override
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
                "config_emref_tolerance",
                float(emref.get("tolerance", math.nan)) == FROZEN_EMREF_TOLERANCE,
                str(emref.get("tolerance")),
            )
            add_check(
                checks,
                errors,
                "config_seletop_select",
                seletop.get("select") == 10,
                str(seletop.get("select")),
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
            if completion.get("per_candidate_failure_tolerance_override") is not False:
                evidence["per_candidate_failure_tolerance_override"] = True
            evidence["completion_status"] = completion.get("status", "")
            evidence["completion_pose_count"] = completion.get("pose_count", "")
            evidence["completion_cluster_count"] = completion.get("cluster_count", "")
            evidence["completion_stage_output_counts"] = completion.get("stage_output_counts", {})
            add_check(checks, errors, "completion_run_id", completion.get("run_id") == run_id, str(completion.get("run_id")))
            add_check(
                checks,
                errors,
                "completion_protocol_id",
                completion.get("protocol_id") == PROTOCOL_ID,
                f"{completion.get('protocol_id')}!={PROTOCOL_ID}",
            )
            add_check(
                checks,
                errors,
                "completion_status",
                completion.get("status") == "PASS_DOCKING_OUTPUT_COMPLETE",
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
                "completion_no_per_candidate_failure_tolerance_override",
                completion.get("per_candidate_failure_tolerance_override") is False,
                str(completion.get("per_candidate_failure_tolerance_override")),
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

    runtime_param_specs = {
        "rigidbody": (run_dir / "1_rigidbody/params.cfg", FROZEN_RIGIDBODY_TOLERANCE),
        "flexref": (run_dir / "3_flexref/params.cfg", FROZEN_FLEXREF_TOLERANCE),
        "emref": (run_dir / "4_emref/params.cfg", FROZEN_EMREF_TOLERANCE),
    }
    for module, (params_path, expected_tolerance) in runtime_param_specs.items():
        add_check(checks, errors, f"runtime_{module}_params_present", params_path.is_file(), str(params_path))
        if not params_path.is_file():
            continue
        try:
            params_document = read_toml(params_path)
            params = params_document.get(module, params_document)
            add_check(
                checks,
                errors,
                f"runtime_{module}_tolerance",
                float(params.get("tolerance", math.nan)) == expected_tolerance,
                str(params.get("tolerance")),
            )
            if module == "rigidbody":
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
                    "runtime_rigidbody_sampling",
                    params.get("sampling") == sampling,
                    f"{params.get('sampling')}!={sampling}",
                )
        except Exception as error:
            add_check(
                checks,
                errors,
                f"runtime_{module}_params_parse",
                False,
                f"{type(error).__name__}:{error}",
            )

    runtime_stage_counts: dict[str, int] = {}
    rigidbody_outputs: list[dict[str, Any]] = []
    for stage, relative in STAGE_IO_RELPATHS.items():
        io_path = run_dir / relative
        add_check(checks, errors, f"runtime_{stage}_io_present", io_path.is_file(), str(io_path))
        if not io_path.is_file():
            runtime_stage_counts[stage] = 0
            continue
        try:
            runtime_io = json.loads(io_path.read_text(encoding="utf-8"))
            outputs = runtime_io.get("output")
            if not isinstance(outputs, list):
                raise ValueError("io.json output is not a list")
            runtime_stage_counts[stage] = len(outputs)
            if stage == "rigidbody":
                rigidbody_outputs = outputs
        except Exception as error:
            runtime_stage_counts[stage] = 0
            add_check(
                checks,
                errors,
                f"runtime_{stage}_io_parse",
                False,
                f"{type(error).__name__}:{error}",
            )
    evidence["runtime_stage_output_counts"] = runtime_stage_counts
    for stage, (operator, expected) in STAGE_OUTPUT_REQUIREMENTS.items():
        observed = runtime_stage_counts.get(stage, 0)
        passed = observed == expected if operator == "eq" else observed >= expected
        add_check(
            checks,
            errors,
            f"runtime_{stage}_output_count",
            passed,
            f"{observed}:{operator}:{expected}",
        )

    try:
        observed_seeds = [parse_int(item.get("seed", ""), "runtime_output_seed") for item in rigidbody_outputs]
        expected_seeds = set(range(expected_seed + 1, expected_seed + sampling + 1))
        observed_seed_set = set(observed_seeds)
        evidence["runtime_rigidbody_output_count"] = len(rigidbody_outputs)
        evidence["runtime_rigidbody_seed_start"] = min(observed_seeds) if observed_seeds else ""
        evidence["runtime_rigidbody_seed_end"] = max(observed_seeds) if observed_seeds else ""
        add_check(
            checks,
            errors,
            "runtime_rigidbody_seed_set",
            len(observed_seed_set) == len(observed_seeds)
            and observed_seed_set <= expected_seeds
            and len(observed_seeds) >= STAGE_OUTPUT_REQUIREMENTS["rigidbody"][1],
            f"observed={sorted(observed_seed_set)};allowed={sorted(expected_seeds)}",
        )
    except Exception as error:
        add_check(checks, errors, "runtime_rigidbody_seed_set", False, f"{type(error).__name__}:{error}")

    completion_stage_counts = completion.get("stage_output_counts", {}) if completion else {}
    add_check(
        checks,
        errors,
        "completion_stage_output_counts_object",
        isinstance(completion_stage_counts, dict),
        type(completion_stage_counts).__name__,
    )
    for stage, observed in runtime_stage_counts.items():
        try:
            declared = parse_int(completion_stage_counts.get(stage, ""), f"completion_stage_{stage}")
            add_check(
                checks,
                errors,
                f"completion_stage_output_count_{stage}",
                declared == observed,
                f"{declared}!={observed}",
            )
        except (AttributeError, ValueError) as error:
            add_check(
                checks,
                errors,
                f"completion_stage_output_count_{stage}",
                False,
                str(error),
            )

    selected_dir = run_dir / "6_seletopclusts"
    model_names = {
        path.name.removesuffix(".pdb.gz").removesuffix(".pdb")
        for path in selected_dir.glob("cluster_*_model_*.pdb*")
        if path.is_file() and path.stat().st_size
    }
    cluster_names = {cluster_from_model(model) for model in model_names}
    evidence["runtime_final_model_files"] = len(model_names)
    evidence["runtime_final_pose_clusters"] = len(cluster_names)
    add_check(
        checks,
        errors,
        "runtime_final_model_files",
        len(model_names) >= MIN_SELECTED_POSES and len(model_names) == runtime_stage_counts.get("final", 0),
        f"files={len(model_names)};io={runtime_stage_counts.get('final', 0)}",
    )
    add_check(
        checks,
        errors,
        "runtime_final_pose_clusters",
        len(cluster_names) >= MIN_POSE_CLUSTERS,
        str(len(cluster_names)),
    )
    if completion:
        try:
            add_check(
                checks,
                errors,
                "completion_pose_count_matches_runtime",
                parse_int(completion.get("pose_count", ""), "pose_count") == len(model_names),
                f"{completion.get('pose_count')}!={len(model_names)}",
            )
            add_check(
                checks,
                errors,
                "completion_cluster_count_matches_runtime",
                parse_int(completion.get("cluster_count", ""), "cluster_count") == len(cluster_names),
                f"{completion.get('cluster_count')}!={len(cluster_names)}",
            )
        except ValueError as error:
            add_check(checks, errors, "completion_runtime_count_match", False, str(error))
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


def postprocess_artifact_paths(run_root: Path, run_id: str) -> dict[str, Path]:
    reports = run_root / "reports"
    return {
        "consensus": reports / f"{run_id}_dual_baseline_consensus.csv",
        "classification_8x6b": reports / f"{run_id}_8x6b_blocker_classification.csv",
        "classification_9e6y": reports / f"{run_id}_9e6y_blocker_classification.csv",
        "mechanism_8x6b": run_root / "8x6b_baseline/haddock3_top_model_mechanism_scores_8x6b.csv",
        "mechanism_9e6y": run_root / "9e6y_baseline/haddock3_top_model_mechanism_scores_9e6y.csv",
        "canonical_contact_summary": reports / f"{run_id}_canonical_contact_summary.csv",
        "canonical_contact_pairs": reports / f"{run_id}_canonical_contact_pairs.csv",
        "ranks": reports / "haddock3_model_ranks.csv",
    }


def validate_postprocess_marker(
    row: Mapping[str, str],
    run_root: Path,
    sync_root: Path,
    run_manifest_sha256: str,
    counts: Mapping[str, int],
    model_set: set[str],
    ranks: Mapping[str, Mapping[str, str]],
) -> list[str]:
    errors: list[str] = []
    run_id = row["run_id"]
    marker_path = run_root / "postprocess.complete.json"
    if not marker_path.is_file():
        return ["postprocess_marker_missing"]
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise ValueError("marker is not an object")
    except Exception as error:
        return [f"postprocess_marker_parse:{type(error).__name__}:{error}"]

    expected_identity = {
        "schema_version": POSTPROCESS_MARKER_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "status": "PASS",
        "run_id": run_id,
        "pilot_id": row["pilot_id"],
        "source_candidate_id": row.get("source_candidate_id", ""),
        "generation_receptor": row["receptor_id"].lower(),
        "seed_role": row["seed_role"],
        "run_manifest_sha256": run_manifest_sha256,
    }
    for field, expected in expected_identity.items():
        actual = marker.get(field)
        normalized = str(actual).lower() if field == "generation_receptor" else actual
        if normalized != expected:
            errors.append(f"marker_identity_mismatch:{field}:{actual}!={expected}")

    input_sha = marker.get("input_sha256")
    if not isinstance(input_sha, dict):
        errors.append("marker_input_sha256_not_object")
    else:
        for marker_field, manifest_field in (
            ("config", "config_sha256"),
            ("monomer", "monomer_sha256"),
            ("receptor", "receptor_sha256"),
        ):
            if input_sha.get(marker_field) != row.get(manifest_field, ""):
                errors.append(
                    f"marker_input_hash_mismatch:{marker_field}:"
                    f"{input_sha.get(marker_field)}!={row.get(manifest_field, '')}"
                )

    completion_relpath = row.get("completion_relpath", f"runs/{run_id}/{run_id}.complete.json")
    completion_path = Path(completion_relpath)
    if not completion_path.is_absolute():
        completion_path = sync_root / completion_path
    docking_marker = marker.get("docking_completion")
    if not isinstance(docking_marker, dict):
        errors.append("marker_docking_completion_not_object")
    elif not completion_path.is_file():
        errors.append(f"marker_docking_completion_missing:{completion_path}")
    else:
        observed_sha = sha256_file(completion_path)
        if docking_marker.get("sha256") != observed_sha:
            errors.append(
                f"marker_docking_completion_hash_mismatch:{docking_marker.get('sha256')}!={observed_sha}"
            )
        try:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            manifest_completion_identity = {
                "protocol_id": PROTOCOL_ID,
                "status": "PASS_DOCKING_OUTPUT_COMPLETE",
                "run_id": run_id,
                "pilot_id": row["pilot_id"],
                "source_candidate_id": row.get("source_candidate_id", ""),
                "seed_role": row["seed_role"],
            }
            for field, expected in manifest_completion_identity.items():
                if completion.get(field) != expected:
                    errors.append(
                        f"marker_docking_completion_manifest_mismatch:{field}:"
                        f"{completion.get(field)}!={expected}"
                    )
            if str(completion.get("receptor_id", "")).lower() != row["receptor_id"].lower():
                errors.append(
                    "marker_docking_completion_manifest_mismatch:receptor_id:"
                    f"{completion.get('receptor_id')}!={row['receptor_id']}"
                )
            for field in (
                "schema_version",
                "protocol_id",
                "status",
                "run_id",
                "pilot_id",
                "source_candidate_id",
                "receptor_id",
                "seed_role",
                "pose_count",
                "cluster_count",
            ):
                actual = docking_marker.get(field)
                expected = completion.get(field)
                if field == "receptor_id":
                    actual, expected = str(actual).lower(), str(expected).lower()
                if actual != expected:
                    errors.append(f"marker_docking_completion_identity_mismatch:{field}:{actual}!={expected}")
        except Exception as error:
            errors.append(f"marker_docking_completion_parse:{type(error).__name__}:{error}")

    marker_counts = marker.get("counts")
    if not isinstance(marker_counts, dict):
        errors.append("marker_counts_not_object")
    else:
        for field in POSTPROCESS_COUNT_FIELDS:
            if marker_counts.get(field) != counts.get(field):
                errors.append(f"marker_count_mismatch:{field}:{marker_counts.get(field)}!={counts.get(field)}")

    paths = postprocess_artifact_paths(run_root, run_id)
    artifact_marker = marker.get("artifacts")
    if not isinstance(artifact_marker, dict):
        errors.append("marker_artifacts_not_object")
    else:
        if set(artifact_marker) != set(POSTPROCESS_ARTIFACT_KEYS):
            errors.append(
                f"marker_artifact_keys_mismatch:{sorted(artifact_marker)}!={sorted(POSTPROCESS_ARTIFACT_KEYS)}"
            )
        for key, expected_path in paths.items():
            item = artifact_marker.get(key)
            if not isinstance(item, dict):
                errors.append(f"marker_artifact_missing:{key}")
                continue
            expected_relpath = str(expected_path.relative_to(run_root))
            if item.get("relpath") != expected_relpath:
                errors.append(f"marker_artifact_relpath_mismatch:{key}:{item.get('relpath')}!={expected_relpath}")
            if not expected_path.is_file():
                errors.append(f"marker_artifact_file_missing:{key}:{expected_path}")
                continue
            observed_sha = sha256_file(expected_path)
            if item.get("sha256") != observed_sha:
                errors.append(f"marker_artifact_hash_mismatch:{key}:{item.get('sha256')}!={observed_sha}")
        consensus_item = artifact_marker.get("consensus", {})
        if marker.get("consensus_sha256") != consensus_item.get("sha256"):
            errors.append("marker_consensus_sha256_mismatch")

    run_dir = resolve_evidence_path(sync_root, row, "run_dir_relpath", f"runs/{run_id}/run_{run_id}")
    selected_dir = run_dir / "6_seletopclusts"
    actual_files = {
        path.name: path
        for path in selected_dir.glob("cluster_*_model_*.pdb*")
        if path.is_file() and path.stat().st_size
    }
    selected_marker = marker.get("selected_pose_files")
    if not isinstance(selected_marker, list):
        errors.append("marker_selected_pose_files_not_list")
    else:
        marker_filenames: set[str] = set()
        marker_models: set[str] = set()
        for item in selected_marker:
            if not isinstance(item, dict):
                errors.append("marker_selected_pose_item_not_object")
                continue
            filename = str(item.get("filename", ""))
            model = str(item.get("model", ""))
            marker_filenames.add(filename)
            marker_models.add(model)
            path = actual_files.get(filename)
            if path is None:
                errors.append(f"marker_selected_pose_missing:{filename}")
                continue
            observed_sha = sha256_file(path)
            if item.get("sha256") != observed_sha:
                errors.append(f"marker_selected_pose_hash_mismatch:{filename}:{item.get('sha256')}!={observed_sha}")
            rank_row = ranks.get(model, {})
            try:
                marker_rank = parse_int(item.get("haddock_rank", ""), "marker_haddock_rank")
                rank_value = parse_int(rank_row.get("haddock_rank", ""), "rank_haddock_rank")
                if marker_rank != rank_value:
                    errors.append(f"marker_selected_pose_rank_mismatch:{model}:{marker_rank}!={rank_value}")
            except ValueError as error:
                errors.append(f"marker_selected_pose_rank_invalid:{model}:{error}")
        if marker_filenames != set(actual_files):
            errors.append(
                f"marker_selected_pose_file_set_mismatch:missing={sorted(set(actual_files)-marker_filenames)};"
                f"extra={sorted(marker_filenames-set(actual_files))}"
            )
        if marker_models != model_set:
            errors.append(
                f"marker_selected_pose_model_set_mismatch:missing={sorted(model_set-marker_models)};"
                f"extra={sorted(marker_models-model_set)}"
            )
    return errors


def evaluate_postprocessed_run(
    row: Mapping[str, str],
    postprocessed_root: Path,
    sync_root: Path,
    run_manifest_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    run_id = row["run_id"]
    receptor = row["receptor_id"].lower()
    run_root = postprocessed_root / run_id
    reports = run_root / "reports"
    errors: list[str] = []
    paths = postprocess_artifact_paths(run_root, run_id)
    consensus = indexed_rows(paths["consensus"], "consensus", errors)
    classifications = {
        baseline: indexed_rows(
            paths[f"classification_{baseline}"],
            f"classification_{baseline}",
            errors,
        )
        for baseline in RECEPTORS
    }
    mechanisms = {
        baseline: indexed_rows(
            paths[f"mechanism_{baseline}"],
            f"mechanism_{baseline}",
            errors,
        )
        for baseline in RECEPTORS
    }
    canonical = indexed_rows(paths["canonical_contact_summary"], "canonical_contact_summary", errors)
    ranks = indexed_rows(paths["ranks"], "ranks", errors)
    canonical_pairs: list[dict[str, str]] = []
    if paths["canonical_contact_pairs"].is_file():
        try:
            canonical_pairs = read_csv(paths["canonical_contact_pairs"])
        except Exception as error:
            errors.append(f"read_canonical_contact_pairs:{type(error).__name__}:{error}")
    else:
        errors.append(f"missing_canonical_contact_pairs:{paths['canonical_contact_pairs']}")
    model_set = set(consensus)
    for label, index in [
        *((f"classification_{key}", value) for key, value in classifications.items()),
        *((f"mechanism_{key}", value) for key, value in mechanisms.items()),
        ("canonical_contact_summary", canonical),
        ("ranks", ranks),
    ]:
        if set(index) != model_set:
            errors.append(
                f"model_set_{label}:missing={sorted(model_set-set(index))};extra={sorted(set(index)-model_set)}"
            )
    contact_failures = sum(item.get("status") != "PASS" for item in canonical.values())
    if len(canonical) != len(model_set):
        contact_failures += abs(len(model_set) - len(canonical))
    pair_counts = Counter(row.get("model", "") for row in canonical_pairs)
    if set(pair_counts) - model_set:
        errors.append(f"canonical_contact_pairs_extra_models:{sorted(set(pair_counts)-model_set)}")
    for model in model_set:
        try:
            declared = parse_int(
                canonical.get(model, {}).get("canonical_residue_pair_count", ""),
                "canonical_residue_pair_count",
            )
            if pair_counts[model] != declared:
                errors.append(f"canonical_contact_pair_count_mismatch:{model}:{pair_counts[model]}!={declared}")
                contact_failures += 1
        except ValueError as error:
            errors.append(f"canonical_contact_pair_count_invalid:{model}:{error}")
            contact_failures += 1

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
                    contact_failures += 1
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
            rank_from_artifact = parse_float(ranks.get(model, {}).get("haddock_rank", ""), "haddock_rank")
            if rank != rank_from_artifact:
                errors.append(f"consensus_rank_mismatch:{model}:{rank}!={rank_from_artifact}")
            relevance = pose_relevance(
                declared_counts["BLOCKER_LIKE_A"],
                declared_counts["BLOCKER_PLAUSIBLE_B"],
                declared_counts["BINDER_LIKE_C"],
            )
            weight = pose_weight(rank, cluster_counts[cluster])
            poses.append(
                {
                    "schema_version": "phase2_v3_p2_docking_gold_pose_v1_1",
                    "protocol_id": PROTOCOL_ID,
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
        "canonical_contact_pair_rows": len(canonical_pairs),
        "contact_failures": contact_failures,
    }
    marker_counts = {
        "selected_models": len(poses),
        "pose_clusters": cluster_count,
        "consensus_rows": len(consensus),
        "classification_8x6b_rows": len(classifications["8x6b"]),
        "classification_9e6y_rows": len(classifications["9e6y"]),
        "mechanism_8x6b_rows": len(mechanisms["8x6b"]),
        "mechanism_9e6y_rows": len(mechanisms["9e6y"]),
        "canonical_contact_pose_rows": len(canonical),
        "canonical_contact_pair_rows": len(canonical_pairs),
        "contact_failures": contact_failures,
    }
    errors.extend(
        validate_postprocess_marker(
            row,
            run_root,
            sync_root,
            run_manifest_sha256,
            marker_counts,
            model_set,
            ranks,
        )
    )
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
        "schema_version": "phase2_v3_p2_docking_gold_candidate_v1_1",
        "protocol_id": PROTOCOL_ID,
        "pilot_rank": pilot.get("pilot_rank", ""),
        "pilot_id": pilot["pilot_id"],
        "source_cohort": pilot.get("source_cohort", ""),
        "source_candidate_id": pilot.get("source_candidate_id", ""),
        "sequence": pilot.get("sequence", ""),
        "sequence_sha256": pilot.get("sequence_sha256", ""),
        "family": pilot.get("family", ""),
        "parent_framework_cluster": pilot.get("parent_framework_cluster", ""),
        "source_formal_split": pilot.get("source_formal_split", ""),
        "target_patch_id": pilot.get("target_patch_id", ""),
        "design_mode": pilot.get("design_mode", ""),
        "selection_stratum": pilot.get("selection_stratum", ""),
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
    per_candidate_failure_tolerance_override: bool,
    tolerance_relaxation: bool,
    spearman: float | None,
    quadratic_kappa: float | None,
    manifest_contract_pass: bool = True,
    package_closure_pass: bool = True,
) -> dict[str, Any]:
    gates = {
        "package_provenance_closure": package_closure_pass,
        "manifest_contract": manifest_contract_pass,
        "main_dg_a_64_of_64": main_complete == EXPECTED_PILOTS,
        "replicate_receptor_runs_32_of_32": replicate_complete == EXPECTED_REPLICATE_RUNS,
        "contact_failures_zero": contact_failures == 0,
        "per_candidate_failure_tolerance_override_false": not per_candidate_failure_tolerance_override,
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
        f"- 协议：`{PROTOCOL_ID}`",
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
    package_closure, package_closure_errors = validate_package_closure(
        args.selection_manifest, args.run_manifest
    )
    _runs_by_id, contract_errors = manifest_contract(selection_rows, run_rows)
    selection = {row["pilot_id"]: row for row in selection_rows}
    all_pose_rows: list[dict[str, Any]] = []
    receptor_rows: list[dict[str, Any]] = []
    global_failure_tolerance_override = False
    global_tolerance_relaxation = False
    run_manifest_sha256 = sha256_file(args.run_manifest)
    package_root = args.run_manifest.resolve().parent.parent
    for manifest_row in run_rows:
        protocol, protocol_errors = run_protocol_checks(
            manifest_row, args.sync_root, package_root
        )
        poses, postprocess, postprocess_errors = evaluate_postprocessed_run(
            manifest_row,
            args.postprocessed_root,
            args.sync_root,
            run_manifest_sha256,
        )
        errors = [*protocol_errors, *postprocess_errors]
        completion_pose_count = protocol.get("completion_pose_count", "")
        completion_cluster_count = protocol.get("completion_cluster_count", "")
        if str(completion_pose_count).strip():
            try:
                if parse_int(completion_pose_count, "completion_pose_count") < postprocess["selected_poses"]:
                    errors.append(
                        f"completion_pose_count_below_postprocess:{completion_pose_count}<{postprocess['selected_poses']}"
                    )
            except ValueError:
                pass
        if str(completion_cluster_count).strip():
            try:
                if parse_int(completion_cluster_count, "completion_cluster_count") < postprocess["pose_clusters"]:
                    errors.append(
                        f"completion_cluster_count_below_postprocess:{completion_cluster_count}<{postprocess['pose_clusters']}"
                    )
            except ValueError:
                pass
        global_failure_tolerance_override |= bool(
            protocol.get("per_candidate_failure_tolerance_override", True)
        )
        global_tolerance_relaxation |= bool(protocol.get("tolerance_relaxed", True))
        dg_a = not errors
        all_pose_rows.extend(poses)
        receptor_rows.append(
            {
                "schema_version": "phase2_v3_p2_docking_gold_receptor_v1_1",
                "protocol_id": PROTOCOL_ID,
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
                "stage_output_counts": json.dumps(
                    protocol.get("runtime_stage_output_counts", {}), sort_keys=True, separators=(",", ":")
                ),
                "per_candidate_failure_tolerance_override": protocol.get(
                    "per_candidate_failure_tolerance_override", True
                ),
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
                "schema_version": "phase2_v3_p2_docking_gold_replicate_comparison_v1_1",
                "protocol_id": PROTOCOL_ID,
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
        global_failure_tolerance_override,
        global_tolerance_relaxation,
        spearman,
        quadratic_kappa,
        manifest_contract_pass=not contract_errors,
        package_closure_pass=not package_closure_errors,
    )

    args.outdir.mkdir(parents=True, exist_ok=True)
    pose_path = args.outdir / "phase2_v3_p2_docking_gold_pose.csv"
    receptor_path = args.outdir / "phase2_v3_p2_docking_gold_receptor.csv"
    candidate_path = args.outdir / "phase2_v3_p2_docking_gold_candidate.csv"
    comparison_path = args.outdir / "phase2_v3_p2_docking_gold_replicate_comparison.csv"
    write_csv(pose_path, all_pose_rows, ["schema_version", "protocol_id", "pilot_id", "run_id", "receptor_id", "seed_role", "model"])
    serializable_receptors = [{key: value for key, value in row.items() if key != "r_receptor_raw"} for row in receptor_rows]
    write_csv(receptor_path, serializable_receptors, ["schema_version", "protocol_id", "pilot_id", "run_id", "receptor_id", "seed_role"])
    write_csv(candidate_path, main_candidates, ["schema_version", "protocol_id", "pilot_rank", "pilot_id", "source_candidate_id", "R_gold"])
    write_csv(comparison_path, comparisons, ["schema_version", "protocol_id", "pilot_id", "source_candidate_id", "main_R_gold", "replicate_R_gold"])
    audit: dict[str, Any] = {
        "schema_version": "phase2_v3_p2_docking_gold_audit_v1_1",
        "protocol_id": PROTOCOL_ID,
        **gate,
        "inputs": {
            "selection_manifest": str(args.selection_manifest),
            "selection_manifest_sha256": sha256_file(args.selection_manifest),
            "run_manifest": str(args.run_manifest),
            "run_manifest_sha256": run_manifest_sha256,
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
            "emref_tolerance": FROZEN_EMREF_TOLERANCE,
            "stage_output_requirements": {
                stage: {"operator": operator, "value": value}
                for stage, (operator, value) in STAGE_OUTPUT_REQUIREMENTS.items()
            },
            "per_candidate_failure_tolerance_override_observed": global_failure_tolerance_override,
            "tolerance_relaxation_observed": global_tolerance_relaxation,
        },
        "package_closure": package_closure,
        "package_closure_errors": package_closure_errors,
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
