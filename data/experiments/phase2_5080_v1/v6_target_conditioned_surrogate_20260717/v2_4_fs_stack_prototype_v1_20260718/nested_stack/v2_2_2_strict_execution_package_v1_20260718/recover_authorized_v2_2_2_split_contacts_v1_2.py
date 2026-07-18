#!/usr/bin/env python3
"""Build V1.2 with split-synchronous marginal and pair contact views."""

from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import shutil
from pathlib import Path


HERE = Path(__file__).resolve()


def module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"module_spec:{path}")
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


base = module("v222_base_v12", HERE.with_name("build_v2_2_2_strict_nested_package_v1.py"))
auth = module("v222_auth_v12", HERE.with_name("authorize_v2_2_2_strict_nested_package_v1.py"))
v11 = module("v222_recovery_v11", HERE.with_name("recover_authorized_v2_2_2_split_training_v1_1.py"))

OLD_PACKAGE = v11.NEW_PACKAGE
OLD_RUNTIME = v11.NEW_RUNTIME
NEW_PACKAGE = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_authorized_v1_2_20260718"
NEW_RUNTIME = "/data1/qlyu/projects/pvrig_v6_v2_2_2_strict_nested_stack_runtime_authorized_v1_2_20260718"


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def rewrite(value):
    if isinstance(value, str): return value.replace(OLD_PACKAGE, NEW_PACKAGE).replace(OLD_RUNTIME, NEW_RUNTIME)
    if isinstance(value, list): return [rewrite(item) for item in value]
    if isinstance(value, dict): return {key: rewrite(item) for key, item in value.items()}
    return value


def filter_raw_gzip(source: Path, destinations: dict[str, Path], candidate_to_splits: dict[str, set[str]]) -> dict[str, dict]:
    handles = {}
    counts = {key: 0 for key in destinations}
    candidates = {key: set() for key in destinations}
    try:
        for key, path in destinations.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = path.open("xb")
            handles[key] = (raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0))
        with gzip.open(source, "rb") as handle:
            header = handle.readline()
            if not header:
                raise RuntimeError(f"empty_contact_source:{source}")
            for _, gz in handles.values(): gz.write(header)
            for line_number, line in enumerate(handle, start=2):
                fields = line.rstrip(b"\r\n").split(b"\t", 2)
                if len(fields) < 3:
                    raise RuntimeError(f"contact_row_columns:{source}:{line_number}")
                candidate = fields[1].decode("utf-8")
                for key in candidate_to_splits.get(candidate, ()):
                    handles[key][1].write(line); counts[key] += 1; candidates[key].add(candidate)
        return {key: {"rows": counts[key], "candidates": candidates[key]} for key in destinations}
    finally:
        for raw, gz in handles.values():
            gz.close(); raw.close()


