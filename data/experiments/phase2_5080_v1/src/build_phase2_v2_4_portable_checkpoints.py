#!/usr/bin/env python3
"""Create durable V2.4 checkpoints from runtime-staged formal runs."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import torch

CHECKPOINT_SCHEMA = "phase2_v2_4_listwise_ranking_checkpoint_v1"
REQUIRED_SEEDS = (43, 53, 67)
DURABLE_CFG_PATHS = {
    "clustered_site_csv": "experiments/phase2_5080_v1/data_splits/zym_site_split_manifest_v2_clustered.csv",
    "pair_csv": "experiments/phase2_5080_v1/data_splits/pair_binding_split_v2_clustered.csv",
    "ranking_triplets_csv": "experiments/phase2_5080_v1/data_splits/pair_ranking_triplets_v2_clustered.csv",
    "ranking_groups_csv": "experiments/phase2_5080_v1/data_splits/pair_ranking_groups_v2_4.csv",
    "pvrig_controls_csv": "experiments/phase2_5080_v1/data_splits/pvrig_validation_controls_v2_4.csv",
    "contact_jsonl": "experiments/phase2_5080_v1/prepared/structure_contact_maps_v3_clustered.jsonl",
    "esm2_cache_manifest": "experiments/phase2_5080_v1/prepared/esm2_8m_v2_3_cache/manifest.csv",
    "cdr_mask_csv": "experiments/phase2_5080_v1/data_splits/vhh_cdr_type_masks_v2_3.csv",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_states_equal(left: dict[str, torch.Tensor], right: dict[str, torch.Tensor]) -> bool:
    return left.keys() == right.keys() and all(torch.equal(left[key].cpu(), right[key].cpu()) for key in left)


def make_portable_payload(checkpoint: dict[str, Any], seed: int) -> dict[str, Any]:
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA:
        raise ValueError(f"Seed {seed} has incompatible checkpoint schema")
    cfg = dict(checkpoint.get("cfg") or {})
    if int(cfg.get("seed", seed)) != seed:
        raise ValueError(f"Seed identity mismatch: expected {seed}, observed {cfg.get('seed')}")
    cfg.update(DURABLE_CFG_PATHS)
    cfg.update({
        "root": ".",
        "out_root": "experiments/phase2_5080_v1",
        "seed": seed,
        "init_checkpoint": f"experiments/phase2_5080_v1/checkpoints/phase2_v2_3_strict_seed{seed}_best_checkpoint.pt",
    })
    portable = copy.deepcopy(checkpoint)
    portable["cfg"] = cfg
    portable["best_checkpoint_path"] = f"experiments/phase2_5080_v1/checkpoints/phase2_v2_4_strict_seed{seed}_best_checkpoint.pt"
    warmstart = dict(portable.get("warmstart") or {})
    warmstart["source"] = cfg["init_checkpoint"]
    portable["warmstart"] = warmstart
    portable["portability"] = {
        "status": "PASS",
        "runtime_staging_removed": True,
        "durable_relative_paths": True,
        "model_state_unchanged": True,
    }
    return portable


def write_portable_checkpoint(source: Path, output: Path, seed: int) -> dict[str, Any]:
    original = torch.load(source, map_location="cpu", weights_only=False)
    portable = make_portable_payload(original, seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    torch.save(portable, temporary)
    reloaded = torch.load(temporary, map_location="cpu", weights_only=False)
    state_equal = model_states_equal(original["model"], reloaded["model"])
    if not state_equal:
        temporary.unlink(missing_ok=True)
        raise ValueError(f"Model state changed while portableizing seed {seed}")
    temporary.replace(output)
    return {
        "seed": seed,
        "source": str(source),
        "portable": str(output),
        "source_sha256": file_sha256(source),
        "portable_sha256": file_sha256(output),
        "epoch": int(reloaded.get("epoch", -1)),
        "best_score": float(reloaded.get("best_score", float("nan"))),
        "model_state_roundtrip_equal": state_equal,
        "durable_cfg_paths": {name: reloaded["cfg"][name] for name in DURABLE_CFG_PATHS},
    }


def parse_seed_path(value: str) -> tuple[int, Path]:
    try:
        seed_text, path_text = value.split("=", 1)
        return int(seed_text), Path(path_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("--source must be SEED=CHECKPOINT") from exc


def build_portable_set(sources: dict[int, Path], output_dir: Path, canonical: Path, audit_json: Path) -> dict[str, Any]:
    if set(sources) != set(REQUIRED_SEEDS):
        raise ValueError(f"Expected source seeds {REQUIRED_SEEDS}, observed {sorted(sources)}")
    records = []
    for seed in REQUIRED_SEEDS:
        output = output_dir / f"phase2_v2_4_strict_seed{seed}_best_checkpoint.pt"
        records.append(write_portable_checkpoint(sources[seed], output, seed))
    selected = max(records, key=lambda record: (record["best_score"], -record["seed"]))
    canonical.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(selected["portable"], canonical)
    result = {
        "status": "PASS",
        "schema_version": "phase2_v2_4_portable_checkpoints_v1",
        "checkpoints": records,
        "canonical_seed": selected["seed"],
        "canonical_selection": "maximum validation composite best_score among preregistered seeds 43, 53, 67",
        "canonical_alias": str(canonical),
        "canonical_alias_sha256": file_sha256(canonical),
        "canonical_matches_selected_portable_sha256": file_sha256(canonical) == selected["portable_sha256"],
        "boundary": "Runtime /tmp staging changed only input location; portable checkpoints restore durable project paths without changing model tensors.",
    }
    audit_json.parent.mkdir(parents=True, exist_ok=True)
    audit_json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True, type=parse_seed_path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    args = parser.parse_args()
    sources = dict(args.source)
    if len(sources) != len(args.source):
        raise ValueError("Duplicate --source seed")
    print(json.dumps(build_portable_set(sources, args.output_dir, args.canonical, args.audit_json), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
