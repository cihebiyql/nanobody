#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib.util
import inspect
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import numpy as np
import torch


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
MODULE_PATH = SCRIPT_DIR / "score_phase2_v4_d_deployment.py"
SPEC = importlib.util.spec_from_file_location("score_phase2_v4_d_deployment", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def write_table(path: Path, rows: list[dict[str, object]], delimiter: str = ",") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class DeploymentFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.pool = root / "candidate_pool.csv"
        self.support_csv = root / "support.csv"
        self.support_audit = root / "support.csv.audit.json"
        self.support_receipt = root / "support.csv.receipt.json"
        self.v4d_manifest = root / "v4d.tsv"
        self.v4d_audit = root / "v4d.audit.json"
        self.v4f_manifest = root / "v4f.tsv"
        self.v4f_audit = root / "v4f.audit.json"
        self.v4f_receipt = root / "v4f.receipt.json"
        self.v4g_reserve = root / "reserve.tsv"
        self.v4g_preregistration = root / "v4g_preregistration.json"
        self.v4g_receipt = root / "v4g.receipt.json"
        self.split = root / "split.tsv"
        self.support_impl = root / "support_impl.py"
        self.contact_csv = root / "contact.csv"
        self.contact_audit = root / "contact.audit.json"
        self.contact_receipt = root / "contact.receipt.json"
        self.contact_schema = root / "contact_schema.json"
        self.sequence_manifest = root / "sequence_manifest.csv"
        self.embedding_manifest = root / "embedding_manifest.csv"
        self.embedding_summary = root / "embedding_summary.json"
        self.base_dir = root / "base"
        self.embedding_dir = root / "embedding"
        self.contact_dir = root / "contact"
        self.out_dir = root / "deployment"
        self.candidates = self._make_candidates()
        self._write_governance()
        self._write_support_release(all_gates_passed=True)
        self.stable_features = (
            "paratope_mean",
            "contact_global_mean",
        )
        self._write_contact_release()
        self.bank = self._write_embedding_release()
        self._write_model_stages()

    def _make_candidates(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for index in range(7):
            token = MOD.base.AA_ORDER[index]
            cdr1 = "GFTF" + token + "SY"
            cdr2 = "IS" + token + "GGT"
            cdr3 = "CAR" + token * (3 + index) + "W"
            sequence = (
                "QVQLVESGGGLVQPGGSLRLSCAAS"
                + cdr1
                + "MGWYRQAPGKERELVA"
                + cdr2
                + "AYKDSVKGRFTISRDFSRSTMYLQMNSLKPEDTAIYYC"
                + cdr3
                + "GQGTQVTVSS"
            )
            rows.append(
                {
                    "candidate_id": f"candidate-{index}",
                    "vhh_sequence": sequence,
                    "sequence_sha256": MOD.base.sequence_sha256(sequence),
                    "parent_framework_cluster": f"P{index}",
                    "design_method": "synthetic",
                    "design_mode": "H3",
                    "target_patch_id": ("A", "B", "C")[index % 3],
                    "cdr1_after": cdr1,
                    "cdr2_after": cdr2,
                    "cdr3_after": cdr3,
                    "generic_binding_prior": 0.1 + 0.1 * index,
                }
            )
        write_table(self.pool, rows)
        return rows

    def _write_governance(self) -> None:
        def identity(index: int) -> dict[str, object]:
            row = self.candidates[index]
            return {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "parent_framework_cluster": row["parent_framework_cluster"],
            }

        write_table(self.v4d_manifest, [identity(index) for index in (0, 1, 2)], "\t")
        write_json(
            self.v4d_audit,
            {
                "status": "PASS_PROSPECTIVE_COMPUTATIONAL_SPLIT",
                "manifest": {"sha256": MOD.sha256_file(self.v4d_manifest)},
            },
        )
        write_table(self.v4f_manifest, [identity(index) for index in (0, 1)], "\t")
        write_json(
            self.v4f_audit,
            {
                "status": "PASS_PROSPECTIVE_V4_F_HOLDOUT_FROZEN",
                "output": {"sha256": MOD.sha256_file(self.v4f_manifest)},
            },
        )
        write_json(
            self.v4f_receipt,
            {
                "status": "PASS_COMPLETE_HASH_CLOSURE",
                "manifest_sha256": MOD.sha256_file(self.v4f_manifest),
                "audit_file_sha256": MOD.sha256_file(self.v4f_audit),
            },
        )
        reserve_rows = [
            {
                "parent_framework_cluster": "P0",
                "selection_role": "UNTOUCHED_V4_G_RESERVE_PARENT",
                "untouched_policy": "no_model_scoring;no_full_qc;no_docking",
            }
        ]
        write_table(self.v4g_reserve, reserve_rows, "\t")
        write_json(
            self.v4g_preregistration,
            {
                "status": "FROZEN_LABEL_FREE_BEFORE_V4D_OPEN_TEACHER_OR_V4F_DOCKING_LABELS",
                "untouched_reserve2": {
                    "parent_clusters": ["P0"],
                    "parent_manifest_sha256": MOD.sha256_file(self.v4g_reserve),
                    "policy": "no model scoring, Full-QC, docking, or label opening",
                },
            },
        )
        write_json(
            self.v4g_receipt,
            {
                "status": "PASS_COMPLETE_HASH_CLOSURE_RECEIPT_PUBLISHED_LAST",
                "outputs": {
                    self.v4g_reserve.name: MOD.sha256_file(self.v4g_reserve),
                    self.v4g_preregistration.name: MOD.sha256_file(
                        self.v4g_preregistration
                    ),
                },
            },
        )

    def _support_rows(self) -> list[dict[str, object]]:
        domains = (
            "IN_DOMAIN",
            "IN_DOMAIN",
            "NEAR_DOMAIN",
            "IN_DOMAIN",
            "NEAR_DOMAIN",
            "OOD",
            "TRAIN_REFERENCE",
        )
        return [
            {
                "candidate_id": row["candidate_id"],
                "sequence_sha256": row["sequence_sha256"],
                "parent_framework_cluster": row["parent_framework_cluster"],
                "v4d_in_sequence_support": str(domains[index] == "IN_DOMAIN").lower(),
                "v4d_support_domain": domains[index],
                "v4d_support_domain_reason": f"synthetic_{domains[index].lower()}",
            }
            for index, row in enumerate(self.candidates)
        ]

    def _write_support_release(self, *, all_gates_passed: bool) -> None:
        write_table(self.support_csv, self._support_rows())
        write_table(
            self.split,
            [
                {
                    "candidate_id": self.candidates[0]["candidate_id"],
                    "model_split": MOD.base.TRAIN_SPLIT,
                }
            ],
            "\t",
        )
        self.support_impl.write_text("# synthetic\n", encoding="utf-8")
        configuration = {"synthetic": True}
        gates = {"synthetic_gate": {"observed": int(all_gates_passed), "passed": all_gates_passed}}
        audit: dict[str, object] = {
            "schema_version": MOD.support.SCHEMA_VERSION,
            "status": (
                "PASS_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
                if all_gates_passed
                else "FAIL_LABEL_FREE_SEQUENCE_SUPPORT_GATES"
            ),
            "execution_mode": "TEST_ONLY_UNFROZEN_CONFIGURATION",
            "production_lock_id": "synthetic",
            "configuration": configuration,
            "configuration_sha256": MOD.support.sha256_json(configuration),
            "implementation": {
                "path": str(self.support_impl.resolve()),
                "sha256": MOD.sha256_file(self.support_impl),
            },
            "inputs": {
                "split_manifest": {
                    "path": str(self.split.resolve()),
                    "sha256": MOD.sha256_file(self.split),
                    "row_count": 1,
                },
                "candidate_pool": {
                    "path": str(self.pool.resolve()),
                    "sha256": MOD.sha256_file(self.pool),
                    "row_count": len(self.candidates),
                },
            },
            "outputs": {
                "sequence_support_csv": {
                    "path": str(self.support_csv.resolve()),
                    "sha256": MOD.sha256_file(self.support_csv),
                    "row_count": len(self.candidates),
                }
            },
            "gates": gates,
            "all_gates_passed": all_gates_passed,
            "coverage": {"candidate_count": len(self.candidates)},
            "claim_boundary": "synthetic_label_free_support",
        }
        audit["audit_payload_sha256"] = MOD.support.sha256_json(audit)
        write_json(self.support_audit, audit)
        receipt = {
            "schema_version": MOD.support.SCHEMA_VERSION,
            "status": "PASS_COMPLETE_HASH_CLOSURE",
            "configuration_sha256": audit["configuration_sha256"],
            "production_lock_id": "synthetic",
            "audit": {
                "path": str(self.support_audit.resolve()),
                "sha256": MOD.sha256_file(self.support_audit),
            },
            "bindings": {
                "split_manifest": audit["inputs"]["split_manifest"],
                "candidate_pool": audit["inputs"]["candidate_pool"],
                "implementation": audit["implementation"],
                "sequence_support_csv": audit["outputs"]["sequence_support_csv"],
            },
        }
        write_json(self.support_receipt, receipt)

    def set_support_gates(self, passed: bool) -> None:
        self._write_support_release(all_gates_passed=passed)

    def _write_contact_release(self) -> None:
        all_stable_columns = [
            column
            for feature in MOD.contact.contact_v3.STABLE_FEATURE_NAMES
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        ]
        rows: list[dict[str, object]] = []
        for index, candidate in enumerate(self.candidates):
            row: dict[str, object] = {
                "schema_version": MOD.contact.contact_v3.SCHEMA_VERSION,
                "supersedes": ";".join(
                    MOD.contact.contact_v3.SUPERSEDED_SCHEMA_VERSIONS
                ),
                "candidate_id": candidate["candidate_id"],
                "sequence_sha256": candidate["sequence_sha256"],
            }
            for feature_index, feature in enumerate(
                MOD.contact.contact_v3.STABLE_FEATURE_NAMES, start=1
            ):
                row[f"{feature}_seed_mean"] = (index + 1) * feature_index / 100.0
                row[f"{feature}_seed_std"] = 0.01 + feature_index / 10000.0
            for feature in MOD.contact.contact_v3.DIAGNOSTIC_ONLY_FEATURES:
                row[f"{feature}_seed_mean"] = float(index + 1)
                row[f"{feature}_seed_std"] = 0.1
            rows.append(row)
        write_table(self.contact_csv, rows)
        dummy = self.root / "label_free_contact_input.txt"
        dummy.write_text("label-free\n", encoding="utf-8")
        snapshot = MOD.contact.contact_v3.snapshot_files({"label_free_input": dummy})
        audit = {
            "status": "PASS",
            "feature_schema_version": MOD.contact.contact_v3.SCHEMA_VERSION,
            "output_sha256": MOD.sha256_file(self.contact_csv),
            "input_snapshot_unchanged": True,
            "label_free_contract": {
                "production_hash_locks_enforced": False,
                "test_only_unfrozen_hash_override": True,
            },
            "feature_policy": {
                "stable_default_trainer_features": list(
                    MOD.contact.contact_v3.STABLE_FEATURE_NAMES
                ),
                "stable_default_trainer_columns": all_stable_columns,
                "default_trainer_must_exclude": list(
                    MOD.contact.contact_v3.DIAGNOSTIC_ONLY_FEATURES
                ),
                "default_trainer_must_exclude_columns": [],
            },
        }
        write_json(self.contact_audit, audit)
        receipt = {
            "status": "PASS",
            "schema_version": MOD.contact.contact_v3.RECEIPT_SCHEMA_VERSION,
            "feature_schema_version": MOD.contact.contact_v3.SCHEMA_VERSION,
            "output": str(self.contact_csv.resolve()),
            "output_sha256": MOD.sha256_file(self.contact_csv),
            "output_row_count": len(rows),
            "audit": str(self.contact_audit.resolve()),
            "audit_sha256": MOD.sha256_file(self.contact_audit),
            "input_snapshot": snapshot,
            "input_snapshot_content_closure_sha256": MOD.contact.contact_v3.snapshot_content_closure(snapshot),
            "script": str(Path(MOD.contact.contact_v3.__file__).resolve()),
            "script_sha256": MOD.sha256_file(Path(MOD.contact.contact_v3.__file__)),
            "claim_boundary": MOD.contact.contact_v3.CLAIM_BOUNDARY,
        }
        write_json(self.contact_receipt, receipt)
        configuration = {
            "schema_version": MOD.contact.CONTACT_SCHEMA_VERSION,
            "selection_uses_docking_labels": False,
            "production_hash_enforcement": False,
        }
        schema: dict[str, object] = {
            "schema_version": MOD.contact.CONTACT_SCHEMA_VERSION,
            "status": "TEST_ONLY_PASS_CONTACT_FEATURE_SCHEMA",
            "execution_mode": "test_only",
            "configuration": configuration,
            "configuration_sha256": MOD.contact.sha256_json(configuration),
            "inputs": {
                "feature_release_receipt": {
                    "path": str(self.contact_receipt.resolve()),
                    "sha256": MOD.sha256_file(self.contact_receipt),
                }
            },
            "selected_feature_count": len(self.stable_features),
            "selected_features": list(self.stable_features),
            "diagnostic_only_length_confounded_features": list(
                MOD.contact.contact_v3.DIAGNOSTIC_ONLY_FEATURES
            ),
            "required_shortcut_baseline": "cdr_length_only",
            "training_feature_sets": {
                "stable_seed_mean": [
                    f"{feature}_seed_mean" for feature in self.stable_features
                ],
                "stable_seed_mean_and_std": [
                    column
                    for feature in self.stable_features
                    for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
                ],
            },
            "feature_stability": [
                {
                    "feature": feature,
                    "selected": True,
                    "cross_seed_stable": True,
                    "length_confounded": False,
                }
                for feature in self.stable_features
            ],
        }
        schema["payload_sha256"] = MOD.contact.sha256_json(schema)
        write_json(self.contact_schema, schema)
        schema_receipt = {
            "schema_version": MOD.contact.CONTACT_SCHEMA_RECEIPT_VERSION,
            "status": "TEST_ONLY_PASS_HASH_CLOSURE",
            "configuration_sha256": schema["configuration_sha256"],
            "feature_release_receipt_sha256": MOD.sha256_file(self.contact_receipt),
            "schema_file_sha256": MOD.sha256_file(self.contact_schema),
            "schema_payload_sha256": schema["payload_sha256"],
        }
        write_json(self.contact_schema.with_suffix(".receipt.json"), schema_receipt)

    def _write_embedding_release(self) -> MOD.embedding.EmbeddingBank:
        antigen = "ACDEFGHIKLMNPQRSTVWY"
        sequence_rows = [
            {
                "sequence_sha256": row["sequence_sha256"],
                "sequence": row["vhh_sequence"],
                "sequence_length": len(str(row["vhh_sequence"])),
                "roles": "vhh",
            }
            for row in self.candidates
        ]
        sequence_rows.append(
            {
                "sequence_sha256": MOD.base.sequence_sha256(antigen),
                "sequence": antigen,
                "sequence_length": len(antigen),
                "roles": "antigen",
            }
        )
        sequence_rows.sort(key=lambda row: str(row["sequence_sha256"]))
        write_table(self.sequence_manifest, sequence_rows)
        config = {
            "backend": "hash",
            "vhhbert_model_path": "synthetic",
            "esm2_model_path": "synthetic",
            "vhhbert_model_sha256": "synthetic",
            "esm2_model_sha256": "synthetic",
            "vhhbert_dim": 5,
            "esm2_dim": 4,
            "physchem_dim": 3,
            "max_esm_residues": 1000,
            "chunk_overlap": 0,
            "pooling": "residue_mean_excluding_special_tokens",
        }
        config_sha = MOD.embedding.sha256_json(config)
        hashes = [str(row["sequence_sha256"]) for row in sequence_rows]
        roles = [str(row["roles"]) for row in sequence_rows]
        esm2 = torch.tensor(
            [[index / 10.0, (index + 1) / 10.0, index % 2, 1.0] for index in range(len(hashes))],
            dtype=torch.float32,
        )
        vhhbert = torch.tensor(
            [[index / 10.0, index / 20.0, index % 2, index % 3, 1.0] for index in range(len(hashes))],
            dtype=torch.float32,
        )
        physchem = torch.tensor(
            [[index / 10.0, index % 2, 1.0] for index in range(len(hashes))],
            dtype=torch.float32,
        )
        shard = self.root / "shards/shard_00000.pt"
        shard.parent.mkdir()
        torch.save(
            {
                "schema_version": "phase2_v3_embedding_shard_v1",
                "config_sha256": MOD.embedding.sha256_json(
                    {"config": config, "sequence_sha256": hashes}
                ),
                "sequence_sha256": hashes,
                "esm2": esm2,
                "vhhbert": vhhbert,
                "physchem": physchem,
                "vhhbert_available": torch.tensor(
                    [role == "vhh" for role in roles], dtype=torch.bool
                ),
            },
            shard,
        )
        manifest_rows = [
            {
                "sequence_sha256": row["sequence_sha256"],
                "sequence_length": row["sequence_length"],
                "roles": row["roles"],
                "shard_path": str(shard.resolve()),
                "shard_index": index,
                "esm2_dim": 4,
                "vhhbert_dim": 5,
                "physchem_dim": 3,
                "config_sha256": config_sha,
            }
            for index, row in enumerate(sequence_rows)
        ]
        write_table(self.embedding_manifest, manifest_rows)
        summary = {
            "schema_version": "phase2_v3_embedding_summary_v1",
            "sequence_manifest": str(self.sequence_manifest.resolve()),
            "sequence_manifest_sha256": MOD.sha256_file(self.sequence_manifest),
            "embedding_manifest": str(self.embedding_manifest.resolve()),
            "embedding_manifest_sha256": MOD.sha256_file(self.embedding_manifest),
            "config": config,
            "config_sha256": config_sha,
            "sequence_count": len(sequence_rows),
            "vhh_sequence_count": len(self.candidates),
            "antigen_sequence_count": 1,
            "shard_count": 1,
            "shard_sha256": {shard.name: MOD.sha256_file(shard)},
        }
        write_json(self.embedding_summary, summary)
        return MOD.embedding.load_embedding_bank(
            self.embedding_manifest,
            self.embedding_summary,
            self.sequence_manifest,
            enforce_production_hashes=False,
        )

    @staticmethod
    def _fits(width: int, base_intercept: float) -> list[dict[str, object]]:
        fits = []
        for seed, offset in ((11, -0.02), (12, 0.0), (13, 0.03)):
            fits.append(
                {
                    "seed": seed,
                    "fit": {
                        "intercept": base_intercept + offset,
                        "coefficient": [0.01 * (index + 1) for index in range(width)],
                        "center": [0.0] * width,
                        "scale": [1.0] * width,
                    },
                }
            )
        return fits

    def _write_stage(
        self,
        stage: str,
        directory: Path,
        artifact: dict[str, object],
        summary: dict[str, object],
    ) -> None:
        directory.mkdir(parents=True)
        names = {
            "base": MOD.watcher.BASE_OUTPUTS,
            "embedding": MOD.watcher.EMBEDDING_OUTPUTS,
            "contact": MOD.watcher.CONTACT_OUTPUTS,
        }[stage]
        config_name = MOD.STAGE_CONFIGS[stage]
        artifact_name = MOD.STAGE_ARTIFACTS[stage]
        summary_name = MOD.STAGE_SUMMARIES[stage]
        config = {
            "prospective_test": {"labels_read": False, "label_files_opened": 0},
            "prospective_test_labels_read": False,
        }
        if stage == "contact":
            config["artifact_identity_contract"] = {
                field: artifact[field]
                for field in (
                    "embedding_bank_identity_sha256",
                    "contact_release_receipt_sha256",
                    "contact_schema_sha256",
                    "stable_contact_columns_sha256",
                )
            }
        write_json(directory / config_name, config)
        artifact["config_sha256"] = MOD.sha256_file(directory / config_name)
        write_json(directory / artifact_name, artifact)
        write_json(directory / summary_name, summary)
        for name in names:
            path = directory / name
            if path.exists():
                continue
            if name.endswith(".tsv"):
                if name == "frozen_prospective_test_predictions.tsv":
                    write_table(
                        path,
                        [
                            {
                                "candidate_id": "sealed-prediction-only",
                                "model_split": MOD.base.SEALED_SPLIT,
                                "prediction": 0.5,
                            }
                        ],
                        "\t",
                    )
                else:
                    write_table(path, [{"candidate_id": "open-development", "prediction": 0.5}], "\t")
            else:
                write_json(path, {"synthetic": True})
        receipt_status = {
            "base": "PASS_FROZEN_OPEN_ARTIFACT_HASH_CLOSURE",
            "embedding": "PASS_FROZEN_EMBEDDING_ARTIFACT_HASH_CLOSURE",
            "contact": "PASS_FROZEN_OPEN_CONTACT_FUSION_ARTIFACT_HASH_CLOSURE",
        }[stage]
        receipt: dict[str, object] = {
            "status": receipt_status,
            "prospective_test_labels_read": False,
            "inputs": self.contact_stage_inputs if stage == "contact" else {},
            "outputs": {
                str((directory / name).resolve()): MOD.sha256_file(directory / name)
                for name in names
            },
        }
        if stage == "contact":
            receipt.update(
                {
                    "stable_contact_columns": list(self.contact_stable_columns),
                    "embedding_bank_identity_sha256": artifact[
                        "embedding_bank_identity_sha256"
                    ],
                    "contact_release_receipt_sha256": artifact[
                        "contact_release_receipt_sha256"
                    ],
                    "contact_schema_sha256": artifact["contact_schema_sha256"],
                    "stable_contact_columns_sha256": artifact[
                        "stable_contact_columns_sha256"
                    ],
                    "stage_inputs_closure_sha256": artifact[
                        "stage_inputs_closure_sha256"
                    ],
                }
            )
        write_json(directory / MOD.STAGE_RECEIPTS[stage], receipt)

    def _write_model_stages(self) -> None:
        base_spec = MOD.base.build_feature_spec(
            "frozen_feature_ridge", self._adapted_candidates(), frozen_feature_width=8
        )
        base_artifact: dict[str, object] = {
            "schema_version": MOD.base.SCHEMA_VERSION,
            "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
            "selected_candidate_model": "frozen_feature_ridge",
            "models": {name: {} for name in MOD.base.MODEL_NAMES},
            "prospective_test_labels_read": False,
        }
        base_artifact["models"]["frozen_feature_ridge"] = {
            "feature_spec": base_spec.to_json(),
            "bootstrap_ensemble_fits": self._fits(8, 0.2),
        }
        base_summary = {
            "status": "PASS_OPEN_DEVELOPMENT_GATES_PROSPECTIVE_TEST_STILL_SEALED",
            "prospective_test": {"labels_read": False, "label_files_opened": 0},
        }
        self._write_stage("base", self.base_dir, base_artifact, base_summary)

        embedding_artifact: dict[str, object] = {
            "schema_version": MOD.embedding.SCHEMA_VERSION,
            "status": "FROZEN_MODEL_TEST_LABELS_NOT_READ",
            "embedding_config_sha256": self.bank.config_sha256,
            "embedding_bank_identity_sha256": self.bank.provenance["identity_sha256"],
            "selected_model": "esm2_ridge",
            "models": {name: {} for name in MOD.embedding.EMBEDDING_MODELS},
            "prospective_test_labels_read": False,
        }
        embedding_artifact["models"]["esm2_ridge"] = {
            "channels": ["esm2"],
            "feature_dim": 4,
            "bootstrap_ensemble_fits": self._fits(4, 0.3),
        }
        embedding_summary = {
            "status": "PASS_OPEN_GATES_FROZEN_TEST_PREDICTIONS_UNEVALUATED",
            "open_gates_pass": True,
            "prospective_test": {"labels_read": False, "label_files_opened": 0},
        }
        self._write_stage(
            "embedding", self.embedding_dir, embedding_artifact, embedding_summary
        )

        stable_columns = tuple(
            column
            for feature in self.stable_features
            for column in (f"{feature}_seed_mean", f"{feature}_seed_std")
        )
        contact_spec = MOD.contact.build_feature_spec(
            "embedding_contact_fusion", stable_columns, 4
        )
        self.contact_stable_columns = stable_columns
        self.contact_stage_inputs = {
            str(self.contact_receipt.resolve()): MOD.sha256_file(self.contact_receipt),
            str(self.contact_schema.resolve()): MOD.sha256_file(self.contact_schema),
            str(self.embedding_manifest.resolve()): MOD.sha256_file(
                self.embedding_manifest
            ),
            str(self.embedding_summary.resolve()): MOD.sha256_file(
                self.embedding_summary
            ),
            str(self.sequence_manifest.resolve()): MOD.sha256_file(
                self.sequence_manifest
            ),
        }
        contact_identity = {
            "embedding_bank_identity_sha256": self.bank.provenance["identity_sha256"],
            "contact_release_receipt_sha256": MOD.sha256_file(self.contact_receipt),
            "contact_schema_sha256": MOD.sha256_file(self.contact_schema),
            "stable_contact_columns_sha256": MOD.base.sha256_strings(stable_columns),
            "stage_inputs_closure_sha256": MOD.contact.sha256_json(
                self.contact_stage_inputs
            ),
        }
        contact_artifact: dict[str, object] = {
            "schema_version": MOD.contact.SCHEMA_VERSION,
            "status": "FROZEN_OPEN_MODEL_ARTIFACT_NOT_PROSPECTIVE_TEST_EVALUATED",
            "selected_candidate_model": "embedding_contact_fusion",
            "models": {name: {} for name in MOD.contact.MODEL_NAMES},
            "prospective_test_labels_read": False,
            **contact_identity,
        }
        contact_artifact["models"]["embedding_contact_fusion"] = {
            "feature_spec": contact_spec.to_json(),
            "bootstrap_ensemble_fits": self._fits(8, 0.4),
        }
        contact_summary = {
            "status": "OPEN_DEVELOPMENT_EVALUATED_PROSPECTIVE_TEST_STILL_SEALED",
            "open_performance_gates_vs_cdr_length_only": {"all_passed": True},
            "selected_model_uncertainty_contract": {"gate_pass": True},
            "artifact_identity_contract": contact_identity,
            "prospective_test": {"labels_read": False, "label_files_opened": 0},
        }
        self._write_stage(
            "contact", self.contact_dir, contact_artifact, contact_summary
        )

    def _adapted_candidates(self) -> list[dict[str, object]]:
        rows = [dict(row) for row in self.candidates]
        return MOD.adapt_candidate_rows(rows, tuple(rows[0]), len(rows))

    def run(self, out_dir: Path | None = None, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "candidate_pool_path": self.pool,
            "support_csv_path": self.support_csv,
            "support_audit_path": self.support_audit,
            "support_receipt_path": self.support_receipt,
            "v4d_manifest_path": self.v4d_manifest,
            "v4d_audit_path": self.v4d_audit,
            "v4f_manifest_path": self.v4f_manifest,
            "v4f_audit_path": self.v4f_audit,
            "v4f_receipt_path": self.v4f_receipt,
            "v4g_reserve_path": self.v4g_reserve,
            "v4g_preregistration_path": self.v4g_preregistration,
            "v4g_receipt_path": self.v4g_receipt,
            "contact_receipt_path": self.contact_receipt,
            "contact_schema_path": self.contact_schema,
            "embedding_manifest_path": self.embedding_manifest,
            "embedding_summary_path": self.embedding_summary,
            "sequence_manifest_path": self.sequence_manifest,
            "base_dir": self.base_dir,
            "embedding_dir": self.embedding_dir,
            "contact_dir": self.contact_dir,
            "out_dir": out_dir or self.out_dir,
            "expected_count": len(self.candidates),
            "expected_v4d_count": 3,
            "expected_v4f_count": 2,
            "expected_reserve_parent_count": 1,
            "enforce_production_locks": False,
        }
        arguments.update(overrides)
        return MOD.run_pipeline(**arguments)


class DeploymentScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.fixture = DeploymentFixture(Path(self.temp.name))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_full_artifact_replay_routes_only_in_domain_to_exploitation(self) -> None:
        result = self.fixture.run()
        self.assertEqual(result["status"], "PASS_DEPLOYMENT_SCORES_ROUTED")
        self.assertEqual(result["routing"]["exploitation_count"], 1)
        self.assertEqual(result["routing"]["scored_prediction_count"], 4)
        rows = MOD.base.read_tsv(Path(result["scores"]))
        self.assertEqual(len(rows), 7)
        by_id = {row["candidate_id"]: row for row in rows}
        self.assertEqual(by_id["candidate-0"]["scoring_governance"], MOD.RESERVE_NO_SCORE)
        self.assertEqual(by_id["candidate-1"]["scoring_governance"], MOD.V4F_NO_SCORE)
        self.assertEqual(by_id["candidate-2"]["scoring_governance"], MOD.V4D_NO_SCORE)
        prediction_fields = (
            "base_prediction",
            "base_ensemble_uncertainty",
            "embedding_prediction",
            "embedding_ensemble_uncertainty",
            "contact_prediction",
            "contact_ensemble_uncertainty",
            "consensus_prediction",
            "ensemble_uncertainty",
            "model_disagreement",
        )
        for candidate_id in ("candidate-0", "candidate-1", "candidate-2"):
            self.assertTrue(all(by_id[candidate_id][field] == "" for field in prediction_fields))
        by_domain = {row["v4d_support_domain"]: row for row in rows}
        self.assertEqual(by_domain["NEAR_DOMAIN"]["deployment_route"], "UNCERTAINTY_DIVERSITY_DIRECT_DOCKING")
        self.assertEqual(by_domain["OOD"]["deployment_route"], "DIRECT_DOCKING_ONLY_OOD")
        self.assertEqual(by_domain["TRAIN_REFERENCE"]["deployment_route"], "TRAIN_REFERENCE_EXCLUDED")
        for row in rows:
            self.assertIn("ensemble_uncertainty", row)
            self.assertIn("model_disagreement", row)
            self.assertEqual(row["claim_boundary"], MOD.CLAIM_BOUNDARY)
        receipt = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(receipt["status"], "PASS_DEPLOYMENT_SCORING_HASH_CLOSURE")
        self.assertFalse(receipt["prospective_test_labels_read"])
        self.assertFalse(receipt["v4f_labels_read"])
        self.assertEqual(
            receipt["inputs"][str(Path(MOD.__file__).resolve())],
            MOD.sha256_file(Path(MOD.__file__)),
        )
        for path, digest in receipt["outputs"].items():
            self.assertEqual(MOD.sha256_file(Path(path)), digest)
        verification = MOD.verify_published_release(self.fixture.out_dir)
        self.assertEqual(verification["status"], "PASS_DEPLOYMENT_RELEASE_HASH_CLOSURE")
        self.assertEqual(verification["row_count"], 7)

    def test_failed_support_gate_blocks_in_domain_but_keeps_near_domain_route(self) -> None:
        self.fixture.set_support_gates(False)
        result = self.fixture.run(self.fixture.root / "support-fail-out")
        self.assertEqual(result["status"], "PASS_INFERENCE_ONLY_SCORES_EXPLOITATION_BLOCKED")
        rows = MOD.base.read_tsv(Path(result["scores"]))
        in_domain = [
            row
            for row in rows
            if row["v4d_support_domain"] == "IN_DOMAIN"
            and row["scoring_governance"] == MOD.SCORE_ALLOWED
        ]
        self.assertTrue(all(row["deployment_route"] == "EXPLOITATION_BLOCKED_SUPPORT_GATE" for row in in_domain))
        near = [
            row
            for row in rows
            if row["v4d_support_domain"] == "NEAR_DOMAIN"
            and row["scoring_governance"] == MOD.SCORE_ALLOWED
        ]
        self.assertTrue(all(row["deployment_route"] == "UNCERTAINTY_DIVERSITY_DIRECT_DOCKING" for row in near))

    def test_missing_artifacts_publishes_waiting_without_score_table(self) -> None:
        missing_root = self.fixture.root / "missing"
        result = self.fixture.run(
            missing_root / "out",
            base_dir=missing_root / "base",
            embedding_dir=missing_root / "embedding",
            contact_dir=missing_root / "contact",
        )
        self.assertEqual(result["status"], "WAITING_FROZEN_MODEL_ARTIFACTS")
        self.assertFalse((missing_root / "out" / MOD.SCORE_FILENAME).exists())
        receipt = json.loads((missing_root / "out" / MOD.RECEIPT_FILENAME).read_text())
        self.assertEqual(receipt["status"], "WAITING_NO_DEPLOYMENT_SCORES_PUBLISHED")
        summary = json.loads((missing_root / "out" / MOD.SUMMARY_FILENAME).read_text())
        self.assertEqual(summary["scoring_governance"]["reserve_parent_count"], 1)
        self.assertEqual(summary["scoring_governance"]["reserve_candidate_count"], 1)
        self.assertEqual(summary["model_scored_candidate_count"], 4)
        verification = MOD.verify_published_release(missing_root / "out")
        self.assertEqual(verification["status"], "PASS_WAITING_RELEASE_HASH_CLOSURE")

    def test_model_gate_failure_blocks_exploitation(self) -> None:
        summary_path = self.fixture.embedding_dir / MOD.STAGE_SUMMARIES["embedding"]
        summary = json.loads(summary_path.read_text())
        summary["status"] = "FAIL_OPEN_GATES_FROZEN_TEST_PREDICTIONS_UNEVALUATED"
        summary["open_gates_pass"] = False
        write_json(summary_path, summary)
        receipt_path = self.fixture.embedding_dir / MOD.STAGE_RECEIPTS["embedding"]
        receipt = json.loads(receipt_path.read_text())
        receipt["outputs"][str(summary_path.resolve())] = MOD.sha256_file(summary_path)
        write_json(receipt_path, receipt)
        result = self.fixture.run(self.fixture.root / "model-fail-out")
        rows = MOD.base.read_tsv(Path(result["scores"]))
        in_domain = [
            row
            for row in rows
            if row["v4d_support_domain"] == "IN_DOMAIN"
            and row["scoring_governance"] == MOD.SCORE_ALLOWED
        ]
        self.assertTrue(all(row["deployment_route"] == "EXPLOITATION_BLOCKED_MODEL_GATE" for row in in_domain))

    def test_all_three_governance_classes_are_removed_before_feature_replay(self) -> None:
        original = MOD.replay_predictions

        def checked_replay(candidates: list[dict[str, object]], *args: object, **kwargs: object):
            self.assertEqual(
                {row["candidate_id"] for row in candidates},
                {"candidate-3", "candidate-4", "candidate-5", "candidate-6"},
            )
            return original(candidates, *args, **kwargs)

        with mock.patch.object(MOD, "replay_predictions", side_effect=checked_replay):
            self.fixture.run(self.fixture.root / "matrix-exclusion-out")

    def test_support_tampering_is_rejected_by_hash_closure(self) -> None:
        self.fixture.support_csv.write_text(
            self.fixture.support_csv.read_text() + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(MOD.DeploymentScoringError, "sequence_support_receipt_verification_failed"):
            self.fixture.run(self.fixture.root / "tampered-support-out")

    def test_model_artifact_tampering_is_rejected_by_stage_receipt(self) -> None:
        artifact = self.fixture.base_dir / MOD.STAGE_ARTIFACTS["base"]
        artifact.write_text(artifact.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(MOD.DeploymentScoringError, "frozen_stage_verification_failed:base"):
            self.fixture.run(self.fixture.root / "tampered-artifact-out")

    def test_contact_identity_tamper_fails_even_with_updated_output_hash(self) -> None:
        artifact_path = self.fixture.contact_dir / MOD.STAGE_ARTIFACTS["contact"]
        artifact = json.loads(artifact_path.read_text())
        artifact["embedding_bank_identity_sha256"] = "0" * 64
        write_json(artifact_path, artifact)
        receipt_path = self.fixture.contact_dir / MOD.STAGE_RECEIPTS["contact"]
        receipt = json.loads(receipt_path.read_text())
        receipt["outputs"][str(artifact_path.resolve())] = MOD.sha256_file(artifact_path)
        write_json(receipt_path, receipt)
        with self.assertRaisesRegex(
            MOD.DeploymentScoringError, "contact_artifact_identity_contract_mismatch"
        ):
            self.fixture.run(self.fixture.root / "tampered-contact-identity-out")

    def test_public_interface_accepts_no_label_paths(self) -> None:
        parameters = set(inspect.signature(MOD.run_pipeline).parameters)
        forbidden = {
            name
            for name in parameters
            if any(token in name for token in ("label", "sealed", "test_result"))
        }
        self.assertEqual(forbidden, set())

    def test_published_summary_tamper_is_rejected(self) -> None:
        self.fixture.run()
        summary = self.fixture.out_dir / MOD.SUMMARY_FILENAME
        summary.write_text(summary.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
            MOD.DeploymentScoringError, "published_release_output_hash_mismatch"
        ):
            MOD.verify_published_release(self.fixture.out_dir)


if __name__ == "__main__":
    unittest.main()
