#!/usr/bin/env python3
from __future__ import annotations

import csv
import gzip
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("select_phase2_v3_p2_v1_2_emref_top8.py")
SPEC = importlib.util.spec_from_file_location("select_p2_v1_2_emref_top8", MODULE_PATH)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def atom_line(serial: int, chain: str, residue: int, x: float) -> str:
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{0.0:8.3f}{0.0:8.3f}  1.00 20.00           C  "
    )


def pdb_bytes(index: int, include_chain_b: bool = True) -> bytes:
    lines = [atom_line(1, "A", 1, float(index))]
    if include_chain_b:
        lines.append(atom_line(2, "B", 10, float(index) + 1.0))
    lines.append("END")
    return ("\n".join(lines) + "\n").encode("ascii")


def write_manifest(path: Path, candidate_id: str, workdir: Path, kind: str = "positive") -> None:
    if kind == "positive":
        row = {
            "calibration_name": candidate_id,
            "family": "151",
            "validation_role": "official_positive_control",
            "workdir": str(workdir),
        }
    else:
        row = {
            "mutant_name": candidate_id,
            "family": "20",
            "intended_role": "geometry perturbation control",
            "workdir": str(workdir),
        }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def make_case(
    root: Path,
    candidate_id: str = "case_01",
    scores: list[float | str | None] | None = None,
    gzip_indices: set[int] | None = None,
    missing_chain_b_index: int | None = None,
) -> tuple[Path, Path, list[dict[str, object]]]:
    scores = scores if scores is not None else [5.0, -2.0, -2.0, 1.0, 0.0, 4.0, 3.0, 2.0, 6.0, 7.0]
    gzip_indices = gzip_indices or set()
    workdir = root / candidate_id
    stage = workdir / "haddock3" / f"run_{candidate_id}" / "4_emref"
    stage.mkdir(parents=True)
    outputs: list[dict[str, object]] = []
    for index, score in enumerate(scores):
        file_name = f"emref_{index + 1}.pdb"
        coordinates = pdb_bytes(index, include_chain_b=index != missing_chain_b_index)
        if index in gzip_indices:
            (stage / f"{file_name}.gz").write_bytes(gzip.compress(coordinates, mtime=0))
        else:
            (stage / file_name).write_bytes(coordinates)
        outputs.append({"file_name": file_name, "score": score, "seed": 900 + index})
    (stage / "io.json").write_text(json.dumps({"output": outputs}), encoding="utf-8")
    manifest = root / f"{candidate_id}_manifest.csv"
    write_manifest(manifest, candidate_id, workdir)
    return manifest, workdir, outputs


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class EmrefTop8SelectionTests(unittest.TestCase):
    def test_ordering_gzip_hashes_exact_ranks_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, _workdir, outputs = make_case(root, gzip_indices={1, 8})
            output = root / "selected.csv"
            audit_path = root / "audit.json"
            first = MOD.build([manifest], output, audit_path, k=8, workspace_root=Path("/"))
            first_csv = output.read_bytes()
            first_audit = audit_path.read_bytes()
            second = MOD.build([manifest], output, audit_path, k=8, workspace_root=Path("/"))

            rows = read_csv(output)
            self.assertEqual([int(row["canonical_rank"]) for row in rows], list(range(1, 9)))
            self.assertEqual(
                [int(row["source_output_index"]) for row in rows],
                [1, 2, 4, 3, 7, 6, 5, 0],
            )
            self.assertEqual(rows[0]["source_pose_format"], "pdb.gz")
            self.assertTrue(rows[0]["source_pose_relpath"].endswith("emref_2.pdb.gz"))
            self.assertFalse(rows[0]["source_pose_relpath"].startswith("/"))
            self.assertNotEqual(
                rows[0]["source_pose_sha256"], rows[0]["decompressed_coordinate_sha256"]
            )
            self.assertEqual(rows[0]["vhh_chain_id"], "A")
            self.assertEqual(rows[0]["pvrig_chain_id"], "B")
            self.assertEqual(rows[0]["reuse_role"], "development_only")
            self.assertEqual(rows[0]["formal_eligible"], "false")
            self.assertEqual(first_csv, output.read_bytes())
            self.assertEqual(first_audit, audit_path.read_bytes())
            self.assertEqual(first["output_csv"]["sha256"], second["output_csv"]["sha256"])

            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertEqual(audit["cases"][0]["source_output_count"], len(outputs))
            self.assertEqual(len(audit["cases"][0]["outputs"]), len(outputs))
            self.assertEqual(audit["cases"][0]["selected_source_output_indices"], [1, 2, 4, 3, 7, 6, 5, 0])
            self.assertEqual(audit["formal_eligible"], False)

    def test_positive_and_mutant_manifest_aliases_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            positive_manifest, _workdir, _outputs = make_case(root, candidate_id="positive_case")
            mutant_manifest, mutant_workdir, _outputs = make_case(root, candidate_id="mutant_case")
            write_manifest(mutant_manifest, "mutant_case", mutant_workdir, kind="mutant")
            output = root / "selected.csv"
            audit = root / "audit.json"
            result = MOD.build(
                [mutant_manifest, positive_manifest], output, audit, workspace_root=Path("/")
            )
            rows = read_csv(output)
            self.assertEqual(result["case_count"], 2)
            self.assertEqual(result["selected_pose_count"], 16)
            self.assertEqual([rows[0]["candidate_id"], rows[8]["candidate_id"]], ["mutant_case", "positive_case"])
            self.assertEqual(rows[0]["role"], "geometry perturbation control")

    def test_invalid_score_missing_chain_and_duplicate_file_fail_closed(self) -> None:
        scenarios = ("invalid_score", "missing_chain", "duplicate_file")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scores: list[float | str | None] | None = None
                missing_chain: int | None = None
                if scenario == "invalid_score":
                    scores = [float("nan")] + [float(index) for index in range(1, 9)]
                if scenario == "missing_chain":
                    missing_chain = 3
                manifest, workdir, outputs = make_case(
                    root, scores=scores, missing_chain_b_index=missing_chain
                )
                if scenario == "duplicate_file":
                    outputs[1]["file_name"] = outputs[0]["file_name"]
                    io_path = next(workdir.glob("haddock3/run_*/4_emref/io.json"))
                    io_path.write_text(json.dumps({"output": outputs}), encoding="utf-8")
                with self.assertRaises(MOD.SelectionError):
                    MOD.build(
                        [manifest], root / "selected.csv", root / "audit.json", workspace_root=Path("/")
                    )
                self.assertFalse((root / "selected.csv").exists())
                self.assertFalse((root / "audit.json").exists())

    def test_fewer_than_k_does_not_backfill_from_downstream_stage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, workdir, _outputs = make_case(root, scores=[float(index) for index in range(7)])
            downstream = next(workdir.glob("haddock3/run_*")) / "6_seletopclusts"
            downstream.mkdir()
            for index in range(8):
                (downstream / f"cluster_1_model_{index + 1}.pdb").write_bytes(pdb_bytes(index))
            (downstream / "io.json").write_text(
                json.dumps({"output": [{"file_name": f"cluster_1_model_{i + 1}.pdb"} for i in range(8)]}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(MOD.SelectionError, "fewer than K=8"):
                MOD.build(
                    [manifest], root / "selected.csv", root / "audit.json", workspace_root=Path("/")
                )

    def test_multiple_emref_runs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, workdir, _outputs = make_case(root)
            source = next(workdir.glob("haddock3/run_*/4_emref/io.json"))
            second = workdir / "haddock3/run_duplicate/4_emref"
            second.mkdir(parents=True)
            (second / "io.json").write_bytes(source.read_bytes())
            with self.assertRaisesRegex(MOD.SelectionError, "exactly one"):
                MOD.build(
                    [manifest], root / "selected.csv", root / "audit.json", workspace_root=Path("/")
                )


if __name__ == "__main__":
    unittest.main()
