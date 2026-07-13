#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import torch

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import train_phase2_v2_3 as v23
import train_phase2_v3_p1_formal as formal


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def digest(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


class SyntheticFormalFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.sequences = ["ACDEF", "ACDGF", "ACDHF", "ACDIF", "ACDKF", "ACDMF"]
        self.target = "NPQRS"
        self.selection = root / "selection.csv"
        self.teacher = root / "teacher_train_dev.csv"
        self.contacts = root / "contacts_train_dev.jsonl"
        self.blinded = root / "formal_blinded.csv"
        self.cache = root / "cache/manifest.csv"
        self.cdr = root / "cdr.csv"
        self.target_fasta = root / "target.fasta"
        self.mapping = root / "target_mapping.csv"
        self.reconciliation = root / "reconciliation.csv"
        self.pdb8 = root / "8X6B.pdb"
        self.pdb9 = root / "9E6Y.pdb"
        self.interface8 = root / "interface8.csv"
        self.interface9 = root / "interface9.csv"
        self.checkpoint = root / "backbone.pt"
        self._write()

    def _write(self) -> None:
        split = ["train", "train", "train", "dev", "dev", "test"]
        parents = ["P_T", "P_T", "P_T", "P_D", "P_D", "P_X"]
        selection_rows: list[dict[str, object]] = []
        for index, (sequence, row_split, parent) in enumerate(zip(self.sequences, split, parents)):
            selection_rows.append(
                {
                    "candidate_id": f"C{index}",
                    "vhh_sequence": sequence,
                    "sequence_sha256": digest(sequence),
                    "parent_framework_cluster": parent,
                    "formal_split": row_split,
                    "generic_binding_prior": 0.1 + 0.1 * index,
                    "generic_binding_model": "meanpool_v3_full_cluster_safe_baseline",
                    "cheap_qc_score": 0.9 - 0.05 * index,
                    "model_uncertainty": 0.01 * index,
                    "parent_id": parent,
                    "target_patch_id": "A_CENTER",
                    "design_mode": "H3",
                }
            )
        write_csv(self.selection, selection_rows)
        write_csv(self.blinded, [selection_rows[-1]])

        teacher_rows: list[dict[str, object]] = []
        tiers = ["G5", "G3", "G1", "G4", "G2"]
        for index, tier in enumerate(tiers):
            row: dict[str, object] = {
                "candidate_id": f"C{index}",
                "sequence": self.sequences[index],
                "formal_split": split[index],
                "teacher_completeness": "COMPLETE",
                "provisional_stable_geometry_tier": tier,
            }
            row.update({field: float(index + offset / 10) for offset, field in enumerate(formal.GEOMETRY_FIELDS)})
            teacher_rows.append(row)
        write_csv(self.teacher, teacher_rows)
        with self.contacts.open("w", encoding="utf-8") as handle:
            for index in range(5):
                handle.write(
                    json.dumps(
                        {
                            "candidate_id": f"C{index}",
                            "formal_split": split[index],
                            "pair_frequencies": [
                                {"vhh_residue": "A:4:ALA", "pvrig_residue": "B:10:ASN", "frequency": 0.2 + index * 0.1}
                            ],
                        }
                    )
                    + "\n"
                )

        all_sequences = [*self.sequences, self.target]
        self.cache.parent.mkdir(parents=True)
        torch.manual_seed(101)
        payload = {digest(sequence): torch.randn(len(sequence), 6) for sequence in all_sequences}
        torch.save(payload, self.cache.parent / "shard.pt")
        write_csv(
            self.cache,
            [
                {
                    "sequence_sha256": digest(sequence),
                    "sequence_length": len(sequence),
                    "cached_length": len(sequence),
                    "truncation_policy": "full_length",
                    "shard_path": "shard.pt",
                    "shard_key": digest(sequence),
                }
                for sequence in all_sequences
            ],
        )
        write_csv(
            self.cdr,
            [
                {
                    "sequence_hash": digest(sequence),
                    "vhh_len": len(sequence),
                    "cdr_mask_json": json.dumps([0, 1, 2, 3, 0]),
                    "status": "exact_annotation",
                }
                for sequence in self.sequences
            ],
        )
        self.target_fasta.write_text(f">target\n{self.target}\n", encoding="utf-8")
        write_csv(
            self.mapping,
            [
                {
                    "in_model_domain": "yes",
                    "model_index_0based": index,
                    "aa": aa,
                    "target_weight": 1.0 if index == 0 else 0.0,
                }
                for index, aa in enumerate(self.target)
            ],
        )

        three = {"N": "ASN", "P": "PRO", "Q": "GLN", "R": "ARG", "S": "SER"}
        reconciliation_rows: list[dict[str, object]] = []
        for pdb_id, chain, start in (("8X6B", "B", 10), ("9E6Y", "A", 20)):
            for index, aa in enumerate(self.target):
                reconciliation_rows.append(
                    {
                        "pdb_id": pdb_id,
                        "pvrig_chain": chain,
                        "pdb_resseq": start + index,
                        "pdb_icode": "",
                        "pdb_resname": three[aa],
                        "pdb_aa": aa,
                        "uniprot_position": 39 + index,
                        "note": "",
                    }
                )
        write_csv(self.reconciliation, reconciliation_rows)
        self._write_pdb(self.pdb8, "B", 10, three)
        self._write_pdb(self.pdb9, "A", 20, three)
        interface_header = {
            "pdb_id": "8X6B", "pvrig_chain": "B", "pvrig_resseq": 10, "pvrig_icode": "",
            "min_heavy_atom_distance_a": 3.0,
        }
        write_csv(self.interface8, [interface_header])
        write_csv(self.interface9, [{**interface_header, "pdb_id": "9E6Y", "pvrig_chain": "A", "pvrig_resseq": 20}])

        backbone_cfg = v23.Config(
            d_model=8,
            esm_dim=6,
            contact_dim=4,
            layers=1,
            cross_layers=1,
            heads=2,
            dropout=0.0,
            max_vhh_len=16,
            max_antigen_len=16,
        )
        backbone = v23.CrossContactNetV23(backbone_cfg)
        torch.save({"cfg": asdict(backbone_cfg), "model": backbone.state_dict()}, self.checkpoint)

    def _write_pdb(self, path: Path, chain: str, start: int, three: dict[str, str]) -> None:
        lines = []
        for index, aa in enumerate(self.target):
            lines.append(
                f"ATOM  {index + 1:5d}  CA  {three[aa]:>3s} {chain}{start + index:4d}    "
                f"{index * 3.8:8.3f}{index * 0.5:8.3f}{index * -0.2:8.3f}  1.00{20 + index:6.2f}           C  "
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def config(self) -> formal.FormalTrainConfig:
        return formal.FormalTrainConfig(
            teacher_open_csv=str(self.teacher),
            contact_open_jsonl=str(self.contacts),
            formal_blinded_csv=str(self.blinded),
            selection_csv=str(self.selection),
            cache_manifest=str(self.cache),
            cdr_mask_csv=str(self.cdr),
            target_fasta=str(self.target_fasta),
            target_mapping_csv=str(self.mapping),
            reconciliation_csv=str(self.reconciliation),
            pdb_8x6b=str(self.pdb8),
            pdb_9e6y=str(self.pdb9),
            interface_8x6b_csv=str(self.interface8),
            interface_9e6y_csv=str(self.interface9),
            source_checkpoint=str(self.checkpoint),
            generic_replay_csv="",
            out_root=str(self.root / "runs"),
            seeds=(83,),
            epochs=2,
            batch_size=3,
            learning_rate=1e-3,
            early_stopping_patience=3,
            contact_dim=4,
            pooled_dim=5,
            hidden_dim=12,
            dropout=0.0,
            use_amp=False,
            device="cpu",
            expected_total_candidates=6,
            expected_train_candidates=3,
            expected_dev_candidates=2,
            expected_test_candidates=1,
            expected_train_parents=1,
            expected_dev_parents=1,
            expected_test_parents=1,
            expected_hotspot_residues=1,
        )


class FormalTrainerTest(unittest.TestCase):
    def test_synthetic_training_resume_is_deterministic_and_test_output_is_blind(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticFormalFixture(Path(directory))
            cfg = fixture.config()
            resumed_root = Path(directory) / "resumed"
            paused = formal.train_seed(cfg, 83, resumed_root, stop_after_epoch=1)
            self.assertEqual(paused["status"], "PAUSED_RESUMABLE")
            resumed = formal.train_seed(cfg, 83, resumed_root, resume=True)
            uninterrupted_root = Path(directory) / "uninterrupted"
            uninterrupted = formal.train_seed(cfg, 83, uninterrupted_root)
            self.assertEqual(resumed["status"], "PASS_FORMAL_TRAINING_COMPLETE")
            self.assertEqual(
                (resumed_root / "test_predictions.csv").read_text(),
                (uninterrupted_root / "test_predictions.csv").read_text(),
            )
            with (resumed_root / "test_predictions.csv").open() as handle:
                predictions = list(csv.DictReader(handle))
            self.assertEqual(len(predictions), 1)
            self.assertEqual(predictions[0]["formal_split"], "test")
            self.assertIn("sequence_sha256", predictions[0])
            self.assertFalse(any("true_" in column or "tier" in column.lower() and not column.startswith("predicted_") for column in predictions[0]))
            with (resumed_root / "control_predictions.csv").open() as handle:
                controls = list(csv.DictReader(handle))
            self.assertEqual(len(controls), 4)
            self.assertEqual(
                {row["control_type"] for row in controls},
                {"vhh_only", "hotspot_shuffle", "antigen_ablation", "target_permutation"},
            )
            summary = json.loads((resumed_root / "summary.json").read_text())
            self.assertIn("normalized", summary["dev_selection_policy"])
            self.assertEqual(summary["test_predictions_sha256"], uninterrupted["test_predictions_sha256"])
            with (resumed_root / "baseline_registry.csv").open() as handle:
                baseline = list(csv.DictReader(handle))
            self.assertEqual({row["formal_split"] for row in baseline}, {"dev", "test"})

    def test_blinded_file_rejects_teacher_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SyntheticFormalFixture(Path(directory))
            with fixture.blinded.open() as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["provisional_stable_geometry_tier"] = "G1"
            write_csv(fixture.blinded, rows)
            backbone_cfg, _ = formal.load_backbone_checkpoint(fixture.checkpoint)
            with self.assertRaisesRegex(ValueError, "forbidden teacher label"):
                formal.build_datasets(fixture.config(), backbone_cfg)

    def test_real_generic_replay_source_freezes_128_train_groups(self) -> None:
        cache = v23.ESM2Cache(EXP_DIR / "prepared/esm2_8m_v2_3_cache/manifest.csv", 320)
        cdr = v23.CDRMaskStore(EXP_DIR / "data_splits/vhh_cdr_type_masks_v2_3.csv")
        dataset = formal.GenericReplayDataset(
            EXP_DIR / "prepared/structure_contact_maps_v3_clustered.jsonl",
            cache,
            cdr,
            v23.Config(),
            128,
        )
        self.assertEqual(len(dataset), 128)
        self.assertEqual({row["source_split"] for row in dataset.rows}, {"train"})
        self.assertEqual(len({row["split_group_id"] for row in dataset.rows}), 128)


if __name__ == "__main__":
    unittest.main()
