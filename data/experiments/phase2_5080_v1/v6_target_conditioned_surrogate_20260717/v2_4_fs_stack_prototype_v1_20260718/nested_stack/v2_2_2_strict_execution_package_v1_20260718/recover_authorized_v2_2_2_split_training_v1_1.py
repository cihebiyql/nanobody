#!/usr/bin/env python3
"""Build V1.1 recovery with per-split canonical-training row views.

The first authorized launch failed before training because the unchanged
trainer correctly requires the input row parents to equal train U score. Inner
folds exclude outer-score parents, while the command supplied the full 31-parent
table. This recovery changes no trainer, split member, label, model, loss,
weight, or hyperparameter. It only supplies each job with the exact row subset
named by its already-frozen split manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path


HERE = Path(__file__).resolve()


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_spec:{path}")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


base = module("v222_base", HERE.with_name("build_v2_2_2_strict_nested_package_v1.py"))
auth = module("v222_auth", HERE.with_name("authorize_v2_2_2_strict_nested_package_v1.py"))
authorized_audit = module("v222_auth_audit", HERE.with_name("audit_authorized_v2_2_2_strict_nested_package_v1.py"))

OLD_PACKAGE = auth.NODE1_PACKAGE_ROOT
OLD_RUNTIME = auth.NODE1_RUNTIME_ROOT
NEW_PACKAGE = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_1_20260718"
NEW_RUNTIME = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_1_20260718"
RUNNER_SOURCE = base.RUNNER


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def rewrite_paths(value):
    if isinstance(value, str):
        return value.replace(OLD_PACKAGE, NEW_PACKAGE).replace(OLD_RUNTIME, NEW_RUNTIME)
    if isinstance(value, list):
        return [rewrite_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: rewrite_paths(item) for key, item in value.items()}
    return value


def build(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    base.require(not output.exists(), f"output_exists:{output}")
    original_audit = authorized_audit.audit(source)
    base.require(original_audit["status"] == "PASS_AUTHORIZED_PACKAGE_READY_TO_LAUNCH", "source_authorized_audit")
    try:
        shutil.copytree(source, output)
        runner_copy = output / "node1_bundle" / "src" / RUNNER_SOURCE.name
        shutil.copy2(RUNNER_SOURCE, runner_copy)
        graph_path = output / "node1_bundle" / "plan" / "job_graph.json"
        graph = rewrite_paths(json.loads(graph_path.read_text(encoding="utf-8")))
        graph["code_contracts"]["runner"]["path"] = str(RUNNER_SOURCE)
        graph["code_contracts"]["runner"]["sha256"] = base.sha256_file(runner_copy)

        with base.TRAINING.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            columns, rows = list(reader.fieldnames or []), list(reader)
        subset_dir = output / "node1_bundle" / "inputs" / "split_training"
        subset_dir.mkdir(parents=True)
        graph["split_training_inputs"] = {}
        split_to_training: dict[str, str] = {}
        for split_key, split_info in graph["split_manifests"].items():
            local_split = output / "node1_bundle" / "plan" / "trainer_splits" / Path(split_info["node1_path"]).name
            split = json.loads(local_split.read_text(encoding="utf-8"))
            parents = set(split["train_parents"]) | set(split["score_parents"])
            selected = [row for row in rows if row["parent_framework_cluster"] in parents]
            observed = {row["parent_framework_cluster"] for row in selected}
            base.require(observed == parents and selected, f"subset_parent_closure:{split_key}")
            subset = subset_dir / f"{split_key}.tsv"
            with subset.open("x", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
                writer.writeheader(); writer.writerows(selected)
            node_path = str(Path(NEW_PACKAGE) / "inputs" / "split_training" / subset.name)
            graph["split_training_inputs"][split_key] = {
                "path": str(subset), "node1_path": node_path,
                "sha256": base.sha256_file(subset), "rows": len(selected),
                "parent_count": len(parents), "source_training_sha256": base.EXPECTED_HASHES[base.TRAINING],
                "split_manifest_sha256": split_info["sha256"],
            }
            split_to_training[split_info["node1_path"]] = node_path

        for job in graph["jobs"]:
            if not job["kind"].startswith("GPU_"):
                continue
            split_path = job["split_manifest"]
            command = job["command"]
            base.require(split_path in split_to_training, f"job_split_mapping:{job['job_id']}")
            index = command.index("--training-tsv") + 1
            command[index] = split_to_training[split_path]

        authorized_view_sha = graph["canonical_inputs"]["deployment_manifest"]["sha256"]
        summary = auth.validate_authorized_graph(graph, authorized_view_sha)
        base.require(len(graph["split_training_inputs"]) == 30, "split_training_count")
        graph["recovery_contract"] = {
            "schema_version": "pvrig_v2_4_v2_2_2_split_training_exact_parent_closure_recovery_v1_1",
            "reason": "V1 synchronized pre-training split_parent_exact_closure failure",
            "trainer_changed": False,
            "split_membership_changed": False,
            "model_or_hyperparameter_changed": False,
            "lane_weights_changed": False,
            "input_row_view": "canonical1507 filtered to frozen train_parents U score_parents per split",
            "failed_runtime": OLD_RUNTIME,
        }
        write_json(graph_path, graph)
        graph_sha = base.sha256_file(graph_path)
        receipt_path = output / "node1_bundle" / "plan" / "receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["job_graph_path"] = str(Path(NEW_PACKAGE) / "plan" / "job_graph.json")
        receipt["job_graph_sha256"] = graph_sha
        receipt["status"] = "READY_EXECUTABLE_POSTCALIBRATION_FREEZE"
        write_json(receipt_path, receipt)

        overlay_path = output / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"
        overlay = json.loads(overlay_path.read_text())
        overlay["schema_version"] = "pvrig_v2_4_v2_2_2_strict_nested_explicit_authorization_recovery_v1_1"
        overlay["recovery_scope"] = graph["recovery_contract"]
        overlay["node1_package_root"] = NEW_PACKAGE
        overlay["node1_runtime_root"] = NEW_RUNTIME
        write_json(overlay_path, overlay)

        launcher_path = output / "node1_bundle" / "src" / "launch_authorized_strict_nested_v1.py"
        source_text = auth.launcher_source(graph_sha, base.sha256_file(runner_copy), base.sha256_file(overlay_path))
        source_text = source_text.replace(OLD_PACKAGE, NEW_PACKAGE).replace(OLD_RUNTIME, NEW_RUNTIME)
        launcher_path.write_text(source_text, encoding="utf-8"); launcher_path.chmod(0o755)

        manifest_path = output / "PACKAGE_MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["schema_version"] = "pvrig_v2_4_v2_2_2_strict_nested_authorized_recovery_package_v1_1"
        manifest["status"] = "PASS_AUTHORIZED_SPLIT_TRAINING_RECOVERY_AUDITED_READY_TO_LAUNCH"
        manifest["node1_package_root"] = NEW_PACKAGE
        manifest["node1_runtime_root"] = NEW_RUNTIME
        manifest["job_graph"] = {"relative_path": "node1_bundle/plan/job_graph.json", "sha256": graph_sha, **summary}
        manifest["authorization_overlay_sha256"] = base.sha256_file(overlay_path)
        manifest["launcher"] = {"relative_path": "node1_bundle/src/launch_authorized_strict_nested_v1.py", "sha256": base.sha256_file(launcher_path)}
        manifest["recovery_contract"] = graph["recovery_contract"]
        manifest["split_training_input_count"] = 30
        manifest["source_failed_authorized_package"] = str(source)
        write_json(manifest_path, manifest)

        sums = output / "SHA256SUMS"
        files = sorted(path for path in output.rglob("*") if path.is_file() and path != sums)
        with sums.open("w", encoding="utf-8") as handle:
            for path in files:
                handle.write(f"{base.sha256_file(path)}  {path.relative_to(output)}\n")
        return manifest
    except Exception:
        shutil.rmtree(output, ignore_errors=True)
        raise


def audit(root: Path) -> dict:
    root = root.resolve()
    checked = 0
    for line in (root / "SHA256SUMS").read_text().splitlines():
        expected, rel = line.split("  ", 1); path = root / rel
        base.require(path.is_file() and not path.is_symlink() and base.sha256_file(path) == expected, f"hash:{rel}")
        checked += 1
    manifest = json.loads((root / "PACKAGE_MANIFEST.json").read_text())
    graph = json.loads((root / "node1_bundle" / "plan" / "job_graph.json").read_text())
    base.require(manifest["status"] == "PASS_AUTHORIZED_SPLIT_TRAINING_RECOVERY_AUDITED_READY_TO_LAUNCH", "manifest_status")
    summary = auth.validate_authorized_graph(graph, graph["canonical_inputs"]["deployment_manifest"]["sha256"])
    base.require(len(graph.get("split_training_inputs", {})) == 30, "split_training_count")
    for job in [j for j in graph["jobs"] if j["kind"].startswith("GPU_")]:
        training = job["command"][job["command"].index("--training-tsv") + 1]
        base.require(training in {v["node1_path"] for v in graph["split_training_inputs"].values()}, f"job_training_view:{job['job_id']}")
    return {"status": "PASS_AUTHORIZED_V1_1_RECOVERY_READY_TO_LAUNCH", "checked_file_count": checked, **summary, "split_training_input_count": 30, "sealed_evaluation_access_count": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-authorized-package", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(); result = build(args.source_authorized_package, args.output_dir)
    print(json.dumps({"status": result["status"], "job_graph_sha256": result["job_graph"]["sha256"], "node1_package_root": result["node1_package_root"], "node1_runtime_root": result["node1_runtime_root"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