def build(source: Path, output: Path) -> dict:
    source, output = source.resolve(), output.resolve()
    base.require(not output.exists(), f"output_exists:{output}")
    base.require(v11.audit(source)["status"] == "PASS_AUTHORIZED_V1_1_RECOVERY_READY_TO_LAUNCH", "v11_source_audit")
    try:
        shutil.copytree(source, output)
        runner = output / "node1_bundle" / "src" / base.RUNNER.name
        shutil.copy2(base.RUNNER, runner)
        graph_path = output / "node1_bundle" / "plan" / "job_graph.json"
        graph = rewrite(json.loads(graph_path.read_text()))
        graph["code_contracts"]["runner"]["path"] = str(base.RUNNER)
        graph["code_contracts"]["runner"]["sha256"] = base.sha256_file(runner)

        training_inputs = graph["split_training_inputs"]
        split_candidates: dict[str, set[str]] = {}
        for key, artifact in training_inputs.items():
            local = output / "node1_bundle" / "inputs" / "split_training" / Path(artifact["node1_path"]).name
            rows = base.read_tsv(local)
            split_candidates[key] = {row["candidate_id"] for row in rows}
            base.require(len(split_candidates[key]) == len(rows), f"split_candidate_duplicate:{key}")

        inner_keys = sorted(key for key in split_candidates if "inner" in key)
        candidate_to_splits: dict[str, set[str]] = {}
        for key in inner_keys:
            for candidate in split_candidates[key]: candidate_to_splits.setdefault(candidate, set()).add(key)
        contact_dir = output / "node1_bundle" / "inputs" / "split_contacts"
        marginal_dest = {key: contact_dir / f"{key}.marginal.tsv.gz" for key in inner_keys}
        pair_dest = {key: contact_dir / f"{key}.pair.tsv.gz" for key in inner_keys}
        marginal_stats = filter_raw_gzip(base.ADAPTIVE_MARGINAL, marginal_dest, candidate_to_splits)
        pair_stats = filter_raw_gzip(base.ADAPTIVE_PAIR, pair_dest, candidate_to_splits)
        graph["split_contact_inputs"] = {}
        ready = base.load_json(base.READY)
        global_marginal = ready["artifacts"]["adaptive_marginal_tsv_gz"]
        global_pair = ready["artifacts"]["adaptive_pair_tsv_gz"]
        for key in sorted(split_candidates):
            expected = split_candidates[key]
            if key in inner_keys:
                base.require(marginal_stats[key]["candidates"] == expected, f"marginal_candidate_closure:{key}")
                base.require(pair_stats[key]["candidates"] == expected, f"pair_candidate_closure:{key}")
                marginal = {
                    "path": str(marginal_dest[key]), "node1_path": str(Path(NEW_PACKAGE) / "inputs" / "split_contacts" / marginal_dest[key].name),
                    "sha256": base.sha256_file(marginal_dest[key]), "rows": marginal_stats[key]["rows"], "candidates": len(expected),
                    "source_sha256": base.EXPECTED_HASHES[base.ADAPTIVE_MARGINAL], "filter_semantics": "exact raw-row subset by frozen split candidate_id",
                }
                pair = {
                    "path": str(pair_dest[key]), "node1_path": str(Path(NEW_PACKAGE) / "inputs" / "split_contacts" / pair_dest[key].name),
                    "sha256": base.sha256_file(pair_dest[key]), "rows": pair_stats[key]["rows"], "candidates": len(expected),
                    "source_sha256": base.EXPECTED_HASHES[base.ADAPTIVE_PAIR], "filter_semantics": "exact raw-row subset by frozen split candidate_id",
                }
            else:
                marginal = {"path": str(base.ADAPTIVE_MARGINAL), "node1_path": global_marginal["node1_path"], "sha256": global_marginal["sha256"], "candidates": 1507, "filter_semantics": "canonical full table for outer split"}
                pair = {"path": str(base.ADAPTIVE_PAIR), "node1_path": global_pair["node1_path"], "sha256": global_pair["sha256"], "candidates": 1507, "filter_semantics": "canonical full table for outer split"}
            graph["split_contact_inputs"][key] = {"marginal": marginal, "pair": pair, "split_training_sha256": training_inputs[key]["sha256"]}

        split_by_manifest = {info["node1_path"]: key for key, info in graph["split_manifests"].items()}
        for job in [item for item in graph["jobs"] if item["kind"].startswith("GPU_")]:
            key = split_by_manifest[job["split_manifest"]]; bundle = graph["split_contact_inputs"][key]
            command = job["command"]
            command[command.index("--contact-tsv-gz") + 1] = bundle["marginal"]["node1_path"]
            command[command.index("--pair-contact-tsv-gz") + 1] = bundle["pair"]["node1_path"]

        # The generic authorized validator expects the canonical adaptive paths.
        # V1.2 instead applies the stronger per-split command/input closure below.
        jobs = [item for item in graph["jobs"] if item["kind"].startswith("GPU_")]
        base.require(len(graph["jobs"]) == 195 and len(jobs) == 90, "job_count")
        base.require({item["physical_gpu"] for item in jobs} == {2, 4, 5}, "gpu_allowlist")
        for job in jobs:
            key = split_by_manifest[job["split_manifest"]]; bundle = graph["split_contact_inputs"][key]; command = job["command"]
            base.require(command[command.index("--contact-tsv-gz") + 1] == bundle["marginal"]["node1_path"], f"marginal_command:{job['job_id']}")
            base.require(command[command.index("--pair-contact-tsv-gz") + 1] == bundle["pair"]["node1_path"], f"pair_command:{job['job_id']}")
            base.require(base.argv_weights(command) == base.EXPECTED_LANE_WEIGHTS[job["lane"]], f"lane_weight:{job['job_id']}")

        graph["recovery_contract"] = {
            "schema_version": "pvrig_v2_4_v2_2_2_split_synchronous_training_marginal_pair_recovery_v1_2",
            "reason": "V1.1 synchronized pre-optimizer contact_candidate_not_in_training failure",
            "trainer_changed": False, "split_membership_changed": False, "label_values_changed": False,
            "model_or_hyperparameter_changed": False, "lane_weights_changed": False,
            "training_marginal_pair_candidate_closure": True,
            "contact_filter_semantics": "exact raw source rows selected only by frozen split candidate_id",
            "failed_runtimes": [auth.NODE1_RUNTIME_ROOT, v11.NEW_RUNTIME],
        }
        write_json(graph_path, graph); graph_sha = base.sha256_file(graph_path)
        receipt_path = output / "node1_bundle" / "plan" / "receipt.json"; receipt = json.loads(receipt_path.read_text()); receipt["job_graph_path"] = str(Path(NEW_PACKAGE)/"plan/job_graph.json"); receipt["job_graph_sha256"] = graph_sha; write_json(receipt_path, receipt)
        overlay_path = output / "contracts" / "EXPLICIT_AUTHORIZATION_OVERLAY.json"; overlay = json.loads(overlay_path.read_text()); overlay["schema_version"] = "pvrig_v2_4_v2_2_2_strict_nested_explicit_authorization_recovery_v1_2"; overlay["recovery_scope"] = graph["recovery_contract"]; overlay["node1_package_root"] = NEW_PACKAGE; overlay["node1_runtime_root"] = NEW_RUNTIME; write_json(overlay_path, overlay)
        launcher = output / "node1_bundle" / "src" / "launch_authorized_strict_nested_v1.py"; text = auth.launcher_source(graph_sha, base.sha256_file(runner), base.sha256_file(overlay_path)).replace(auth.NODE1_PACKAGE_ROOT, NEW_PACKAGE).replace(auth.NODE1_RUNTIME_ROOT, NEW_RUNTIME); launcher.write_text(text); launcher.chmod(0o755)
        manifest_path = output / "PACKAGE_MANIFEST.json"; manifest = json.loads(manifest_path.read_text()); manifest["schema_version"] = "pvrig_v2_4_v2_2_2_strict_nested_authorized_recovery_package_v1_2"; manifest["status"] = "PASS_AUTHORIZED_SPLIT_SYNCHRONOUS_CONTACT_RECOVERY_AUDITED_READY_TO_SMOKE"; manifest["node1_package_root"] = NEW_PACKAGE; manifest["node1_runtime_root"] = NEW_RUNTIME; manifest["job_graph"] = {"relative_path":"node1_bundle/plan/job_graph.json","sha256":graph_sha,"job_count":195,"gpu_job_count":90,"cpu_job_count":105,"physical_gpus":[2,4,5]}; manifest["authorization_overlay_sha256"] = base.sha256_file(overlay_path); manifest["launcher"]={"relative_path":"node1_bundle/src/launch_authorized_strict_nested_v1.py","sha256":base.sha256_file(launcher)}; manifest["recovery_contract"]=graph["recovery_contract"]; manifest["split_contact_input_count"]=30; manifest["filtered_inner_contact_input_count"]=25; manifest["source_failed_authorized_package"]=str(source); write_json(manifest_path,manifest)
        sums=output/"SHA256SUMS"; files=sorted(path for path in output.rglob("*") if path.is_file() and path != sums)
        with sums.open("w") as handle:
            for path in files: handle.write(f"{base.sha256_file(path)}  {path.relative_to(output)}\n")
        return manifest
    except Exception:
        shutil.rmtree(output,ignore_errors=True); raise


