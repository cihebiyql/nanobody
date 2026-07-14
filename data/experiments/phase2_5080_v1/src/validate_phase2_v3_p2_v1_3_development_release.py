#!/usr/bin/env python3
"""Independently release the V1.3 dual-receptor development decision.

The calibrator is intentionally unable to authorize downstream smoke work.  This
validator consumes two byte-identical, independently published calibrator
releases, revalidates their immutable inputs and preregistered gates, and is the
only V1.3 component that can emit the development PASS status.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
WORKSPACE_ROOT = EXP_DIR.parents[1]
ANTIBODY_ROOT = WORKSPACE_ROOT.parent

SCHEMA_VERSION = "pvrig_v1_3_dual_receptor_development_release_v1"
PROTOCOL_ID = "DG_A_PVRIG_V1_3_DUAL_NATIVE_DEV"
METHOD_ID = "PVRIG_V1_3_NATIVE_DUAL_RECEPTOR_CALIBRATION_V1"
PASS_STATUS = "PASS_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD"
FAIL_STATUS = "FAIL_V1_3_DUAL_RECEPTOR_DEVELOPMENT_METHOD_NOT_FROZEN"
SOURCE_AUDIT_STATUS = "CALCULATED_PENDING_RELEASE_VALIDATION"
SOURCE_INPUT_STATUS = "PENDING_EXTERNAL_RELEASE_VALIDATION"
SOURCE_GATE_PASS = "COMPUTED_GATES_SATISFIED"
SOURCE_GATE_FAIL = "COMPUTED_GATES_NOT_SATISFIED"
RELEASE_NAME = "pvrig_v1_3_development_release.json"
CALIBRATION_AUDIT_NAME = "pvrig_v1_3_native_dual_calibration_audit.json"
RELEASE_INPUT_NAME = "pvrig_v1_3_calibration_release_input.json"
RULES_NAME = "pvrig_v1_3_native_dual_rules.json"
REPORT_NAME = "PVRIG_V3_P2_DOCKING_GOLD_V1_3_NATIVE_DUAL_CALIBRATION_ZH.md"
BOOTSTRAP_SEED = 20260714
BOOTSTRAP_REPLICATES = 2000
CLAIM_BOUNDARY = (
    "Independent native 8X6B/9E6Y computational geometry development only; "
    "not Docking Gold, a training label, binder truth, affinity/Kd truth, or "
    "experimental blocking truth."
)

DEFAULT_CALIBRATION_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_native_dual_calibration"
)
DEFAULT_PRIMARY_RELEASE_INPUT = DEFAULT_CALIBRATION_ROOT / "current" / RELEASE_INPUT_NAME
DEFAULT_PREREGISTRATION = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_development_preregistration.json"
)
DEFAULT_ANCHOR_READINESS = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_anchor_readiness_audit.json"
)
DEFAULT_EXECUTION_RELEASE = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_docking_execution_release_manifest.json"
)
DEFAULT_PACKAGE_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_completion15_package"
)
DEFAULT_CASE_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/case_manifest.csv"
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/run_manifest.csv"
DEFAULT_PROTOCOL_MANIFEST = DEFAULT_PACKAGE_ROOT / "manifests/protocol_manifest.csv"
DEFAULT_SELECTOR_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_top8_recovery"
)
DEFAULT_SELECTOR_CSV = (
    DEFAULT_SELECTOR_ROOT / "current/pvrig_v1_3_dual47_emref_top8_selector.csv"
)
DEFAULT_SELECTOR_AUDIT = (
    DEFAULT_SELECTOR_ROOT / "current/pvrig_v1_3_dual47_emref_top8_recovery_audit.json"
)
DEFAULT_PROCESSING_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_native_processing"
)
DEFAULT_METRICS_CSV = (
    DEFAULT_PROCESSING_ROOT / "current/pvrig_v1_3_native_top8_continuous_metrics.csv"
)
DEFAULT_PROCESSOR_AUDIT = (
    DEFAULT_PROCESSING_ROOT / "current/pvrig_v1_3_native_top8_processing_audit.json"
)
DEFAULT_PROCESSOR_QUALIFICATION = (
    EXP_DIR
    / "runs/pvrig_v3_p2/docking_gold_v1_3_native_processor_qualification/"
    "current/pvrig_v1_3_native_processor_qualification.json"
)
DEFAULT_POSITIVE_MANIFEST = (
    ANTIBODY_ROOT / "docking/calibration/patent_success_validation/batch_manifest.csv"
)
DEFAULT_MUTANT_MANIFEST = (
    ANTIBODY_ROOT / "docking/calibration/mutant_validation_panel/mutant_panel.csv"
)
DEFAULT_CALIBRATOR = SCRIPT_DIR / "calibrate_phase2_v3_p2_v1_3_dual_native.py"
DEFAULT_CALIBRATOR_TEST = (
    SCRIPT_DIR / "test_calibrate_phase2_v3_p2_v1_3_dual_native.py"
)
DEFAULT_VALIDATOR_TEST = (
    SCRIPT_DIR / "test_validate_phase2_v3_p2_v1_3_development_release.py"
)
DEFAULT_OUTDIR = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_development_release"
)

CSV_OUTPUTS: dict[str, tuple[int, str]] = {
    "pvrig_v1_3_native_pose_scores.csv": (752, "pose_score_row_sha256"),
    "pvrig_v1_3_native_run_scores.csv": (94, "run_score_row_sha256"),
    "pvrig_v1_3_dual_candidate_scores.csv": (47, "dual_score_row_sha256"),
    "pvrig_v1_3_family_lofo.csv": (11, "lofo_row_sha256"),
    "pvrig_v1_3_bootstrap_thresholds.csv": (
        20000,
        "bootstrap_threshold_row_sha256",
    ),
    "pvrig_v1_3_bootstrap_receptor_anchor_evaluations.csv": (
        44000,
        "bootstrap_receptor_row_sha256",
    ),
    "pvrig_v1_3_bootstrap_dual_anchor_evaluations.csv": (
        22000,
        "bootstrap_dual_row_sha256",
    ),
    "pvrig_v1_3_mutant_paired_deltas.csv": (
        29,
        "mutant_delta_row_sha256",
    ),
    "pvrig_v1_3_robustness_grid.csv": (54, "robustness_row_sha256"),
}
EXPECTED_RELEASE_FILES = frozenset(
    {RULES_NAME, REPORT_NAME, CALIBRATION_AUDIT_NAME, RELEASE_INPUT_NAME}
    | set(CSV_OUTPUTS)
)
REQUIRED_GATES = (
    "frozen_upstream",
    "cohort_closure",
    "run_closure",
    "pose_closure",
    "metric_closure",
    "protocol_hash_closure",
    "ATOM_only",
    "five_channel_threshold_validity",
    "family_and_receptor_balance",
    "central_and_54_grid",
    "LOFO",
    "bootstrap",
    "receptor_consistency",
    "mutant_sensitivity",
    "diagnostic_isolation",
    "claim_boundary",
    "formal_veto",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CALC_RELEASE_RE = re.compile(r"^calc-[0-9a-f]{24}$")
PointerPromoter = Callable[[Path, Path], None]


class ReleaseError(RuntimeError):
    """Raised when a release input is not independently releasable."""


@dataclass(frozen=True)
class ReleaseConfig:
    primary_release_input: Path
    rebuild_release_input: Path
    preregistration: Path = DEFAULT_PREREGISTRATION
    anchor_readiness: Path = DEFAULT_ANCHOR_READINESS
    execution_release: Path = DEFAULT_EXECUTION_RELEASE
    case_manifest: Path = DEFAULT_CASE_MANIFEST
    run_manifest: Path = DEFAULT_RUN_MANIFEST
    protocol_manifest: Path = DEFAULT_PROTOCOL_MANIFEST
    selector_csv: Path = DEFAULT_SELECTOR_CSV
    selector_audit: Path = DEFAULT_SELECTOR_AUDIT
    metrics_csv: Path = DEFAULT_METRICS_CSV
    processor_audit: Path = DEFAULT_PROCESSOR_AUDIT
    processor_qualification: Path = DEFAULT_PROCESSOR_QUALIFICATION
    positive_manifest: Path = DEFAULT_POSITIVE_MANIFEST
    mutant_manifest: Path = DEFAULT_MUTANT_MANIFEST
    calibrator: Path = DEFAULT_CALIBRATOR
    calibrator_test: Path = DEFAULT_CALIBRATOR_TEST
    outdir: Path = DEFAULT_OUTDIR


@dataclass(frozen=True)
class SourceRelease:
    release_input_path: Path
    root: Path
    release_dir: Path
    release_id: str
    release_input: dict[str, Any]
    audit: dict[str, Any]
    rules: dict[str, Any]
    rows: dict[str, list[dict[str, str]]]
    inventory: dict[str, dict[str, Any]]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def sha256_file(path: Path) -> str:
    if not path.is_file():
        raise ReleaseError(f"Required file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseError(f"Invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ReleaseError(f"{label} must be a JSON object: {path}")
    return value


def read_csv(path: Path, hash_field: str) -> list[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if (
                not reader.fieldnames
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or hash_field not in reader.fieldnames
            ):
                raise ReleaseError(f"Invalid CSV header: {path}")
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise ReleaseError(f"Invalid CSV output: {path}") from error
    for number, row in enumerate(rows, start=2):
        observed = row.get(hash_field, "")
        expected = sha256_json({key: value for key, value in row.items() if key != hash_field})
        if observed != expected:
            raise ReleaseError(f"Row hash mismatch: {path}:{number}")
    return rows


def row_hash_chain(rows: Sequence[Mapping[str, str]], hash_field: str) -> str:
    return sha256_json([row[hash_field] for row in rows])


def csv_count(path: Path) -> int:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            next(reader)
            return sum(1 for _ in reader)
    except (OSError, UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise ReleaseError(f"Cannot count manifest rows: {path}") from error


def inventory(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseError(f"Symlink inside immutable release is forbidden: {path}")
        if path.is_file():
            relpath = path.relative_to(root).as_posix()
            entries[relpath] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    return entries


def require_false_boundaries(
    payload: Mapping[str, Any], label: str, *, require_p2: bool = True
) -> None:
    fields = [
        "formal_eligible",
        "docking_gold_release_eligible",
        "training_label_release_eligible",
    ]
    if require_p2:
        fields.append("p2_training_ready")
    for field in fields:
        if payload.get(field) is not False:
            raise ReleaseError(f"{label} violates unconditional {field}=false")


def validate_source_publication(path: Path) -> SourceRelease:
    lexical = Path(os.path.abspath(path))
    if lexical.name != RELEASE_INPUT_NAME or lexical.parent.name != "current":
        raise ReleaseError("Calibrator release input must be selected through root/current")
    current = lexical.parent
    root = current.parent
    if not current.is_symlink():
        raise ReleaseError(f"Calibrator current pointer is not a symlink: {current}")
    target_text = os.readlink(current)
    if os.path.isabs(target_text):
        raise ReleaseError("Calibrator current pointer must use a relative target")
    release_dir = current.resolve()
    releases_root = (root / "releases").resolve()
    if release_dir.parent != releases_root or not release_dir.is_dir():
        raise ReleaseError("Calibrator current pointer escapes releases/")
    release_id = release_dir.name
    if not CALC_RELEASE_RE.fullmatch(release_id):
        raise ReleaseError(f"Invalid calibrator release id: {release_id}")
    if lexical.resolve() != (release_dir / RELEASE_INPUT_NAME).resolve():
        raise ReleaseError("Calibrator release-input pointer identity mismatch")

    release_inventory = inventory(release_dir)
    if set(release_inventory) != EXPECTED_RELEASE_FILES:
        missing = sorted(EXPECTED_RELEASE_FILES - set(release_inventory))
        extra = sorted(set(release_inventory) - EXPECTED_RELEASE_FILES)
        raise ReleaseError(f"Immutable calibrator inventory mismatch: missing={missing}, extra={extra}")
    release_input = read_json(release_dir / RELEASE_INPUT_NAME, "release input")
    audit = read_json(release_dir / CALIBRATION_AUDIT_NAME, "calibration audit")
    rules = read_json(release_dir / RULES_NAME, "calibration rules")
    if PASS_STATUS.encode("ascii") in b"".join(
        (release_dir / name).read_bytes() for name in sorted(EXPECTED_RELEASE_FILES)
    ):
        raise ReleaseError("Calibrator publication attempted to self-emit development PASS")

    expected_input = {
        "schema_version": "pvrig_v1_3_calibration_release_input_v1",
        "status": SOURCE_INPUT_STATUS,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "release_id": release_id,
        "calculation_status": SOURCE_AUDIT_STATUS,
        "external_validator_required": True,
        "development_smoke_eligible": False,
    }
    expected_audit = {
        "schema_version": "pvrig_v1_3_native_dual_receptor_calibration_v1",
        "status": SOURCE_AUDIT_STATUS,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "external_release_validation_required": True,
        "development_smoke_eligible": False,
    }
    expected_rules = {
        "schema_version": "pvrig_v1_3_native_dual_receptor_calibration_v1",
        "status": SOURCE_AUDIT_STATUS,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "external_release_validation_required": True,
        "development_smoke_eligible": False,
    }
    for label, payload, expected in (
        ("release input", release_input, expected_input),
        ("calibration audit", audit, expected_audit),
        ("calibration rules", rules, expected_rules),
    ):
        mismatches = {key: (payload.get(key), value) for key, value in expected.items() if payload.get(key) != value}
        if mismatches:
            raise ReleaseError(f"{label} contract mismatch: {mismatches}")
        require_false_boundaries(payload, label)

    publication = audit.get("publication")
    if not isinstance(publication, dict):
        raise ReleaseError("Calibration audit lacks publication contract")
    expected_publication = {
        "release_id": release_id,
        "release_relpath": f"releases/{release_id}",
        "current_pointer_relpath": "current",
        "immutable_versioned_release": True,
        "promotion": "single atomic current symlink replacement",
        "rollback_safe": True,
    }
    if any(publication.get(key) != value for key, value in expected_publication.items()):
        raise ReleaseError("Calibration immutable publication contract mismatch")
    audit_binding = release_input.get("calibration_audit")
    if not isinstance(audit_binding, dict) or audit_binding != {
        "relpath": CALIBRATION_AUDIT_NAME,
        "sha256": sha256_file(release_dir / CALIBRATION_AUDIT_NAME),
    }:
        raise ReleaseError("Release input does not bind the calibration audit")
    report = audit.get("report")
    if not isinstance(report, dict) or report != {
        "relpath": REPORT_NAME,
        "sha256": sha256_file(release_dir / REPORT_NAME),
    }:
        raise ReleaseError("Calibration audit does not bind the report")

    rows: dict[str, list[dict[str, str]]] = {}
    audit_ledger = audit.get("output_sha256")
    input_ledger = release_input.get("output_sha256")
    if not isinstance(audit_ledger, dict) or audit_ledger != input_ledger:
        raise ReleaseError("Audit/release-input output ledgers differ")
    if set(audit_ledger) != {RULES_NAME, *CSV_OUTPUTS}:
        raise ReleaseError("Frozen calibration output ledger is incomplete")
    rules_binding = audit_ledger.get(RULES_NAME)
    if rules_binding != {"sha256": sha256_file(release_dir / RULES_NAME)}:
        raise ReleaseError("Rules hash binding mismatch")
    for name, (expected_rows, hash_field) in CSV_OUTPUTS.items():
        table = read_csv(release_dir / name, hash_field)
        if len(table) != expected_rows:
            raise ReleaseError(f"{name} cardinality mismatch: {len(table)} != {expected_rows}")
        expected_binding = {
            "sha256": sha256_file(release_dir / name),
            "rows": expected_rows,
            "row_hash_chain": row_hash_chain(table, hash_field),
        }
        if audit_ledger.get(name) != expected_binding:
            raise ReleaseError(f"{name} hash/row-chain binding mismatch")
        rows[name] = table
    return SourceRelease(
        release_input_path=lexical,
        root=root,
        release_dir=release_dir,
        release_id=release_id,
        release_input=release_input,
        audit=audit,
        rules=rules,
        rows=rows,
        inventory=release_inventory,
    )


def validate_deterministic_pair(primary: SourceRelease, rebuild: SourceRelease) -> None:
    if primary.root.resolve() == rebuild.root.resolve():
        raise ReleaseError("Independent calibrator publications must have distinct roots")
    if primary.release_dir.resolve() == rebuild.release_dir.resolve():
        raise ReleaseError("A calibrator release cannot self-qualify as its own rebuild")
    if primary.release_id != rebuild.release_id:
        raise ReleaseError("Independent content-addressed release IDs differ")
    if primary.inventory != rebuild.inventory:
        raise ReleaseError("Independent immutable release inventories differ")
    for name in sorted(EXPECTED_RELEASE_FILES):
        if (primary.release_dir / name).read_bytes() != (rebuild.release_dir / name).read_bytes():
            raise ReleaseError(f"Independent output bytes differ: {name}")


def require_hash(value: Any, path: Path, label: str) -> None:
    observed = sha256_file(path.resolve())
    if value != observed or not SHA256_RE.fullmatch(str(value)):
        raise ReleaseError(f"Frozen hash binding mismatch for {label}")


def execution_artifact_hashes(payload: Mapping[str, Any]) -> dict[str, str]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ReleaseError("Execution release lacks artifact ledger")
    result: dict[str, str] = {}
    for item in artifacts:
        if not isinstance(item, dict) or not item.get("path") or not item.get("sha256"):
            raise ReleaseError("Malformed execution-release artifact")
        path = str(item["path"])
        if path in result:
            raise ReleaseError(f"Duplicate execution-release artifact: {path}")
        result[path] = str(item["sha256"])
    return result


def workspace_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def validate_upstream(
    config: ReleaseConfig, source: SourceRelease
) -> tuple[dict[str, str], dict[str, Any]]:
    paths = {
        "preregistration": config.preregistration.resolve(),
        "anchor_readiness": config.anchor_readiness.resolve(),
        "execution_release": config.execution_release.resolve(),
        "case_manifest": config.case_manifest.resolve(),
        "run_manifest": config.run_manifest.resolve(),
        "protocol_manifest": config.protocol_manifest.resolve(),
        "selector_csv": config.selector_csv.resolve(),
        "selector_audit": config.selector_audit.resolve(),
        "continuous_metrics": config.metrics_csv.resolve(),
        "processor_audit": config.processor_audit.resolve(),
        "processor_qualification": config.processor_qualification.resolve(),
        "positive_manifest": config.positive_manifest.resolve(),
        "mutant_manifest": config.mutant_manifest.resolve(),
        "calibrator": config.calibrator.resolve(),
        "calibrator_test": config.calibrator_test.resolve(),
    }
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    prereg = read_json(paths["preregistration"], "preregistration")
    anchor = read_json(paths["anchor_readiness"], "anchor readiness")
    execution = read_json(paths["execution_release"], "execution release")
    selector = read_json(paths["selector_audit"], "selector audit")
    processor = read_json(paths["processor_audit"], "processor audit")
    qualification = read_json(paths["processor_qualification"], "processor qualification")

    if (
        prereg.get("schema_version")
        != "phase2_v3_p2_docking_gold_v1_3_development_preregistration_v1"
        or prereg.get("status")
        != "PREREGISTERED_V1_3_DEVELOPMENT_ONLY_PENDING_IMPLEMENTATION"
        or prereg.get("development_acceptance", {}).get("pass_status") != PASS_STATUS
        or prereg.get("development_acceptance", {}).get("fail_status") != FAIL_STATUS
        or tuple(prereg.get("development_acceptance", {}).get("gates", [])) != REQUIRED_GATES
        or prereg.get("bootstrap", {}).get("seed") != BOOTSTRAP_SEED
        or prereg.get("bootstrap", {}).get("replicates") != BOOTSTRAP_REPLICATES
    ):
        raise ReleaseError("Preregistration contract mismatch")
    anchor_observed = anchor.get("observed_registered_evidence", {})
    anchor_decision = anchor.get("decision", {})
    if (
        anchor.get("status") != "FAIL_FORMAL_ANCHOR_READINESS_ZERO_NEW_FAMILIES"
        or anchor_observed.get("anchor_count") != 11
        or anchor_observed.get("family_count") != 5
        or anchor_observed.get("new_eligible_independent_family_count") != 0
        or anchor.get("unconditional_veto", {}).get("active") is not True
        or anchor_decision.get("v1_3_formal_validation_permitted") is not False
        or anchor_decision.get("docking_gold_release_permitted") is not False
        or anchor_decision.get("training_label_release_permitted") is not False
        or anchor_decision.get("p2_training_ready") is not False
    ):
        raise ReleaseError("Anchor-readiness veto is not the frozen zero-new-family state")
    if (
        execution.get("schema_version")
        != "phase2_v3_p2_v1_3_docking_execution_release_v1"
        or execution.get("status") != "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE"
        or execution.get("execution_closure", {}).get("total_main_run_count") != 94
    ):
        raise ReleaseError("Execution release contract mismatch")
    require_false_boundaries(execution, "execution release")
    ledger = execution_artifact_hashes(execution)
    for name in ("preregistration", "case_manifest", "run_manifest", "protocol_manifest"):
        if ledger.get(workspace_relpath(paths[name])) != hashes[name]:
            raise ReleaseError(f"Execution release does not bind {name}")

    input_bindings = source.audit.get("input_bindings")
    upstream = source.release_input.get("upstream_sha256")
    if not isinstance(input_bindings, dict) or not isinstance(upstream, dict):
        raise ReleaseError("Calibration source lacks frozen upstream bindings")
    direct = {
        "preregistration": "preregistration",
        "execution_release": "execution_release",
        "selector_csv": "selector_csv",
        "selector_audit": "selector_audit",
        "processor_audit": "processor_audit",
        "processor_qualification": "processor_qualification",
        "continuous_metrics": "continuous_metrics",
        "positive_manifest": "positive_manifest",
        "mutant_manifest": "mutant_manifest",
    }
    for input_name, hash_name in direct.items():
        if upstream.get(input_name) != hashes[hash_name]:
            raise ReleaseError(f"Release input does not bind {input_name}")
    nested = {
        "preregistration": ("preregistration",),
        "execution_release": ("execution_release",),
        "selector_csv": ("selector_publication", "selector_csv"),
        "selector_audit": ("selector_publication", "selector_audit"),
        "processor_audit": ("processor_audit",),
        "processor_qualification": ("processor_qualification",),
        "continuous_metrics": ("continuous_metrics",),
        "positive_manifest": ("positive_manifest",),
        "mutant_manifest": ("mutant_manifest",),
    }
    for hash_name, keys in nested.items():
        value: Any = input_bindings
        for key in keys:
            value = value.get(key) if isinstance(value, dict) else None
        if not isinstance(value, dict) or value.get("sha256") != hashes[hash_name]:
            raise ReleaseError(f"Calibration audit does not bind {hash_name}")

    frozen = input_bindings.get("frozen_manifests", {})
    for name in ("case_manifest", "run_manifest", "protocol_manifest"):
        if frozen.get(name, {}).get("sha256") != hashes[name]:
            raise ReleaseError(f"Calibration audit does not bind {name}")
    if (
        frozen.get("case_count") != 47
        or frozen.get("run_count") != 94
        or frozen.get("protocol_count") != 2
        or csv_count(paths["case_manifest"]) != 47
        or csv_count(paths["run_manifest"]) != 94
        or csv_count(paths["protocol_manifest"]) != 2
    ):
        raise ReleaseError("Frozen 47-case/94-run/two-protocol closure failed")

    selector_counts = selector.get("counts", {})
    if (
        selector.get("status") != "PASS_V1_3_DUAL47_EMREF_TOP8_RECOVERED"
        or selector_counts.get("selected_runs") != 94
        or selector_counts.get("selected_poses") != 752
        or selector.get("selection_backfill") is not False
        or selector.get("scoring_performed") is not False
        or csv_count(paths["selector_csv"]) != 752
    ):
        raise ReleaseError("Selector 94-run/752-pose evidence failed")
    require_false_boundaries(selector, "selector audit", require_p2=False)
    observed = processor.get("observed_contract", {})
    if (
        processor.get("schema_version") != "pvrig_v1_3_native_top8_processing_audit_v1"
        or processor.get("status") != "BUILT_PENDING_DEVELOPMENT_RELEASE"
        or processor.get("native_only") is not True
        or observed.get("case_count") != 47
        or observed.get("run_count") != 94
        or observed.get("metric_rows") != 752
        or observed.get("aligned_pose_files") != 752
        or observed.get("rows_by_generation_receptor") != {"8X6B": 376, "9E6Y": 376}
        or csv_count(paths["continuous_metrics"]) != 752
    ):
        raise ReleaseError("Native processor 94-run/752-metric evidence failed")
    require_false_boundaries(processor, "processor audit")
    qualified = qualification.get("qualified_input", {})
    if (
        qualification.get("schema_version")
        != "pvrig_v1_3_native_processor_qualification_v1"
        or qualification.get("status") != "QUALIFIED_NATIVE_PROCESSOR_INPUT"
        or qualification.get("calibration_input_eligible") is not True
        or qualification.get("determinism", {}).get("independent_publication_count") != 2
        or qualified.get("processor_audit_sha256") != hashes["processor_audit"]
        or qualified.get("continuous_metrics_sha256") != hashes["continuous_metrics"]
        or qualified.get("selector_csv_sha256") != hashes["selector_csv"]
        or qualified.get("selector_audit_sha256") != hashes["selector_audit"]
        or qualified.get("case_manifest_sha256") != hashes["case_manifest"]
        or qualified.get("run_manifest_sha256") != hashes["run_manifest"]
        or qualified.get("protocol_manifest_sha256") != hashes["protocol_manifest"]
    ):
        raise ReleaseError("Independent processor qualification evidence failed")
    require_false_boundaries(qualification, "processor qualification")

    implementation = source.audit.get("implementation")
    calibrator_binding = source.release_input.get("calibrator")
    expected_impl = {
        "relpath": workspace_relpath(paths["calibrator"]),
        "sha256": hashes["calibrator"],
        "test_relpath": workspace_relpath(paths["calibrator_test"]),
        "test_sha256": hashes["calibrator_test"],
    }
    if implementation != expected_impl or calibrator_binding != expected_impl:
        raise ReleaseError("Calibrator implementation/test hash binding mismatch")
    return hashes, {
        "preregistration": prereg,
        "anchor_readiness": anchor,
        "execution_release": execution,
        "selector_audit": selector,
        "processor_audit": processor,
        "processor_qualification": qualification,
    }


def bool_text(row: Mapping[str, str], field: str) -> bool:
    value = row.get(field)
    if value not in {"true", "false"}:
        raise ReleaseError(f"Non-boolean CSV value for {field}: {value!r}")
    return value == "true"


def validate_common_row_boundaries(rows: Sequence[Mapping[str, str]], label: str) -> None:
    for number, row in enumerate(rows, start=2):
        for field in (
            "formal_eligible",
            "docking_gold_release_eligible",
            "training_label_release_eligible",
        ):
            if row.get(field) != "false":
                raise ReleaseError(f"{label}:{number} violates {field}=false")


def recompute_lofo(rows: Sequence[Mapping[str, str]]) -> tuple[bool, dict[str, Any]]:
    by_family: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        by_family[row["held_out_family"]].append(row)
    if len(by_family) != 5 or len({row["held_out_candidate_id"] for row in rows}) != 11:
        return False, {"reason": "family_or_anchor_closure"}
    recalls: list[float] = []
    shifts: list[int] = []
    families: dict[str, Any] = {}
    for family, family_rows in sorted(by_family.items()):
        defined = all(bool_text(row, "fold_defined") for row in family_rows)
        retained = sum(bool_text(row, "held_out_G1_G3_retained") for row in family_rows)
        recall = retained / len(family_rows)
        recalls.append(recall)
        shifts.extend(int(row["absolute_dual_tier_shift"]) for row in family_rows if bool_text(row, "fold_defined"))
        families[family] = {"defined": defined, "retained": retained, "recall": recall}
    macro = sum(recalls) / len(recalls)
    passed = (
        len(shifts) == 11
        and all(item["defined"] and item["retained"] >= 1 for item in families.values())
        and macro >= 0.80
        and sum(shift <= 1 for shift in shifts) >= 9
        and max(shifts) <= 2
    )
    return passed, {"macro_family_G1_G3_recall": macro, "families": families}


def validate_bootstrap_tables(
    threshold_rows: Sequence[Mapping[str, str]],
    receptor_rows: Sequence[Mapping[str, str]],
    dual_rows: Sequence[Mapping[str, str]],
) -> tuple[bool, bool, dict[str, Any]]:
    expected_ids = set(range(1, BOOTSTRAP_REPLICATES + 1))
    for rows, expected_per_replicate, label in (
        (threshold_rows, 10, "threshold"),
        (receptor_rows, 22, "receptor"),
        (dual_rows, 11, "dual"),
    ):
        counts: Counter[int] = Counter()
        for row in rows:
            if int(row["bootstrap_seed"]) != BOOTSTRAP_SEED:
                raise ReleaseError(f"{label} bootstrap seed drift")
            counts[int(row["bootstrap_replicate"])] += 1
        if set(counts) != expected_ids or set(counts.values()) != {expected_per_replicate}:
            raise ReleaseError(f"{label} B=2000 replicate cardinality failed")
    threshold_keys: dict[int, set[tuple[str, str]]] = defaultdict(set)
    for row in threshold_rows:
        threshold_keys[int(row["bootstrap_replicate"])].add((row["channel"], row["cutpoint"]))
    if any(len(keys) != 10 for keys in threshold_keys.values()):
        raise ReleaseError("Bootstrap five-channel/two-cutpoint closure failed")

    by_candidate: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    family_by_candidate: dict[str, str] = {}
    for row in dual_rows:
        by_candidate[row["candidate_id"]].append(row)
        family_by_candidate[row["candidate_id"]] = row["family"]
    if len(by_candidate) != 11 or len(set(family_by_candidate.values())) != 5:
        raise ReleaseError("Bootstrap 11-anchor/five-family closure failed")
    modal_count = 0
    consistency_count = 0
    family_retention: dict[str, list[float]] = defaultdict(list)
    family_both_non_e: dict[str, list[float]] = defaultdict(list)
    strength = {"G1": 4, "G2": 3, "G3": 2, "G4": 1, "G5": 0}
    anchor_summary: dict[str, Any] = {}
    for candidate, candidate_rows in sorted(by_candidate.items()):
        if len(candidate_rows) != BOOTSTRAP_REPLICATES:
            raise ReleaseError(f"Bootstrap candidate replicate closure failed: {candidate}")
        defined = [row for row in candidate_rows if bool_text(row, "evaluation_defined")]
        tiers = Counter(row["dual_tier"] for row in defined)
        if not set(tiers) <= set(strength):
            raise ReleaseError(f"Unknown bootstrap dual tier for {candidate}")
        modal = max(strength, key=lambda tier: (tiers[tier], strength[tier]))
        modal_probability = tiers[modal] / BOOTSTRAP_REPLICATES
        retention = sum(tiers[tier] for tier in ("G1", "G2", "G3")) / BOOTSTRAP_REPLICATES
        consistency = sum(int(row["class_ordinal_gap"]) <= 1 for row in defined) / BOOTSTRAP_REPLICATES
        both_non_e = sum(bool_text(row, "both_native_non_E") for row in defined) / BOOTSTRAP_REPLICATES
        modal_count += int(modal_probability >= 0.70)
        consistency_count += int(consistency >= 0.70)
        family = family_by_candidate[candidate]
        family_retention[family].append(retention)
        family_both_non_e[family].append(both_non_e)
        anchor_summary[candidate] = {
            "modal_probability": modal_probability,
            "retention_probability": retention,
            "consistency_probability": consistency,
            "both_native_non_E_probability": both_non_e,
        }
    bootstrap_passed = (
        modal_count >= 9
        and all(max(values) >= 0.70 for values in family_retention.values())
        and consistency_count >= 9
        and all(max(values) >= 0.70 for values in family_both_non_e.values())
    )
    receptor_consistency = (
        consistency_count >= 9
        and all(max(values) >= 0.70 for values in family_both_non_e.values())
    )
    return bootstrap_passed, receptor_consistency, {
        "modal_probability_ge_0_70_count": modal_count,
        "receptor_consistency_ge_0_70_count": consistency_count,
        "anchors": anchor_summary,
    }


def thresholds_valid(rules_document: Mapping[str, Any]) -> bool:
    rules = rules_document.get("rules")
    if not isinstance(rules, dict) or rules.get("primary_channel_count") != 5:
        return False
    thresholds = rules.get("thresholds", {})
    channels = [thresholds.get("pooled_H")]
    receptor = thresholds.get("receptor", {})
    channels.extend(receptor.get(name, {}).get(metric) for name in ("8X6B", "9E6Y") for metric in ("O", "P"))
    try:
        return len(channels) == 5 and all(
            isinstance(item, dict)
            and item.get("defined") is True
            and math.isfinite(float(item["L_raw"]))
            and math.isfinite(float(item["U_raw"]))
            and float(item["L_raw"]) > 0.0
            and float(item["U_raw"]) > float(item["L_raw"])
            for item in channels
        )
    except (KeyError, TypeError, ValueError):
        return False


def recompute_gates(source: SourceRelease) -> tuple[dict[str, bool], dict[str, Any]]:
    rows = source.rows
    pose = rows["pvrig_v1_3_native_pose_scores.csv"]
    run = rows["pvrig_v1_3_native_run_scores.csv"]
    dual = rows["pvrig_v1_3_dual_candidate_scores.csv"]
    lofo = rows["pvrig_v1_3_family_lofo.csv"]
    boot_t = rows["pvrig_v1_3_bootstrap_thresholds.csv"]
    boot_r = rows["pvrig_v1_3_bootstrap_receptor_anchor_evaluations.csv"]
    boot_d = rows["pvrig_v1_3_bootstrap_dual_anchor_evaluations.csv"]
    mutants = rows["pvrig_v1_3_mutant_paired_deltas.csv"]
    robustness = rows["pvrig_v1_3_robustness_grid.csv"]
    for name, table in rows.items():
        validate_common_row_boundaries(table, name)
    pose_keys = {(row["candidate_id"], row["generation_receptor"], int(row["native_rank"])) for row in pose}
    run_keys = {(row["candidate_id"], row["generation_receptor"]) for row in run}
    dual_ids = {row["candidate_id"] for row in dual}
    pose_closure = (
        len(pose_keys) == 752
        and {key[1] for key in pose_keys} == {"8X6B", "9E6Y"}
        and {key[2] for key in pose_keys} == set(range(1, 9))
    )
    run_closure = len(run_keys) == 94 and {key[1] for key in run_keys} == {"8X6B", "9E6Y"}
    cohort_closure = len(dual_ids) == 47 and len({row["candidate_id"] for row in pose}) == 47
    diagnostic_isolation = all(
        row.get("cross_receptor_rank_pairing") == "false" for row in (*run, *dual)
    ) and all(row.get("candidate_level_join_only") == "true" for row in dual)
    claim_boundary = all(row.get("claim_boundary") == CLAIM_BOUNDARY for row in (*pose, *run, *dual))
    lofo_passed, lofo_summary = recompute_lofo(lofo)
    bootstrap_passed, receptor_consistency, bootstrap_summary = validate_bootstrap_tables(boot_t, boot_r, boot_d)
    grid_passed = (
        len({row["grid_id"] for row in robustness}) == 54
        and sum(bool_text(row, "primary_preregistered_row") for row in robustness) == 1
        and all(bool_text(row, "grid_defined") for row in robustness)
        and not any(bool_text(row, "best_row_selected") for row in robustness)
    )
    mutant_passed = (
        len({row["candidate_id"] for row in mutants}) == 29
        and all(bool_text(row, "mutation_semantics_validated") for row in mutants)
        and all(not bool_text(row, "binary_negative_label_assigned") for row in mutants)
        and all(bool_text(row, "direction_preserved") for row in mutants)
        and all(SHA256_RE.fullmatch(row.get(field, "")) for row in mutants for field in ("candidate_sequence_sha256", "base_sequence_sha256"))
    )
    audit = source.audit
    observed = audit.get("observed_contract", {})
    bindings = audit.get("input_bindings", {})
    rule_payload = source.rules.get("rules", {})
    gates = {
        "frozen_upstream": (
            bindings.get("preregistration", {}).get("validated") is True
            and bindings.get("execution_release", {}).get("validated") is True
            and bindings.get("selector_publication", {}).get("immutable_publication_validated") is True
            and bindings.get("processor_audit", {}).get("validated") is True
            and bindings.get("processor_qualification", {}).get("calibration_input_eligible") is True
            and bindings.get("fixed_case_semantics", {}).get("mutation_semantics_validated") is True
        ),
        "cohort_closure": cohort_closure and observed.get("case_count") == 47 and observed.get("positive_anchor_count") == 11 and observed.get("positive_family_count") == 5 and observed.get("control_case_count") == 36,
        "run_closure": run_closure,
        "pose_closure": pose_closure,
        "metric_closure": observed.get("metric_rows") == 752 and observed.get("rows_by_generation_receptor") == {"8X6B": 376, "9E6Y": 376},
        "protocol_hash_closure": bindings.get("frozen_manifests", {}).get("run_count") == 94 and bindings.get("frozen_manifests", {}).get("protocol_count") == 2 and bindings.get("execution_release", {}).get("artifact_count", 0) >= 30,
        "ATOM_only": observed.get("atom_only_reference_inventory_gate_passed") is True,
        "five_channel_threshold_validity": thresholds_valid(source.rules),
        "family_and_receptor_balance": rule_payload.get("positive_family_count") == 5 and rule_payload.get("pooled_H_receptor_weighting") == "one_half_per_receptor",
        "central_and_54_grid": grid_passed,
        "LOFO": lofo_passed,
        "bootstrap": bootstrap_passed,
        "receptor_consistency": receptor_consistency,
        "mutant_sensitivity": mutant_passed,
        "diagnostic_isolation": diagnostic_isolation and observed.get("native_rank_pairing_across_receptors") is False and observed.get("native_only_validated") is True and observed.get("generation_native_receptor_identity_validated") is True,
        "claim_boundary": claim_boundary,
        "formal_veto": True,
    }
    return gates, {"lofo": lofo_summary, "bootstrap": bootstrap_summary}


def validate_claimed_gate_outcome(source: SourceRelease, gates: Mapping[str, bool]) -> None:
    acceptance = source.audit.get("acceptance_summary")
    if not isinstance(acceptance, dict):
        raise ReleaseError("Calibration audit lacks acceptance summary")
    if tuple(acceptance.get("required_gate_order", [])) != REQUIRED_GATES:
        raise ReleaseError("Calibration required-gate order drift")
    claimed = acceptance.get("gates")
    if not isinstance(claimed, dict) or set(claimed) != set(REQUIRED_GATES):
        raise ReleaseError("Calibration gate ledger is incomplete")
    for name in REQUIRED_GATES:
        if not isinstance(claimed.get(name), dict) or claimed[name].get("passed") is not gates[name]:
            raise ReleaseError(f"Calibration claimed/recomputed gate mismatch: {name}")
    passed = all(gates.values())
    expected_outcome = SOURCE_GATE_PASS if passed else SOURCE_GATE_FAIL
    for label, payload in (
        ("audit", source.audit),
        ("release input", source.release_input),
        ("acceptance", acceptance),
        ("rules", source.rules),
    ):
        if payload.get("computed_gate_outcome") != expected_outcome:
            raise ReleaseError(f"{label} computed-gate outcome mismatch")
    for label, payload in (("audit", source.audit), ("acceptance", acceptance), ("rules", source.rules)):
        if payload.get("development_method_passed") is not passed:
            raise ReleaseError(f"{label} development-method boolean mismatch")


def promote_current_symlink(release_dir: Path, current: Path) -> None:
    current.parent.mkdir(parents=True, exist_ok=True)
    if current.exists() and not current.is_symlink():
        raise ReleaseError(f"Development current pointer is not a symlink: {current}")
    descriptor, raw = tempfile.mkstemp(prefix=".current.", dir=current.parent)
    os.close(descriptor)
    temporary = Path(raw)
    temporary.unlink()
    try:
        os.symlink(os.path.relpath(release_dir, current.parent), temporary, target_is_directory=True)
        os.replace(temporary, current)
    finally:
        temporary.unlink(missing_ok=True)


def publish(staging: Path, release_dir: Path, current: Path, promoter: PointerPromoter) -> None:
    expected = inventory(staging)
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    previous = current.resolve() if current.is_symlink() else None
    created = False
    if release_dir.exists():
        if inventory(release_dir) != expected:
            raise ReleaseError(f"Immutable development-release collision: {release_dir.name}")
        shutil.rmtree(staging)
    else:
        os.replace(staging, release_dir)
        created = True
    try:
        promoter(release_dir, current)
        if not current.is_symlink() or current.resolve() != release_dir.resolve():
            raise ReleaseError("Development current-pointer verification failed")
    except Exception:
        if previous is not None:
            promote_current_symlink(previous, current)
        else:
            current.unlink(missing_ok=True)
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise


def decision_from_gates(gates: Mapping[str, bool]) -> tuple[str, bool]:
    if tuple(gates) != REQUIRED_GATES:
        raise ReleaseError("Decision gate order does not match preregistration")
    passed = all(gates.values())
    return (PASS_STATUS, True) if passed else (FAIL_STATUS, False)


def validate_and_publish(
    config: ReleaseConfig, *, pointer_promoter: PointerPromoter = promote_current_symlink
) -> dict[str, Any]:
    primary = validate_source_publication(config.primary_release_input)
    rebuild = validate_source_publication(config.rebuild_release_input)
    validate_deterministic_pair(primary, rebuild)
    upstream_hashes, upstream_documents = validate_upstream(config, primary)
    rebuild_hashes, _ = validate_upstream(config, rebuild)
    if upstream_hashes != rebuild_hashes:
        raise ReleaseError("Independent calibrator publications bind different upstream inputs")
    gates, diagnostics = recompute_gates(primary)
    rebuild_gates, rebuild_diagnostics = recompute_gates(rebuild)
    if gates != rebuild_gates or diagnostics != rebuild_diagnostics:
        raise ReleaseError("Independent gate revalidation differs")
    validate_claimed_gate_outcome(primary, gates)
    validate_claimed_gate_outcome(rebuild, rebuild_gates)
    status, smoke = decision_from_gates(gates)

    source_inventory_sha = sha256_json(primary.inventory)
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "protocol_id": PROTOCOL_ID,
        "method_id": METHOD_ID,
        "development_method_passed": smoke,
        "development_smoke_eligible": smoke,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
        "training_state": "P2_TRAINING_BLOCKED",
        "anchor_readiness": {
            "status": upstream_documents["anchor_readiness"]["status"],
            "existing_anchor_count": 11,
            "existing_family_count": 5,
            "new_eligible_independent_family_count": 0,
            "unconditional_formal_veto": True,
        },
        "determinism": {
            "independent_calibrator_publication_count": 2,
            "byte_identical_all_13_files": True,
            "content_addressed_release_id_equal": True,
            "calibrator_release_id": primary.release_id,
            "immutable_inventory_sha256": source_inventory_sha,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "bootstrap_threshold_rows": 20000,
            "bootstrap_receptor_anchor_rows": 44000,
            "bootstrap_dual_anchor_rows": 22000,
        },
        "gate_revalidation": {
            "required_gate_order": list(REQUIRED_GATES),
            "gates": {name: {"passed": gates[name]} for name in REQUIRED_GATES},
            "all_gates_passed": all(gates.values()),
            "computed_gate_outcome": SOURCE_GATE_PASS if all(gates.values()) else SOURCE_GATE_FAIL,
            "diagnostics": diagnostics,
        },
        "source_publications": {
            "primary": {
                "release_input_path": primary.release_input_path.as_posix(),
                "release_input_sha256": sha256_file(primary.release_input_path),
                "release_id": primary.release_id,
            },
            "rebuild": {
                "release_input_path": rebuild.release_input_path.as_posix(),
                "release_input_sha256": sha256_file(rebuild.release_input_path),
                "release_id": rebuild.release_id,
            },
        },
        "bound_evidence_sha256": {
            **upstream_hashes,
            "source_inventory_sha256": source_inventory_sha,
            "validator": sha256_file(Path(__file__).resolve()),
            "validator_test": sha256_file(DEFAULT_VALIDATOR_TEST.resolve()),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }
    release_id = f"development-{sha256_json(base)[:24]}"
    payload = {
        **base,
        "publication": {
            "release_id": release_id,
            "release_relpath": f"releases/{release_id}",
            "current_pointer_relpath": "current",
            "immutable_versioned_release": True,
            "promotion": "single atomic current symlink replacement",
            "rollback_safe": True,
        },
    }
    config.outdir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".development.staging.", dir=config.outdir))
    try:
        output = staging / RELEASE_NAME
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        publish(
            staging,
            config.outdir / "releases" / release_id,
            config.outdir / "current",
            pointer_promoter,
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-release-input", type=Path, default=DEFAULT_PRIMARY_RELEASE_INPUT)
    parser.add_argument("--rebuild-release-input", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, default=DEFAULT_PREREGISTRATION)
    parser.add_argument("--anchor-readiness", type=Path, default=DEFAULT_ANCHOR_READINESS)
    parser.add_argument("--execution-release", type=Path, default=DEFAULT_EXECUTION_RELEASE)
    parser.add_argument("--case-manifest", type=Path, default=DEFAULT_CASE_MANIFEST)
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST)
    parser.add_argument("--protocol-manifest", type=Path, default=DEFAULT_PROTOCOL_MANIFEST)
    parser.add_argument("--selector-csv", type=Path, default=DEFAULT_SELECTOR_CSV)
    parser.add_argument("--selector-audit", type=Path, default=DEFAULT_SELECTOR_AUDIT)
    parser.add_argument("--metrics-csv", type=Path, default=DEFAULT_METRICS_CSV)
    parser.add_argument("--processor-audit", type=Path, default=DEFAULT_PROCESSOR_AUDIT)
    parser.add_argument("--processor-qualification", type=Path, default=DEFAULT_PROCESSOR_QUALIFICATION)
    parser.add_argument("--positive-manifest", type=Path, default=DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--calibrator", type=Path, default=DEFAULT_CALIBRATOR)
    parser.add_argument("--calibrator-test", type=Path, default=DEFAULT_CALIBRATOR_TEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = ReleaseConfig(
        primary_release_input=args.primary_release_input,
        rebuild_release_input=args.rebuild_release_input,
        preregistration=args.preregistration,
        anchor_readiness=args.anchor_readiness,
        execution_release=args.execution_release,
        case_manifest=args.case_manifest,
        run_manifest=args.run_manifest,
        protocol_manifest=args.protocol_manifest,
        selector_csv=args.selector_csv,
        selector_audit=args.selector_audit,
        metrics_csv=args.metrics_csv,
        processor_audit=args.processor_audit,
        processor_qualification=args.processor_qualification,
        positive_manifest=args.positive_manifest,
        mutant_manifest=args.mutant_manifest,
        calibrator=args.calibrator,
        calibrator_test=args.calibrator_test,
        outdir=args.outdir,
    )
    try:
        payload = validate_and_publish(config)
    except (ReleaseError, OSError, ValueError) as error:
        print(canonical_json({
            "schema_version": SCHEMA_VERSION,
            "status": FAIL_STATUS,
            "development_smoke_eligible": False,
            "formal_eligible": False,
            "docking_gold_release_eligible": False,
            "training_label_release_eligible": False,
            "p2_training_ready": False,
            "error": str(error),
        }))
        return 2
    print(canonical_json({
        "status": payload["status"],
        "development_smoke_eligible": payload["development_smoke_eligible"],
        "release_id": payload["publication"]["release_id"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
