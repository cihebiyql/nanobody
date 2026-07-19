from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


HERE = Path(__file__).resolve()
PACKAGE = HERE.parents[1]
SRC = PACKAGE / "src"
MODEL_SOURCE = HERE.parents[3] / "v2_5_ortho_contact_pose_stack_v1_20260718" / "model" / "residue_model_v2_5_ortho.py"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


exporter = load("v25_label_free_export_test", SRC / "export_outer_label_free_features_v1.py")
builder = load("v25_label_free_contract_test", SRC / "build_export_contract_v1.py")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rec(path: Path) -> dict[str, object]:
    return {"path": str(path.resolve()), "sha256": sha(path), "bytes": path.stat().st_size}


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def fixture(tmp_path: Path) -> tuple[Path, Path]:
    sequences = {"train": "ACDE", "score": "FGHI"}
    panel = tmp_path / "open_label_free_panel.tsv"
    panel_rows = [
        {
            "candidate_id": candidate, "sequence": sequence,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
            "parent_framework_cluster": "P0" if candidate == "train" else "P1",
            "outer_fold": 1 if candidate == "train" else 0,
        }
        for candidate, sequence in sequences.items()
    ]
    write_tsv(panel, list(exporter.PANEL_FIELDS), panel_rows)

    split = tmp_path / "outer_0.json"
    split.write_text(json.dumps({
        "schema_version": "test_open_split", "split_id": "outer0", "outer_fold": 0,
        "train_parents": ["P0"], "score_parents": ["P1"], "open_only": True,
        "v4_f_test32_access_count": 0,
    }))

    graph_dir = tmp_path / "graph_cache"
    graph_dir.mkdir()
    manifest_rows = []
    aa, region, confidence, edges, edge_features = [], [], [], [], []
    node_start = edge_start = 0
    for candidate, sequence in sequences.items():
        node_end = node_start + len(sequence)
        local_edges = [(index, index) for index in range(len(sequence))]
        edge_end = edge_start + len(local_edges)
        manifest_rows.append({
            "schema_version": "pvrig_v6_residue_graph_cache_v2", "entity_id": candidate,
            "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(), "monomer_sha256": "0" * 64,
            "chain": "A", "node_start": node_start, "node_end": node_end,
            "edge_start": edge_start, "edge_end": edge_end,
        })
        aa.extend([1, 2, 3, 4]); region.extend([0, 1, 2, 3]); confidence.extend([0.9] * len(sequence))
        edges.extend([(left + node_start, right + node_start) for left, right in local_edges])
        edge_features.extend([[0.1, 0.2] for _ in local_edges])
        node_start, edge_start = node_end, edge_end
    manifest = graph_dir / "graph_manifest_v2.tsv"
    write_tsv(manifest, list(manifest_rows[0]), manifest_rows)
    npz = graph_dir / "graph_cache_v2.npz"
    np.savez(
        npz, aa_index=np.asarray(aa, dtype=np.int64), region_index=np.asarray(region, dtype=np.int64),
        confidence=np.asarray(confidence, dtype=np.float32), edge_index=np.asarray(edges, dtype=np.int64).T,
        edge_features=np.asarray(edge_features, dtype=np.float32),
    )
    graph_receipt = graph_dir / "graph_cache_receipt_v2.json"
    graph_receipt.write_text(json.dumps({
        "schema_version": "pvrig_v6_residue_graph_cache_v2", "status": "PASS_LABEL_FREE_MONOMER_GRAPH_CACHE",
        "claim_boundary": "Label-free monomer graph; no teacher labels.",
        "counts": {"edge_feature_dim": 2},
        "outputs": {"graph_manifest_v2.tsv": sha(manifest), "graph_cache_v2.npz": sha(npz)},
    }))

    target_graphs = {}
    for shift, receptor in enumerate(("8x6b", "9e6y")):
        target_graphs[receptor] = {
            "node_features": torch.arange(18, dtype=torch.float32).reshape(3, 6) / 20 + shift,
            "edge_index": torch.tensor([[0, 1, 2], [0, 1, 2]], dtype=torch.long),
            "edge_features": torch.tensor([[0.2, 0.3], [0.1, 0.4], [0.3, 0.2]], dtype=torch.float32),
            "interface_mask": torch.tensor([1, 1, 0], dtype=torch.bool),
            "hotspot_mask": torch.tensor([1, 0, 0], dtype=torch.bool),
        }
    target_path = tmp_path / "fixed_target_graph.pt"
    torch.save({"target_graphs": target_graphs}, target_path)

    model_module = exporter.load_model_module(MODEL_SOURCE)
    backbone_seed = 777
    refit_records = []
    rows = exporter.load_panel(panel)
    graph_store = exporter.LabelFreeGraphStore(graph_dir, {
        "graph_manifest_v2.tsv": rec(manifest), "graph_cache_receipt_v2.json": rec(graph_receipt),
        "graph_cache_v2.npz": rec(npz),
    }, rows)
    score_rows = [row for row in rows if row.candidate_id == "score"]
    for seed in exporter.SEEDS:
        torch.manual_seed(seed)
        backbone = exporter.TinyBackbone(12, backbone_seed)
        config = model_module.ResidueV25OrthoConfig(
            backbone_hidden_size=12, target_node_dim=6, edge_feature_dim=2,
            graph_hidden_dim=128, dropout=0.25, enable_contact_evidence=True,
            contact_encoder_gradient="shared",
        )
        model = model_module.OrthogonalResidueSurrogate(backbone, model_module.OrthogonalTargetHead(config))
        checkpoint_dir = tmp_path / f"outer_refit_{seed}"
        checkpoint_dir.mkdir()
        checkpoint = checkpoint_dir / "neural_head.pt"
        torch.save({
            "schema_version": "pvrig_v2_5_ortho_real_head_checkpoint_v1", "lane": exporter.LANE,
            "source_split_id": "outer0",
            "head_state": {name: value.detach().clone() for name, value in model.state_dict().items() if name.startswith("head.")},
        }, checkpoint)
        model.eval()
        batch = exporter.collate(score_rows, exporter.TinyTokenizer(), graph_store)
        with torch.no_grad():
            output = model(
                input_ids=batch["input_ids"], attention_mask=batch["attention_mask"], residue_mask=batch["residue_mask"],
                vhh_aa_index=batch["vhh_aa_index"], vhh_region_index=batch["vhh_region_index"],
                vhh_confidence=batch["vhh_confidence"], vhh_edge_index=batch["vhh_edge_index"],
                vhh_edge_features=batch["vhh_edge_features"], target_graphs=target_graphs,
            )
        source_predictions = checkpoint_dir / "score_predictions_no_metrics.tsv"
        write_tsv(source_predictions, list(exporter.SOURCE_PREDICTION_FIELDS), [{
            "candidate_id": "score", "neural_R8": float(output["receptor_predictions"][0, 0]),
            "neural_R9": float(output["receptor_predictions"][0, 1]), "neural_Rdual": float(output["exact_min_dual"][0]),
            "contact_score_R8": float(output["contact_composite"][0, 0]),
            "contact_score_R9": float(output["contact_composite"][0, 1]),
        }])
        result = checkpoint_dir / "RESULT.json"
        result.write_text(json.dumps({
            "status": "PASS_FORMAL_OUTER_REFIT", "phase": "outer", "outer_fold": 0, "formal_seed": seed,
            "lane": {"variant": exporter.LANE}, "formal_hparam_id": "H0",
            "source_split": {"split_id": "outer0"}, "prediction_metrics_access_count": 0,
            "v4_f_test32_access_count": 0, "neural_input_firewall": {"M2_126D_ID_pose_inputs": 0},
            "model_contract": {"contact_feedback_to_scalar": False, "config": {
                "enable_contact_evidence": True, "contact_encoder_gradient": "shared",
                "graph_hidden_dim": 128, "dropout": 0.25, "backbone_hidden_size": 12,
                "edge_feature_dim": 2, "target_node_dim": 6,
            }},
            "artifacts": {
                "neural_head": {"path": checkpoint.name, "sha256": sha(checkpoint)},
                "predictions_no_metrics": {"path": source_predictions.name, "sha256": sha(source_predictions), "rows": 1},
            },
        }))
        refit_records.append({
            "seed": seed, "result_receipt": rec(result), "checkpoint": rec(checkpoint),
            "source_predictions_no_metrics": {**rec(source_predictions), "rows": 1},
            "formal_hparam_id": "H0", "source_split_id": "outer0",
        })

    contract = tmp_path / "contract.json"
    contract.write_text(json.dumps({
        "schema_version": exporter.SCHEMA, "status": "FROZEN_LABEL_FREE_EXPORT_CONTRACT",
        "outer_fold": 0, "lane": exporter.LANE, "seeds": list(exporter.SEEDS),
        "backbone": {"kind": "tiny_test_only", "test_fixture": True, "hidden_size": 12, "initialization_seed": backbone_seed},
        "inputs": {
            "label_free_panel": rec(panel),
            "graph_cache": {"path": str(graph_dir.resolve()), "files": {
                "graph_manifest_v2.tsv": rec(manifest), "graph_cache_receipt_v2.json": rec(graph_receipt),
                "graph_cache_v2.npz": rec(npz),
            }},
            "target_graph": rec(target_path), "model_source": rec(MODEL_SOURCE), "split_manifest": rec(split),
        },
        "outer_refits": refit_records, "replay_atol": 1e-6,
        "pair_summary_feature_scope": "FUTURE_VERSION_DIAGNOSTIC_ONLY_NOT_CURRENT_V2_5_SELECTION",
        "current_v2_5_primary_contact_fields": ["contact_score_R8", "contact_score_R9"],
        "teacher_metric_files_read": 0, "v4_f_test32_access_count": 0,
    }))
    return contract, panel


