#!/usr/bin/env python3
"""Independently qualify two deterministic V1.3 native-processing releases."""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


try:
    from experiments.phase2_5080_v1.src import (
        process_phase2_v3_p2_v1_3_native_top8 as processor,
    )
except ModuleNotFoundError:  # pragma: no cover - direct execution
    import process_phase2_v3_p2_v1_3_native_top8 as processor


SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
DATA_ROOT = EXP_DIR.parents[1]
WORKSPACE_ROOT = DATA_ROOT.parent

SCHEMA_VERSION = "pvrig_v1_3_native_processor_qualification_v1"
STATUS = "QUALIFIED_NATIVE_PROCESSOR_INPUT"
QUALIFICATION_NAME = "pvrig_v1_3_native_processor_qualification.json"
DEFAULT_PRIMARY_AUDIT = processor.DEFAULT_OUTDIR / "current" / processor.AUDIT_NAME
DEFAULT_QUALIFICATION_ROOT = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_native_processor_qualification"
)
DEFAULT_EXECUTION_RELEASE = (
    EXP_DIR / "audits/phase2_v3_p2_v1_3_docking_execution_release_manifest.json"
)
DEFAULT_PACKAGE = (
    EXP_DIR / "runs/pvrig_v3_p2/docking_gold_v1_3_dual47_completion15_package"
)
DEFAULT_CASE_MANIFEST = DEFAULT_PACKAGE / "manifests/case_manifest.csv"
DEFAULT_RUN_MANIFEST = DEFAULT_PACKAGE / "manifests/run_manifest.csv"
DEFAULT_PROTOCOL_MANIFEST = DEFAULT_PACKAGE / "manifests/protocol_manifest.csv"
DEFAULT_VALIDATOR_TEST = (
    SCRIPT_DIR / "test_validate_phase2_v3_p2_v1_3_native_processor_release.py"
)


class QualificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class QualificationContract:
    case_count: int = 47
    run_count: int = 94
    metric_rows: int = 752


@dataclass(frozen=True)
class QualificationConfig:
    primary_audit: Path
    rebuild_audit: Path
    selector_csv: Path = processor.DEFAULT_SELECTOR_CSV
    selector_audit: Path = processor.DEFAULT_SELECTOR_AUDIT
    preregistration: Path = processor.DEFAULT_PREREGISTRATION
    execution_release: Path = DEFAULT_EXECUTION_RELEASE
    positive_manifest: Path = processor.DEFAULT_POSITIVE_MANIFEST
    mutant_manifest: Path = processor.DEFAULT_MUTANT_MANIFEST
    case_manifest: Path = DEFAULT_CASE_MANIFEST
    run_manifest: Path = DEFAULT_RUN_MANIFEST
    protocol_manifest: Path = DEFAULT_PROTOCOL_MANIFEST
    references: Mapping[str, Path] = None  # type: ignore[assignment]
    processor_path: Path = Path(processor.__file__).resolve()
    processor_test: Path = processor.DEFAULT_PROCESSOR_TEST
    outdir: Path = DEFAULT_QUALIFICATION_ROOT
    contract: QualificationContract = QualificationContract()

    def __post_init__(self) -> None:
        if self.references is None:
            object.__setattr__(
                self,
                "references",
                {
                    receptor: Path(spec["reference"])
                    for receptor, spec in processor.RECEPTORS.items()
                },
            )


def sha256_file(path: Path) -> str:
    try:
        return processor.sha256_file(path.resolve())
    except processor.ContractError as error:
        raise QualificationError(str(error)) from error


def sha256_json(value: Any) -> str:
    return processor.sha256_json(value)


def canonical_json(value: Any) -> str:
    return processor.canonical_json(value)


