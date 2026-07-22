from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/run_clean_attention_inner_oof_fold_v1.py"
V6_ROOT = ROOT.parent
MODEL_PATH = V6_ROOT / "v2_5_ortho_contact_pose_stack_v1_20260718/model/residue_model_v2_5_ortho.py"
TRAINER_PATH = V6_ROOT / "v2_5_ortho_contact_pose_stack_v1_20260718/trainer/train_v2_5_ortho_heads.py"
GRAPH_BUILDER_PATH = V6_ROOT / "residue_v2/src/build_residue_graph_cache_v2.py"


def import_module(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification and specification.loader
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


MOD = import_module("v211_full10644_clean_attention", SOURCE)
GRAPH = import_module("v211_graph_builder_fixture", GRAPH_BUILDER_PATH)


THREE = {
    "A": "ALA", "C": "CYS", "D": "ASP", "E": "GLU", "F": "PHE",
    "G": "GLY", "H": "HIS", "I": "ILE", "K": "LYS", "L": "LEU",
    "M": "MET", "N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG",
    "S": "SER", "T": "THR", "V": "VAL", "W": "TRP", "Y": "TYR",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_pdb(path: Path, sequence: str) -> None:
    lines, serial = [], 1
    for index, aa in enumerate(sequence, start=1):
        ca_x = 3.8 * (index - 1)
        for atom, xyz in {
            "N": (ca_x - 1.2, 0.4, 0.1),
            "CA": (ca_x, 0.0, 0.0),
            "C": (ca_x + 1.3, 0.3, -0.1),
        }.items():
            lines.append(
                f"ATOM  {serial:5d} {atom:>4s} {THREE[aa]:>3s} A{index:4d}    "
                f"{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{1.0:6.2f}{90.0:6.2f}          {atom[0]:>2s}\n"
            )
            serial += 1
    path.write_text("".join(lines) + "END\n", encoding="utf-8")


def target_graph(node_dim: int = 7, edge_dim: int = 26) -> dict[str, dict[str, torch.Tensor]]:
    result = {}
    for channel, (receptor, nodes) in enumerate((("8x6b", 4), ("9e6y", 5))):
        edges = []
        for index in range(nodes - 1):
            edges.extend(((index, index + 1), (index + 1, index)))
        features = torch.zeros((len(edges), edge_dim))
        features[:, 0] = 1.0
        result[receptor] = {
            "node_features": torch.arange(nodes*node_dim, dtype=torch.float32).reshape(nodes, node_dim)/100 + channel,
            "edge_index": torch.tensor(edges, dtype=torch.long).T.contiguous(),
            "edge_features": features,
            "interface_mask": torch.tensor([(index % 2) == 0 for index in range(nodes)]),
            "hotspot_mask": torch.tensor([index in {1, 2} for index in range(nodes)]),
        }
    return result


class Fixture:
    def __init__(self, root: Path):
        self.root = root
        self.training = root / "training.tsv"
        self.split = root / "split.json"
        self.graph_root = root / "label_free_bundle"
        self.graph_cache = self.graph_root / "graph_cache"
        self.target_pt = root / "target_graphs_v2.pt"
        self.target_receipt = root / "target_graph_receipt_v2.json"
        self.contract = root / "contract.json"
        self.output = root / "output"
        self.rows: list[dict[str, str]] = []
        self.write_all()

    def write_all(self) -> None:
        parents = ("P1", "P2", "P3", "P4")
        sequences = ("ACDEFG", "HIKLMN", "PQRSTV", "WYACDE", "FGHIKL", "MNPQRS", "TVWYAC", "DEFGHI")
        self.rows = []
        graphs = []
        monomer_dir = self.root / "monomers"
        monomer_dir.mkdir()
        for index, sequence in enumerate(sequences):
            candidate = f"C{index:02d}"
            parent = parents[index // 2]
            digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
            r8 = 0.2 + 0.05*index
            r9 = 0.25 + 0.03*index
            self.rows.append({
                "candidate_id": candidate,
                "sequence_sha256": digest,
                "sequence": sequence,
                "parent_framework_cluster": parent,
                "sample_weight": "1" if index % 2 == 0 else "0.8",
                "R_8X6B": str(r8),
                "R_9E6Y": str(r9),
                "R_dual_min": str(min(r8, r9)),
                "teacher_source": "AUDIT_ONLY_NOT_INPUT",
            })
            pdb = monomer_dir / f"{candidate}.pdb"
            write_pdb(pdb, sequence)
            graphs.append(GRAPH.build_graph_from_pdb(
                entity_id=candidate,
                sequence=sequence,
                sequence_digest=digest,
                monomer_path=pdb,
                region_index=[0, 1, 1, 2, 3, 3],
                expected_chain="A",
                expected_monomer_sha256=sha256(pdb),
            ))
        write_tsv(self.training, self.rows)
        train_parents, dev_parents = parents[:3], parents[3:]
        self.split.write_text(json.dumps({
            "split_id": "tiny_D1",
            "train_parents": list(train_parents),
            "score_parents": list(dev_parents),
            "frozen_test_parents": ["P5"],
            "train_parent_set_sha256": MOD._stable_set_hash(train_parents),
            "score_parent_set_sha256": MOD._stable_set_hash(dev_parents),
        }), encoding="utf-8")

        self.graph_root.mkdir()
        graph_receipt = GRAPH.materialize_graph_cache(graphs, self.graph_cache)
        with (self.graph_cache / "graph_manifest_v2.tsv").open(newline="", encoding="utf-8") as handle:
            graph_manifest = list(csv.DictReader(handle, delimiter="\t"))
        prepared_rows = [{
            "candidate_id": row["entity_id"],
            "sequence_sha256": row["sequence_sha256"],
            "monomer_sha256": row["monomer_sha256"],
        } for row in graph_manifest]
        prepared_path = self.graph_root / "canonical10644_label_free_graph_input_manifest_v1.tsv"
        write_tsv(prepared_path, prepared_rows)
        (self.graph_root / "PREPARE_RECEIPT.json").write_text(json.dumps({
            "outputs": {prepared_path.name: sha256(prepared_path)}
        }), encoding="utf-8")
        (self.graph_root / "MATERIALIZATION_RECEIPT.json").write_text(json.dumps({
            "status": "PASS_CANONICAL10644_LABEL_FREE_GRAPH_MATERIALIZED",
            "outputs": {
                "graph_cache_v2.npz": sha256(self.graph_cache / "graph_cache_v2.npz"),
                "graph_manifest_v2.tsv": sha256(self.graph_cache / "graph_manifest_v2.tsv"),
                "graph_cache_receipt_v2.json": sha256(self.graph_cache / "graph_cache_receipt_v2.json"),
            },
        }), encoding="utf-8")
        self.assert_graph_receipt = graph_receipt

        torch.save(target_graph(), self.target_pt)
        self.target_receipt.write_text(json.dumps({
            "status": "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
            "outputs": {self.target_pt.name: sha256(self.target_pt)},
            "sealed_boundary": {
                "candidate_docking_pose_files_opened": 0,
                "teacher_source_is_model_feature": False,
            },
        }), encoding="utf-8")
        self.contract.write_text(json.dumps({
            "schema_version": MOD.CONTRACT_SCHEMA,
            "status": "FROZEN_INNER_OOF_PRE_LAUNCH",
            "lane": MOD.LANE,
            "contact_supervision_enabled": False,
            "expected_counts": {"total": 8, "train": 6, "score": 2},
            "training_table": {"path": str(self.training), "sha256": sha256(self.training)},
            "split_manifest": {"path": str(self.split), "sha256": sha256(self.split)},
            "fixed_target_graph": {
                "receipt": {"path": str(self.target_receipt), "sha256": sha256(self.target_receipt)},
                "torch_artifact": {"path": str(self.target_pt), "sha256": sha256(self.target_pt)},
            },
            "ortho_model": {"path": str(MODEL_PATH), "sha256": sha256(MODEL_PATH)},
            "ortho_trainer": {"path": str(TRAINER_PATH), "sha256": sha256(TRAINER_PATH)},
            "fixed_hyperparameters": {},
            "task": {"fold_id": 0, "seed": 43},
        }), encoding="utf-8")

    def args(self) -> argparse.Namespace:
        return argparse.Namespace(
            contract=self.contract,
            graph_cache_dir=self.graph_cache,
            output_dir=self.output,
            device="cpu",
            seed=43,
            epochs=1,
            batch_size=2,
            eval_batch_size=2,
            gradient_accumulation=2,
            precision="fp32",
            learning_rate=1e-3,
            weight_decay=0.0,
            gradient_clip=1.0,
            graph_hidden_dim=128,
            dropout=0.0,
            receptor_weight=1.0,
            dual_weight=0.5,
            huber_beta=0.03,
            softmin_tau=0.02,
            backbone_kind="tiny",
            backbone_dtype="fp32",
            model_path=None,
            model_identity_file=None,
            expected_model_sha256=None,
            tiny_hidden_size=16,
            tiny_e2e=True,
        )


class Full10644CleanAttentionTests(unittest.TestCase):
    def test_tiny_e2e_is_pure_b_and_exact_min(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            result = MOD.train(fixture.args())
            self.assertEqual(result["status"], "PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_FOLD_TRAINING")
            self.assertEqual(result["split"]["train_rows"], 6)
            self.assertEqual(result["split"]["score_rows"], 2)
            self.assertEqual(result["training"]["optimizer_parameter_roles"]["contact"]["parameter_values"], 0)
            self.assertEqual(result["neural_input_firewall"]["m2_input_count"], 0)
            self.assertEqual(result["neural_input_firewall"]["contact_input_count"], 0)
            self.assertLessEqual(result["metrics"]["exact_min_max_abs_error"], 1e-7)
            self.assertIn("early_enrichment", result["metrics"])
            self.assertIn("primary_early_enrichment", result["metrics"])
            with (fixture.output / MOD.PREDICTION_NAME).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertAlmostEqual(
                    float(row["prediction_R_dual_min"]),
                    min(float(row["prediction_R_8X6B"]), float(row["prediction_R_9E6Y"])),
                    places=9,
                )

    def test_collator_batch_has_no_ids_m2_c2_or_contact(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            rows = MOD.load_rows(fixture.training, 8)
            split = MOD.load_split(fixture.split, rows, 6, 2)
            store = MOD.GraphCacheStore(fixture.graph_cache, rows, require_full_receipt=True)
            weights = {index: rows[index].sample_weight for index in split.train_indices}
            batch = MOD.CleanCollator(rows, MOD.TinyTokenizer(), store, weights)(split.train_indices[:2])
            self.assertEqual(set(batch), {
                "input_ids", "attention_mask", "residue_mask", "vhh_aa_index", "vhh_region_index",
                "vhh_confidence", "vhh_edge_index", "vhh_edge_features", "targets", "hierarchy_weights",
            })
            self.assertFalse(set(batch) & MOD.FORBIDDEN_NEURAL_INPUTS)
            _model, trainer = MOD.load_frozen_ortho_modules(MOD.load_contract(fixture.contract))
            targets = MOD.load_target_graphs(fixture.target_pt, store.edge_feature_dim, fixture.target_receipt)
            forward = trainer.neural_forward_kwargs(batch, targets)
            self.assertEqual(set(forward), set(trainer.NEURAL_REQUIRED_BATCH_FIELDS) | {"target_graphs"})

    def test_whole_parent_overlap_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            payload = json.loads(fixture.split.read_text())
            payload["score_parents"].append("P1")
            payload["score_parent_set_sha256"] = MOD._stable_set_hash(payload["score_parents"])
            fixture.split.write_text(json.dumps(payload))
            rows = MOD.load_rows(fixture.training, 8)
            with self.assertRaisesRegex(MOD.CleanAttentionError, "train_development_parent_overlap"):
                MOD.load_split(fixture.split, rows, 6, 2)

    def test_graph_prepared_triplet_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            prepared = fixture.graph_root / "canonical10644_label_free_graph_input_manifest_v1.tsv"
            fields, rows = MOD._read_tsv(prepared, "prepared")
            rows[0]["monomer_sha256"] = "f"*64
            write_tsv(prepared, rows)
            receipt = fixture.graph_root / "PREPARE_RECEIPT.json"
            receipt.write_text(json.dumps({"outputs": {prepared.name: sha256(prepared)}}))
            training = MOD.load_rows(fixture.training, 8)
            with self.assertRaisesRegex(MOD.CleanAttentionError, "prepared_graph_triplet_mismatch"):
                MOD.GraphCacheStore(fixture.graph_cache, training, require_full_receipt=True)

    def test_b_lane_has_no_contact_modules(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            contract = MOD.load_contract(fixture.contract)
            store = MOD.GraphCacheStore(fixture.graph_cache, MOD.load_rows(fixture.training, 8), require_full_receipt=True)
            targets = MOD.load_target_graphs(fixture.target_pt, store.edge_feature_dim, fixture.target_receipt)
            args = fixture.args()
            model, _tokenizer, loss, trainer, _identity = MOD.build_clean_model(args, contract, store.edge_feature_dim, 7)
            self.assertIsNone(model.head.contact_interaction)
            self.assertIsNone(model.head.contact_calibration)
            self.assertEqual(loss.marginal_weight, 0.0)
            self.assertEqual(loss.pair_weight, 0.0)
            _optimizer, audit = trainer.build_optimizer(model, trainer.OptimizerConfig())
            self.assertEqual(audit["contact"]["parameter_values"], 0)

    def test_perfect_ranking_has_expected_early_enrichment(self):
        candidate_ids = [f"C{index:02d}" for index in range(20)]
        parents = [f"P{index//5}" for index in range(20)]
        target = np.asarray([[float(index), float(index) + 0.25] for index in range(20)])
        evaluated = MOD.comprehensive_metrics(candidate_ids, parents, target, target.copy())
        primary = evaluated["primary_early_enrichment"]
        self.assertEqual(primary["recall_true_top20_at_budget20"], 1.0)
        self.assertEqual(primary["ef_true_top10_at_budget10"], 10.0)
        self.assertEqual(primary["binary_ndcg_true_top10_at_budget10"], 1.0)
        self.assertEqual(primary["within_parent_macro_recall_top20"], 1.0)



if __name__ == "__main__":
    unittest.main()
