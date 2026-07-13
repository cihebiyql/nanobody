#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("process_phase2_v3_p2_dual_docking_pilot.py")
SPEC = importlib.util.spec_from_file_location("p2_dual_postprocess", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, chain: str, residue: int, x: float = 0.0) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C  "
    )


class DualDockingPostprocessTests(unittest.TestCase):
    def test_alignment_pair_maps_use_pose_chain_b_and_23_unique_hotspots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for source in MOD.RECEPTORS:
                for target in MOD.RECEPTORS:
                    path = Path(tmp) / f"{source}_{target}.csv"
                    self.assertEqual(MOD.write_alignment_pair_map(source, target, path), 23)
                    rows = MOD.read_csv(path)
                    self.assertEqual(len(rows), 23)
                    self.assertEqual(len({row["mobile_ref"] for row in rows}), 23)
                    self.assertTrue(all(row["mobile_ref"].startswith("B:") for row in rows))
                    target_chain = str(MOD.RECEPTORS[target]["pvrig_chain"])
                    self.assertTrue(all(row["reference_ref"].startswith(f"{target_chain}:") for row in rows))

    def test_cross_conformer_number_map_contains_all_common_uniprot_residues(self) -> None:
        reconciliation = MOD.parse_reconciliation()
        common = set(reconciliation["8X6B"]) & set(reconciliation["9E6Y"])
        self.assertGreaterEqual(len(common), 100)
        self.assertEqual(len(MOD.residue_number_map("8x6b", "9e6y")), len(common))
        self.assertEqual(len(MOD.residue_number_map("9e6y", "8x6b")), len(common))

    def test_remap_changes_only_receptor_residue_ids(self) -> None:
        mapping = MOD.residue_number_map("8x6b", "9e6y")
        (source_number, source_icode), (target_number, target_icode) = next(iter(mapping.items()))
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.pdb"
            destination = Path(tmp) / "destination.pdb"
            source.write_text(
                "\n".join(
                    [
                        atom_line(1, "A", 7, 1.0),
                        atom_line(2, "B", source_number, 2.0),
                        atom_line(3, "B", 999, 3.0),
                        "TER",
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            evidence = MOD.remap_pose_receptor_numbering(
                source, destination, "8x6b", "9e6y"
            )
            lines = destination.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0][21], "A")
            self.assertEqual(int(lines[0][22:26]), 7)
            self.assertEqual(lines[1][21], "B")
            self.assertEqual(int(lines[1][22:26]), target_number)
            self.assertEqual(lines[1][26].strip(), target_icode)
            self.assertLess(int(lines[2][22:26]), 0)
            self.assertEqual(evidence["observed_receptor_residues"], 2)
            self.assertEqual(evidence["remapped_receptor_residues"], 1)
            self.assertEqual(evidence["unmapped_receptor_residues"], 1)

    def test_contacts_are_mapped_to_canonical_uniprot_positions(self) -> None:
        canonical = MOD.native_to_uniprot_map("9e6y")
        (native_number, _icode), uniprot = next(iter(canonical.items()))
        with tempfile.TemporaryDirectory() as tmp:
            pose = Path(tmp) / "pose.pdb"
            pose.write_text(
                "\n".join(
                    [
                        atom_line(1, "A", 7, 0.0),
                        atom_line(2, "B", native_number, 3.0),
                        "TER",
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            rows = MOD.canonical_contact_rows(pose, "cluster_1_model_1", "9e6y")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["pvrig_uniprot_position"], uniprot)
            self.assertEqual(rows[0]["vhh_resseq"], 7)

    def test_postprocess_marker_pins_runtime_inputs_poses_and_every_scored_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sync_root = root / "sync"
            workdir = root / "post" / "P2PILOT_001__8X6B__main"
            run_dir = sync_root / "runs/P2PILOT_001__8X6B__main/run_P2PILOT_001__8X6B__main"
            selected_dir = run_dir / "6_seletopclusts"
            selected_dir.mkdir(parents=True)
            selected = []
            for rank, model in enumerate(("cluster_1_model_1", "cluster_2_model_1"), 1):
                path = selected_dir / f"{model}.pdb.gz"
                path.write_bytes(f"pose-{rank}\n".encode())
                selected.append((model, path, rank))

            row = {
                "run_id": "P2PILOT_001__8X6B__main",
                "pilot_id": "P2PILOT_001",
                "source_candidate_id": "candidate_1",
                "receptor_id": "8X6B",
                "seed_role": "main",
                "completion_relpath": "runs/P2PILOT_001__8X6B__main/P2PILOT_001__8X6B__main.complete.json",
                "config_sha256": "c" * 64,
                "monomer_sha256": "m" * 64,
                "receptor_sha256": "r" * 64,
            }
            docking_completion = sync_root / row["completion_relpath"]
            docking_completion.parent.mkdir(parents=True, exist_ok=True)
            docking_completion.write_text(
                json.dumps(
                    {
                        "schema_version": "phase2_v3_p2_pilot64_run_completion_v1_1",
                        "protocol_id": MOD.PROTOCOL_ID,
                        "status": "PASS_DOCKING_OUTPUT_COMPLETE",
                        "run_id": row["run_id"],
                        "pilot_id": row["pilot_id"],
                        "source_candidate_id": row["source_candidate_id"],
                        "receptor_id": row["receptor_id"],
                        "seed_role": row["seed_role"],
                        "pose_count": 2,
                        "cluster_count": 2,
                    }
                ),
                encoding="utf-8",
            )
            for path in MOD.postprocess_artifact_paths(workdir, row["run_id"]).values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"artifact:{path.name}\n", encoding="utf-8")
            evidence = {
                "selected_models": 2,
                "pose_clusters": 2,
                "consensus_rows": 2,
                "classification_8x6b_rows": 2,
                "classification_9e6y_rows": 2,
                "mechanism_8x6b_rows": 2,
                "mechanism_9e6y_rows": 2,
                "canonical_contact_pose_rows": 2,
                "canonical_contact_pair_rows": 4,
                "contact_failures": 0,
                "complete": True,
            }
            marker = MOD.build_postprocess_marker(
                row,
                sync_root,
                workdir,
                run_dir,
                selected,
                evidence,
                "f" * 64,
            )
            self.assertEqual(marker["schema_version"], "phase2_v3_p2_dual_docking_run_postprocess_v1_1")
            self.assertEqual(marker["protocol_id"], MOD.PROTOCOL_ID)
            self.assertEqual(marker["run_manifest_sha256"], "f" * 64)
            self.assertEqual(marker["docking_completion"]["sha256"], MOD.sha256_file(docking_completion))
            self.assertEqual(marker["input_sha256"]["config"], "c" * 64)
            self.assertEqual(marker["counts"], {key: evidence[key] for key in MOD.POSTPROCESS_COUNT_FIELDS})
            self.assertEqual(
                [item["filename"] for item in marker["selected_pose_files"]],
                ["cluster_1_model_1.pdb.gz", "cluster_2_model_1.pdb.gz"],
            )
            self.assertTrue(all(item["sha256"] for item in marker["selected_pose_files"]))
            self.assertEqual(set(marker["artifacts"]), set(MOD.POSTPROCESS_ARTIFACT_KEYS))
            self.assertTrue(all(item["sha256"] for item in marker["artifacts"].values()))
            self.assertEqual(set(marker["toolchain_sha256"]), set(MOD.POSTPROCESS_TOOLCHAIN_PATHS))
            self.assertEqual(set(marker["reference_sha256"]), set(MOD.POSTPROCESS_REFERENCE_PATHS))

            marker_path = workdir / "postprocess.complete.json"
            self.assertFalse(MOD.postprocess_marker_matches(marker_path, marker))
            marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
            self.assertTrue(MOD.postprocess_marker_matches(marker_path, marker))

            selected[0][1].write_bytes(b"pose-drift\n")
            drifted = MOD.build_postprocess_marker(
                row,
                sync_root,
                workdir,
                run_dir,
                selected,
                evidence,
                "f" * 64,
            )
            self.assertFalse(MOD.postprocess_marker_matches(marker_path, drifted))


if __name__ == "__main__":
    unittest.main()
