#!/usr/bin/env python3
"""Build deterministic, content-bound trust anchors for the V4-D/V4-F V3 watchers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Mapping


CANONICAL_EXP = Path("/mnt/d/work/抗体/data/experiments/phase2_5080_v1")


class AnchorError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_regular(path: Path, role: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AnchorError(f"missing:{role}:{path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AnchorError(f"regular_non_symlink_required:{role}:{path}")
    if metadata.st_size <= 0:
        raise AnchorError(f"empty:{role}:{path}")
    return metadata


def surrogate_files(exp: Path) -> dict[str, Path]:
    embedding = exp / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
    roles = {
        "v3_watcher": exp / "src/monitor_phase2_v4_d_surrogate_training_v3.sh",
        "v3_helper": exp / "src/phase2_v4_d_surrogate_watcher_helper_v3.py",
        "base_trainer": exp / "src/train_phase2_v4_d_surrogate.py",
        "embedding_trainer": exp / "src/train_phase2_v4_d_frozen_embedding_surrogate.py",
        "contact_trainer": exp / "src/train_phase2_v4_d_contact_feature_surrogate.py",
        "split_manifest": exp / "data_splits/pvrig_v4_d/fullqc290_split_manifest.tsv",
        "contact_schema": exp / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
        "contact_schema_receipt": exp / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.receipt.json",
        "contact_features": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv",
        "contact_feature_audit": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json",
        "contact_feature_receipt": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
        "contact_feature_verification": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.verification.json",
        "embedding_manifest": embedding / "meanpool_embeddings/embedding_manifest_v3.csv",
        "embedding_summary": embedding / "meanpool_embeddings/embedding_summary_v3.json",
        "embedding_sequence_manifest": embedding / "sequence_manifest_v3.csv",
    }
    for index in range(7):
        roles[f"embedding_shard_{index:05d}"] = (
            embedding / f"meanpool_embeddings/shards/shard_{index:05d}.pt"
        )
    return roles


def v4f_files(exp: Path) -> dict[str, Path]:
    embedding = exp / "prepared/pvrig_teacher_formal_v1_candidates/model_inputs"
    roles = {
        "v3_watcher": exp / "src/monitor_phase2_v4_f_prediction_freeze_v3.sh",
        "freezer": exp / "src/freeze_phase2_v4_f_surrogate_predictions.py",
        "base_trainer": exp / "src/train_phase2_v4_d_surrogate.py",
        "embedding_trainer": exp / "src/train_phase2_v4_d_frozen_embedding_surrogate.py",
        "contact_trainer": exp / "src/train_phase2_v4_d_contact_feature_surrogate.py",
        "contact_extractor": exp / "src/extract_pvrig_v2_3_residue_contact_features.py",
        "contact_scorer": exp / "src/score_pvrig_candidates_v2_3.py",
        "v2_3_trainer": exp / "src/train_phase2_v2_3.py",
        "v4f_manifest": exp / "data_splits/pvrig_v4_f/prospective_holdout96_manifest.tsv",
        "v4f_manifest_audit": exp / "data_splits/pvrig_v4_f/prospective_holdout96_audit.json",
        "v4f_manifest_receipt": exp / "data_splits/pvrig_v4_f/prospective_holdout96_receipt.json",
        "contact_schema": exp / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.json",
        "contact_schema_receipt": exp / "prepared/pvrig_v4_d/frozen_contact_feature_schema_v2.receipt.json",
        "contact_features": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.csv",
        "contact_feature_audit": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.audit.json",
        "contact_feature_receipt": exp / "predictions/pvrig_candidate_v2_3_residue_contact_features_v3.receipt.json",
        "embedding_manifest": embedding / "meanpool_embeddings/embedding_manifest_v3.csv",
        "embedding_summary": embedding / "meanpool_embeddings/embedding_summary_v3.json",
        "embedding_sequence_manifest": embedding / "sequence_manifest_v3.csv",
        "surrogate_v3_trust_anchor": exp / "audits/phase2_v4_d_surrogate_training_v3_implementation_trust_anchor.json",
    }
    for index in range(7):
        roles[f"embedding_shard_{index:05d}"] = (
            embedding / f"meanpool_embeddings/shards/shard_{index:05d}.pt"
        )
    return roles


def build_payload(kind: str, exp: Path) -> dict[str, object]:
    if kind == "surrogate":
        schema = "phase2_v4_d_surrogate_implementation_trust_anchor_v3"
        status = "FROZEN_BEFORE_OPEN258_TEACHER_AND_SURROGATE_TRAINING"
        anchor_kind = "v4d_surrogate_training"
        files = surrogate_files(exp)
    else:
        schema = "phase2_v4_f_prediction_implementation_trust_anchor_v3"
        status = "FROZEN_BEFORE_V4F_PREDICTION_FREEZE"
        anchor_kind = "v4f_prediction_freeze"
        files = v4f_files(exp)
    entries: dict[str, dict[str, object]] = {}
    seen: set[Path] = set()
    for role, source in sorted(files.items()):
        source = source.resolve()
        metadata = require_regular(source, role)
        if source in seen:
            raise AnchorError(f"duplicate_trust_path:{source}")
        seen.add(source)
        entries[role] = {
            "path": str(source),
            "size": metadata.st_size,
            "sha256": sha256_file(source),
        }
    return {
        "schema_version": schema,
        "status": status,
        "anchor_kind": anchor_kind,
        "files": entries,
        "file_count": len(entries),
        "claim_boundary": (
            "Implementation and label-free input integrity only; no docking, binding, "
            "affinity, competition, or experimental blocking evidence."
        ),
    }


def write_atomic(path: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path.exists():
        require_regular(path, "existing_anchor")
        if path.read_text(encoding="utf-8") != encoded:
            raise AnchorError(f"existing_anchor_differs:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("surrogate", "v4f"), required=True)
    parser.add_argument("--exp-dir", type=Path, default=CANONICAL_EXP)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--test-only-noncanonical-root", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exp = args.exp_dir.resolve()
    if args.test_only_noncanonical_root:
        if exp == CANONICAL_EXP.resolve():
            raise AnchorError("test_only_mode_forbidden_on_production_root")
    elif exp != CANONICAL_EXP.resolve():
        raise AnchorError("production_anchor_requires_canonical_exp_dir")
    if not args.test_only_noncanonical_root:
        expected_output = CANONICAL_EXP / (
            "audits/phase2_v4_d_surrogate_training_v3_implementation_trust_anchor.json"
            if args.kind == "surrogate"
            else "audits/phase2_v4_f_prediction_freeze_v3_implementation_trust_anchor.json"
        )
        if args.out.resolve() != expected_output.resolve():
            raise AnchorError(f"production_anchor_output_path_invalid:{args.out}")
    payload = build_payload(args.kind, exp)
    write_atomic(args.out.resolve(), payload)
    print(
        json.dumps(
            {
                "status": "PASS_TRUST_ANCHOR_BUILT",
                "kind": args.kind,
                "path": str(args.out.resolve()),
                "sha256": sha256_file(args.out.resolve()),
                "file_count": payload["file_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