class ExportTests(unittest.TestCase):
    def test_contract_builder_closes_three_outer_refits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source_contract, panel = fixture(tmp_path)
            source = json.loads(source_contract.read_text())
            model_dir = tmp_path / "model"
            model_dir.mkdir()
            identity = tmp_path / "model_identity.json"
            identity.write_text('{"test":true}\n')
            output = tmp_path / "built_contract.json"
            argv = [
                "--outer-fold", "0", "--label-free-panel", str(panel),
                "--graph-cache-dir", source["inputs"]["graph_cache"]["path"],
                "--target-graph-pt", source["inputs"]["target_graph"]["path"],
                "--model-source", str(MODEL_SOURCE), "--model-path", str(model_dir),
                "--model-identity-file", str(identity), "--expected-model-identity-sha256", sha(identity),
                "--split-manifest", source["inputs"]["split_manifest"]["path"],
                "--output-json", str(output),
            ]
            for refit in source["outer_refits"]:
                argv.extend(["--outer-refit", f'{refit["seed"]}:{Path(refit["result_receipt"]["path"]).parent}'])
            self.assertEqual(builder.main(argv), 0)
            built = json.loads(output.read_text())
            self.assertEqual(tuple(item["seed"] for item in built["outer_refits"]), exporter.SEEDS)
            self.assertEqual(built["teacher_metric_files_read"], 0)

    def test_end_to_end_label_free_replay_exports_14d_and_ensemble(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            contract, _ = fixture(tmp_path)
            output = tmp_path / "published"
            self.assertEqual(exporter.main(["--contract-json", str(contract), "--output-dir", str(output), "--device", "cpu", "--batch-size", "1"]), 0)
            receipt = json.loads((output / "EXPORT_RECEIPT.json").read_text())
            self.assertEqual(receipt["status"], "PASS_LABEL_FREE_OUTER_CONTACT_REPLAY")
            self.assertEqual(receipt["pair_summary_dimensions"], 14)
            self.assertEqual((receipt["seed_rows"], receipt["ensemble_rows"]), (3, 1))
            with (output / "OUTER_TEST_SEED_FEATURES.tsv").open() as handle:
                seed_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(seed_rows), 3)
            self.assertTrue(set(exporter.PAIR_FEATURES) <= set(seed_rows[0]))
            with (output / "OUTER_TEST_ENSEMBLE_FEATURES.tsv").open() as handle:
                ensemble = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(ensemble), 1)
            self.assertTrue(all(f"{name}_mean" in ensemble[0] and f"{name}_std" in ensemble[0] for name in exporter.PAIR_FEATURES))
            self.assertGreaterEqual(float(ensemble[0]["neural_Rdual_std"]), 0.0)

    def test_panel_with_teacher_column_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            _, panel = fixture(tmp_path)
            with panel.open() as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            for row in rows:
                row["R_dual_min"] = "0.5"
            write_tsv(panel, list(exporter.PANEL_FIELDS) + ["R_dual_min"], rows)
            with self.assertRaisesRegex(exporter.ExportError, "label_free_panel_fields_not_exact"):
                exporter.load_panel(panel)

    def test_checkpoint_hash_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            contract, _ = fixture(tmp_path)
            payload = json.loads(contract.read_text())
            checkpoint = Path(payload["outer_refits"][0]["checkpoint"]["path"])
            checkpoint.write_bytes(checkpoint.read_bytes() + b"mutation")
            with self.assertRaisesRegex(exporter.ExportError, "checkpoint_43_bytes"):
                exporter.main(["--contract-json", str(contract), "--output-dir", str(tmp_path / "out"), "--device", "cpu"])

    def test_pair_summary_scope_cannot_be_promoted_in_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            contract, _ = fixture(tmp_path)
            payload = json.loads(contract.read_text())
            payload["pair_summary_feature_scope"] = "CURRENT_PRIMARY"
            contract.write_text(json.dumps(payload))
            with self.assertRaisesRegex(exporter.ExportError, "pair_feature_scope"):
                exporter.main(["--contract-json", str(contract), "--output-dir", str(tmp_path / "out"), "--device", "cpu"])

    def test_builder_rejects_sealed_path(self) -> None:
        with self.assertRaisesRegex(builder.ContractError, "sealed_path_forbidden"):
            builder.reject_sealed_path(Path("/tmp/V4-F/test32.tsv"))

    def test_source_prediction_schema_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pred.tsv"
            write_tsv(path, list(exporter.SOURCE_PREDICTION_FIELDS) + ["truth_Rdual"], [{
                "candidate_id": "x", "neural_R8": 0, "neural_R9": 0, "neural_Rdual": 0,
                "contact_score_R8": 0, "contact_score_R9": 0, "truth_Rdual": 1,
            }])
            with self.assertRaisesRegex(exporter.ExportError, "source_prediction_fields"):
                exporter.source_predictions(path)


if __name__ == "__main__":
    unittest.main()