def audit(root: Path) -> dict:
    root=root.resolve(); checked=0
    for line in (root/"SHA256SUMS").read_text().splitlines():
        expected,rel=line.split("  ",1); path=root/rel; base.require(path.is_file() and not path.is_symlink() and base.sha256_file(path)==expected,f"hash:{rel}"); checked+=1
    manifest=json.loads((root/"PACKAGE_MANIFEST.json").read_text()); graph=json.loads((root/"node1_bundle/plan/job_graph.json").read_text())
    base.require(manifest["status"]=="PASS_AUTHORIZED_SPLIT_SYNCHRONOUS_CONTACT_RECOVERY_AUDITED_READY_TO_SMOKE","status")
    base.require(graph["execution_authorized"] is True and graph["status"]==auth.AUTHORIZED_STATUS,"auth")
    base.require(len(graph["jobs"])==195 and len(graph["split_contact_inputs"])==30,"counts")
    base.require(graph["sealed_evaluation_access_count"]==0 and graph["prediction_metrics_access_count"]==0,"sealed")
    return {"status":"PASS_AUTHORIZED_V1_2_READY_FOR_PREOPTIMIZER_SMOKE","checked_file_count":checked,"job_count":195,"gpu_job_count":90,"cpu_job_count":105,"split_contact_input_count":30,"filtered_inner_contact_input_count":25,"physical_gpus":[2,4,5],"sealed_evaluation_access_count":0}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--source-v1-1-package",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True); a=p.parse_args(); result=build(a.source_v1_1_package,a.output_dir); print(json.dumps({"status":result["status"],"job_graph_sha256":result["job_graph"]["sha256"],"node1_package_root":result["node1_package_root"],"node1_runtime_root":result["node1_runtime_root"]},sort_keys=True)); return 0


if __name__=="__main__": raise SystemExit(main())