def read_json(path: Path, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise QualificationError(f"Invalid {context}: {path}") from error
    if not isinstance(payload, dict):
        raise QualificationError(f"{context} is not an object: {path}")
    return payload


def directory_inventory(root: Path) -> dict[str, str]:
    try:
        return processor.package_file_hashes(root.resolve())
    except processor.ContractError as error:
        raise QualificationError(str(error)) from error


def metrics_hash_chain(path: Path) -> tuple[int, str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "metrics_row_sha256" not in reader.fieldnames:
            raise QualificationError(f"Metrics CSV lacks row hashes: {path}")
        rows = list(reader)
    for row_number, row in enumerate(rows, start=2):
        if row.get("metrics_row_sha256") != processor.row_sha256(
            row, "metrics_row_sha256"
        ):
            raise QualificationError(f"Metrics row hash mismatch at {path}:{row_number}")
        if row.get("primary_native_metric_eligible") != "false":
            raise QualificationError("Pending processor metrics must remain primary=false")
    return len(rows), processor.hash_chain(rows, "metrics_row_sha256")


def validate_pending_release(
    audit_path: Path, contract: QualificationContract
) -> dict[str, Any]:
    audit_path = audit_path.resolve()
    audit = read_json(audit_path, "processor audit")
    expected = {
        "schema_version": "pvrig_v1_3_native_top8_processing_audit_v1",
        "status": processor.PROCESSOR_PENDING_STATUS,
        "protocol_id": processor.PROTOCOL_ID,
        "formal_eligible": False,
        "training_label_release_eligible": False,
        "docking_gold_release_eligible": False,
        "primary_native_metric_eligible": False,
        "p2_training_ready": False,
        "native_only": True,
    }
    mismatches = {
        key: (audit.get(key), value)
        for key, value in expected.items()
        if audit.get(key) != value
    }
    observed = audit.get("observed_contract")
    if not isinstance(observed, dict):
        mismatches["observed_contract"] = (observed, "object")
    else:
        for key, value in {
            "case_count": contract.case_count,
            "run_count": contract.run_count,
            "metric_rows": contract.metric_rows,
            "materialization_rows": contract.metric_rows,
            "contact_records": contract.metric_rows,
            "aligned_pose_files": contract.metric_rows,
        }.items():
            if observed.get(key) != value:
                mismatches[f"observed_contract.{key}"] = (observed.get(key), value)
    release = audit.get("publication_contract")
    if not isinstance(release, dict):
        mismatches["publication_contract"] = (release, "object")
        release = {}
    release_id = str(release.get("release_id", ""))
    try:
        observed_release_id = processor.immutable_release_id(audit_path)
    except processor.ContractError as error:
        raise QualificationError(str(error)) from error
    if release_id != observed_release_id:
        mismatches["publication_contract.release_id"] = (
            release_id,
            observed_release_id,
        )
    if release.get("immutable_versioned_release") is not True:
        mismatches["publication_contract.immutable_versioned_release"] = (
            release.get("immutable_versioned_release"),
            True,
        )
    if mismatches:
        raise QualificationError(f"Pending processor audit mismatch: {mismatches}")

    output = audit.get("output_sha256")
    if not isinstance(output, dict):
        raise QualificationError("Processor audit lacks output_sha256")
    metrics_binding = output.get("continuous_metrics")
    if not isinstance(metrics_binding, dict):
        raise QualificationError("Processor audit lacks continuous metrics binding")
    metrics_path = audit_path.parent / str(metrics_binding.get("relpath", ""))
    rows, row_chain = metrics_hash_chain(metrics_path)
    if (
        rows != contract.metric_rows
        or metrics_binding.get("rows") != rows
        or metrics_binding.get("sha256") != sha256_file(metrics_path)
        or metrics_binding.get("row_hash_chain") != row_chain
    ):
        raise QualificationError("Continuous metrics hash/row-chain closure failed")
    inventory = directory_inventory(audit_path.parent)
    return {
        "audit": audit,
        "audit_path": audit_path,
        "audit_sha256": sha256_file(audit_path),
        "metrics_path": metrics_path,
        "metrics_sha256": sha256_file(metrics_path),
        "metrics_rows": rows,
        "metrics_row_hash_chain": row_chain,
        "release_id": release_id,
        "inventory": inventory,
        "inventory_sha256": sha256_json(inventory),
        "core_output_sha256": output,
    }


def require_hash_binding(
    audit: Mapping[str, Any], field: str, path: Path, expected_hash: str
) -> None:
    inputs = audit.get("input_sha256")
    if not isinstance(inputs, dict) or inputs.get(field) != expected_hash:
        raise QualificationError(f"Processor audit does not bind {field}")
    if sha256_file(path) != expected_hash:
        raise QualificationError(f"Qualified upstream hash drift: {path}")


def promote_current_symlink(release_dir: Path, current_link: Path) -> None:
    current_link.parent.mkdir(parents=True, exist_ok=True)
    if current_link.exists() and not current_link.is_symlink():
        raise QualificationError(f"Qualification current pointer is not a symlink: {current_link}")
    descriptor, raw = tempfile.mkstemp(prefix=".current.", dir=current_link.parent)
    os.close(descriptor)
    temporary = Path(raw)
    temporary.unlink()
    try:
        os.symlink(
            os.path.relpath(release_dir, current_link.parent),
            temporary,
            target_is_directory=True,
        )
        os.replace(temporary, current_link)
    finally:
        temporary.unlink(missing_ok=True)


def publish_qualification(staging: Path, release_dir: Path, current_link: Path) -> None:
    expected = directory_inventory(staging)
    release_dir.parent.mkdir(parents=True, exist_ok=True)
    previous = current_link.resolve() if current_link.is_symlink() else None
    created = False
    if release_dir.exists():
        if directory_inventory(release_dir) != expected:
            raise QualificationError(f"Immutable qualification collision: {release_dir.name}")
        shutil.rmtree(staging)
    else:
        os.replace(staging, release_dir)
        created = True
    try:
        promote_current_symlink(release_dir, current_link)
        if not current_link.is_symlink() or current_link.resolve() != release_dir.resolve():
            raise QualificationError("Qualification current-pointer verification failed")
    except Exception:
        if previous is not None:
            promote_current_symlink(previous, current_link)
        elif current_link.is_symlink():
            current_link.unlink()
        if created and release_dir.exists():
            shutil.rmtree(release_dir)
        raise


def qualify(config: QualificationConfig) -> dict[str, Any]:
    primary = validate_pending_release(config.primary_audit, config.contract)
    rebuild = validate_pending_release(config.rebuild_audit, config.contract)
    if primary["audit_path"] == rebuild["audit_path"]:
        raise QualificationError("Deterministic rebuild must use a distinct publication path")
    if primary["inventory"] != rebuild["inventory"]:
        raise QualificationError("Independent pending-release inventories differ")
    if primary["core_output_sha256"] != rebuild["core_output_sha256"]:
        raise QualificationError("Independent core output hashes differ")
    if primary["release_id"] != rebuild["release_id"]:
        raise QualificationError("Independent content-addressed release IDs differ")

    paths = {
        "selector_csv": config.selector_csv.resolve(),
        "selector_audit": config.selector_audit.resolve(),
        "preregistration": config.preregistration.resolve(),
        "execution_release": config.execution_release.resolve(),
        "positive_manifest": config.positive_manifest.resolve(),
        "mutant_manifest": config.mutant_manifest.resolve(),
        "case_manifest": config.case_manifest.resolve(),
        "run_manifest": config.run_manifest.resolve(),
        "protocol_manifest": config.protocol_manifest.resolve(),
        "processor": config.processor_path.resolve(),
        "processor_test": config.processor_test.resolve(),
        **{
            f"reference_{receptor.lower()}": path.resolve()
            for receptor, path in config.references.items()
        },
    }
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    execution_payload = read_json(paths["execution_release"], "execution release")
    if (
        execution_payload.get("schema_version")
        != "phase2_v3_p2_v1_3_docking_execution_release_v1"
        or execution_payload.get("status")
        != "FROZEN_V1_3_DOCKING_EXECUTION_RELEASE"
    ):
        raise QualificationError("Frozen execution-release status/schema mismatch")
    artifacts = execution_payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise QualificationError("Execution release lacks artifact ledger")
    execution_ledger = {
        str(item.get("path", "")): str(item.get("sha256", ""))
        for item in artifacts
        if isinstance(item, dict)
    }
    for name in ("preregistration", "case_manifest", "run_manifest", "protocol_manifest"):
        relpath = processor.canonical_input_path(paths[name], DATA_ROOT)
        if execution_ledger.get(relpath) != hashes[name]:
            raise QualificationError(f"Execution release does not bind {name}")
    audit = primary["audit"]
    for field in (
        "selector_csv",
        "selector_audit",
        "preregistration",
        "positive_manifest",
        "mutant_manifest",
        "processor",
        "processor_test",
        "reference_8x6b",
        "reference_9e6y",
    ):
        require_hash_binding(audit, field, paths[field], hashes[field])
    inputs = audit.get("input_sha256", {})
    if inputs.get("execution_release_manifest") != hashes["execution_release"]:
        raise QualificationError("Processor audit does not bind execution release")
    if inputs.get("run_manifest") != hashes["run_manifest"]:
        raise QualificationError("Processor audit does not bind run manifest")

    selector_audit = read_json(paths["selector_audit"], "selector audit")
    publication = selector_audit.get("publication")
    if not isinstance(publication, dict) or not publication.get("release_id"):
        raise QualificationError("Selector audit lacks immutable publication evidence")
    selector_release_id = str(publication["release_id"])
    if processor.immutable_release_id(paths["selector_csv"]) != selector_release_id:
        raise QualificationError("Selector CSV publication identity mismatch")
    if processor.immutable_release_id(paths["selector_audit"]) != selector_release_id:
        raise QualificationError("Selector audit publication identity mismatch")

    qualified_input = {
        "processor_audit_sha256": primary["audit_sha256"],
        "continuous_metrics_sha256": primary["metrics_sha256"],
        "continuous_metrics_row_hash_chain": primary["metrics_row_hash_chain"],
        "selector_csv_sha256": hashes["selector_csv"],
        "selector_audit_sha256": hashes["selector_audit"],
        "selector_publication_release_id": selector_release_id,
        "preregistration_sha256": hashes["preregistration"],
        "execution_release_sha256": hashes["execution_release"],
        "positive_manifest_sha256": hashes["positive_manifest"],
        "mutant_manifest_sha256": hashes["mutant_manifest"],
        "case_manifest_sha256": hashes["case_manifest"],
        "run_manifest_sha256": hashes["run_manifest"],
        "protocol_manifest_sha256": hashes["protocol_manifest"],
        "reference_sha256": {
            receptor: hashes[f"reference_{receptor.lower()}"]
            for receptor in processor.RECEPTORS
        },
        "processor_sha256": hashes["processor"],
        "processor_test_sha256": hashes["processor_test"],
        "validator_sha256": sha256_file(Path(__file__).resolve()),
        "validator_test_sha256": sha256_file(DEFAULT_VALIDATOR_TEST.resolve()),
    }
    determinism = {
        "independent_publication_count": 2,
        "full_inventory_equal": True,
        "core_output_hashes_equal": True,
        "content_addressed_release_id_equal": True,
        "release_id": primary["release_id"],
        "primary_inventory_sha256": primary["inventory_sha256"],
        "rebuild_inventory_sha256": rebuild["inventory_sha256"],
        "primary_processor_audit_sha256": primary["audit_sha256"],
        "rebuild_processor_audit_sha256": rebuild["audit_sha256"],
    }
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "protocol_id": processor.PROTOCOL_ID,
        "calibration_input_eligible": True,
        "formal_eligible": False,
        "docking_gold_release_eligible": False,
        "training_label_release_eligible": False,
        "p2_training_ready": False,
        "native_only": True,
        "qualified_input": qualified_input,
        "determinism": determinism,
        "source_pending_releases": {
            "primary": {
                "audit_path": processor.canonical_input_path(
                    primary["audit_path"], WORKSPACE_ROOT
                ),
                "audit_sha256": primary["audit_sha256"],
                "release_id": primary["release_id"],
            },
            "rebuild": {
                "audit_path": processor.canonical_input_path(
                    rebuild["audit_path"], WORKSPACE_ROOT
                ),
                "audit_sha256": rebuild["audit_sha256"],
                "release_id": rebuild["release_id"],
            },
        },
    }
    release_id = f"qualification-{sha256_json(base)[:24]}"
    payload = {
        **base,
        "publication": {
            "release_id": release_id,
            "release_relpath": f"releases/{release_id}",
            "current_pointer_relpath": "current",
            "immutable_versioned_release": True,
            "atomic_current_symlink_replacement": True,
        },
    }
    config.outdir.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".qualification.staging.", dir=config.outdir)
    )
    try:
        processor.write_json(staging / QUALIFICATION_NAME, payload)
        publish_qualification(
            staging,
            config.outdir / "releases" / release_id,
            config.outdir / "current",
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-audit", type=Path, default=DEFAULT_PRIMARY_AUDIT)
    parser.add_argument("--rebuild-audit", type=Path, required=True)
    parser.add_argument("--selector-csv", type=Path, default=processor.DEFAULT_SELECTOR_CSV)
    parser.add_argument("--selector-audit", type=Path, default=processor.DEFAULT_SELECTOR_AUDIT)
    parser.add_argument("--preregistration", type=Path, default=processor.DEFAULT_PREREGISTRATION)
    parser.add_argument("--execution-release", type=Path, default=DEFAULT_EXECUTION_RELEASE)
    parser.add_argument("--positive-manifest", type=Path, default=processor.DEFAULT_POSITIVE_MANIFEST)
    parser.add_argument("--mutant-manifest", type=Path, default=processor.DEFAULT_MUTANT_MANIFEST)
    parser.add_argument("--case-manifest", type=Path, default=DEFAULT_CASE_MANIFEST)
    parser.add_argument("--run-manifest", type=Path, default=DEFAULT_RUN_MANIFEST)
    parser.add_argument("--protocol-manifest", type=Path, default=DEFAULT_PROTOCOL_MANIFEST)
    parser.add_argument("--reference-8x6b", type=Path, default=processor.RECEPTORS["8X6B"]["reference"])
    parser.add_argument("--reference-9e6y", type=Path, default=processor.RECEPTORS["9E6Y"]["reference"])
    parser.add_argument("--processor", type=Path, default=Path(processor.__file__).resolve())
    parser.add_argument("--processor-test", type=Path, default=processor.DEFAULT_PROCESSOR_TEST)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_QUALIFICATION_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = qualify(
            QualificationConfig(
                primary_audit=args.primary_audit.resolve(),
                rebuild_audit=args.rebuild_audit.resolve(),
                selector_csv=args.selector_csv.resolve(),
                selector_audit=args.selector_audit.resolve(),
                preregistration=args.preregistration.resolve(),
                execution_release=args.execution_release.resolve(),
                positive_manifest=args.positive_manifest.resolve(),
                mutant_manifest=args.mutant_manifest.resolve(),
                case_manifest=args.case_manifest.resolve(),
                run_manifest=args.run_manifest.resolve(),
                protocol_manifest=args.protocol_manifest.resolve(),
                references={
                    "8X6B": args.reference_8x6b.resolve(),
                    "9E6Y": args.reference_9e6y.resolve(),
                },
                processor_path=args.processor.resolve(),
                processor_test=args.processor_test.resolve(),
                outdir=args.outdir.resolve(),
            )
        )
    except QualificationError as error:
        print(f"ERROR: {error}", file=os.sys.stderr)
        return 2
    print(canonical_json({"status": payload["status"], "release_id": payload["publication"]["release_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
