from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PKG = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"invalid_spec:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MATERIALIZER = load_module(
    "v212_graph_view_materializer_test",
    PKG / "src/materialize_train9849_graph_view_v1.py",
)
COLLECTOR = load_module(
    "v212_oof_collector_test",
    PKG / "src/collect_clean_attention_inner_oof_v1.py",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class GraphViewMaterializerTests(unittest.TestCase):
    def test_train9849_manifest_view_hardlinks_only_backing_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            teacher = root / "teacher.tsv"
            source_root = root / "source"
            source_graph = source_root / "graph_cache"
            source_graph.mkdir(parents=True)
            teacher_rows = [
                {"candidate_id": f"C{i:05d}", "sequence_sha256": f"{i:064x}"}
                for i in range(9849)
            ]
            source_rows = [
                {
                    "entity_id": f"C{i:05d}",
                    "sequence_sha256": f"{i:064x}",
                    "node_offset": str(i),
                }
                for i in range(10644)
            ]
            prepared_rows = [
                {
                    "candidate_id": f"C{i:05d}",
                    "sequence_sha256": f"{i:064x}",
                    "sequence": "ACDEFGHIK",
                }
                for i in range(10644)
            ]
            write_tsv(teacher, ["candidate_id", "sequence_sha256"], teacher_rows)
            write_tsv(source_graph / "graph_manifest_v2.tsv", list(source_rows[0]), source_rows)
            write_tsv(
                source_root / "canonical10644_label_free_graph_input_manifest_v1.tsv",
                list(prepared_rows[0]),
                prepared_rows,
            )
            (source_graph / "graph_cache_v2.npz").write_bytes(b"immutable-backing-arrays")
            (source_graph / "graph_cache_receipt_v2.json").write_text(
                json.dumps({"counts": {"edge_feature_dim": 11}}) + "\n",
                encoding="utf-8",
            )
            output = root / "view"
            receipt = MATERIALIZER.materialize(teacher, source_graph, output)
            self.assertEqual(receipt["status"], "PASS_TRAIN9849_LABEL_FREE_GRAPH_VIEW")
            self.assertEqual(
                (source_graph / "graph_cache_v2.npz").stat().st_ino,
                (output / "graph_cache/graph_cache_v2.npz").stat().st_ino,
            )
            _, view_rows = MATERIALIZER.read_tsv(output / "graph_cache/graph_manifest_v2.tsv")
            self.assertEqual(len(view_rows), 9849)
            self.assertEqual({row["entity_id"] for row in view_rows}, {row["candidate_id"] for row in teacher_rows})


class OofCollectorTests(unittest.TestCase):
    def test_collects_exact_five_fold_candidate_closure(self) -> None:
        prepared = PKG / "prepared"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contracts = root / "contracts"
            runs = root / "runs"
            contracts.mkdir()
            runs.mkdir()
            with (prepared / "train9849_teacher.tsv").open(newline="", encoding="utf-8") as handle:
                teacher_rows = list(csv.DictReader(handle, delimiter="\t"))
            by_id = {row["candidate_id"]: row for row in teacher_rows}
            with (prepared / "candidate_fold_assignment.tsv").open(newline="", encoding="utf-8") as handle:
                assignments = list(csv.DictReader(handle, delimiter="\t"))
            for fold in range(5):
                split_source = prepared / f"fold_{fold}_split.json"
                split_copy = contracts / split_source.name
                split_copy.write_bytes(split_source.read_bytes())
                contract = json.loads((prepared / f"fold_{fold}_contract.json").read_text(encoding="utf-8"))
                contract["split_manifest"] = {"path": str(split_copy), "sha256": sha256_file(split_copy)}
                contract_path = contracts / f"fold_{fold}_contract.json"
                contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                fold_rows = [row for row in assignments if int(row["fold_id"]) == fold]
                prediction_rows = []
                for assigned in fold_rows:
                    source = by_id[assigned["candidate_id"]]
                    r8, r9 = float(source["R_8X6B"]), float(source["R_9E6Y"])
                    prediction_rows.append(
                        {
                            "candidate_id": assigned["candidate_id"],
                            "sequence_sha256": assigned["sequence_sha256"],
                            "parent_framework_cluster": assigned["parent_framework_cluster"],
                            "fold_id": str(fold),
                            "seed": "43",
                            "target_R_8X6B": repr(r8),
                            "target_R_9E6Y": repr(r9),
                            "target_R_dual_min": repr(min(r8, r9)),
                            "prediction_R_8X6B": repr(r8),
                            "prediction_R_9E6Y": repr(r9),
                            "prediction_R_dual_min": repr(min(r8, r9)),
                        }
                    )
                fold_dir = runs / f"fold_{fold}"
                prediction_path = fold_dir / COLLECTOR.RUNNER.PREDICTION_NAME
                write_tsv(prediction_path, list(prediction_rows[0]), prediction_rows)
                result = {
                    "status": "PASS_V2_12_CLEAN_ATTENTION_INNER_OOF_FOLD_TRAINING",
                    "fold_id": fold,
                    "seed": 43,
                    "open_development_access_count": 0,
                    "frozen_test_access_count": 0,
                    "outputs": {COLLECTOR.RUNNER.PREDICTION_NAME: sha256_file(prediction_path)},
                }
                (fold_dir / COLLECTOR.RUNNER.RESULT_NAME).write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            output = root / "aggregate"
            receipt = COLLECTOR.collect(
                prepared / "train9849_teacher.tsv",
                prepared / "candidate_fold_assignment.tsv",
                contracts,
                runs,
                output,
            )
            self.assertEqual(receipt["status"], "PASS_CLEAN_ATTENTION_TRAIN9849_WHOLE_PARENT_OOF")
            self.assertEqual(receipt["counts"], {"rows": 9849, "parents": 54, "folds": 5, "seed": 43})
            with (output / COLLECTOR.OUTPUT_NAME).open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 9849)
            self.assertEqual(len({row["candidate_id"] for row in rows}), 9849)


if __name__ == "__main__":
    unittest.main()
