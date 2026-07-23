from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "verify_c2_refined_top7500_publication_v1.py"
SPEC = importlib.util.spec_from_file_location("publication_verifier", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seqsha(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)


def write_sums(path: Path, files: list[Path]) -> None:
    path.write_text("".join(f"{sha(item)}  {item.name}\n" for item in files), encoding="utf-8")


class PublicationVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fixture(self) -> argparse.Namespace:
        assets = {}
        for role in ("coarse_code", "vendor_adapter", "model_artifact", "target_npz", "target_pdb8", "target_pdb9"):
            path = self.root / f"{role}.bin"; path.write_bytes(role.encode())
            assets[role] = (path, sha(path))

        stage_rows = []
        structure_rows = []
        for index in range(4):
            candidate = f"C{index}"
            sequence = "A" * (100 + index)
            pdb = self.root / "pdb" / f"{candidate}.pdb"
            pdb.parent.mkdir(exist_ok=True)
            pdb.write_text(f"ATOM      1  CA  ALA H   1       {index:6.3f}   0.000   0.000  1.00 20.00           C\n")
            stage_rows.append({
                "candidate_id": candidate, "sequence": sequence, "sequence_sha256": seqsha(sequence),
                "parent_framework_cluster": f"P{index % 2}", "four_model_ensemble_utility": str(1-index/10),
                "l1_utility": ".9", "b_utility": ".8", "s0_utility": ".7", "m2_utility": ".6",
                "tnp_review_tier": "CLEAR", "cdr3": "AAA", "target_patch_id": "A", "design_method": "X",
            })
            structure_rows.append({
                "candidate_id": candidate, "sequence_sha256": seqsha(sequence),
                "parent_framework_cluster": f"P{index % 2}", "monomer_path": str(pdb.resolve()),
                "monomer_sha256": sha(pdb), "cdr1_range": "1-2", "cdr2_range": "3-4", "cdr3_range": "5-6",
            })

        prelim = self.root / "four_model_preliminary_top7500_v1"; prelim.mkdir()
        stage = prelim / "STAGE1_TOP30000_FOR_C2.tsv"; write_tsv(stage, stage_rows)
        stage_receipt = {
            "status": MODULE.STAGE_STATUS, "stage1_rows": 4,
            "outputs": {stage.name: sha(stage)}, "docking_truth_access_count": 0,
            "experimental_label_access_count": 0,
        }
        (prelim / "RUN_RECEIPT.json").write_text(json.dumps(stage_receipt))

        staging = self.root / "nbb2_staging_full150k_v1"; staging.mkdir()
        structure = staging / "top150k_m2_structure_manifest_v1.tsv"; write_tsv(structure, structure_rows)
        graph = staging / "top150k_graph_structure_manifest_v1.tsv"; write_tsv(graph, [{"candidate_id":"C0"}])
        audit = staging / "top150k_archive_audit_v1.tsv"; write_tsv(audit, [{"archive_path":"a"}])
        staging_receipt = {
            "status": MODULE.STAGING_STATUS, "counts": {"candidates": 4},
            "outputs": {path.name: sha(path) for path in (structure, graph, audit)},
            "invariants": {"candidate_docking_pose_files_opened": 0, "geometry_label_columns_read": 0},
        }
        (staging / "top150k_nbb2_staging_receipt_v1.json").write_text(json.dumps(staging_receipt))

        plan_root = self.root / "c2_top30k_shard_plan_v1"; (plan_root / "manifests").mkdir(parents=True)
        shards = []
        raw_root = self.root / "c2_top30k_shard_outputs_v1"
        raw_names = [name[4:] for name in MODULE.EXPECTED_C2_FEATURES]
        raw_names.insert(0, "8x6b__pose_count"); raw_names.insert(7, "8x6b__top20_score_entropy")
        split = len([name for name in raw_names if name.startswith("8x6b")])
        raw_names.insert(split, "9e6y__pose_count")
        raw_names.insert(split + 7, "9e6y__top20_score_entropy")
        self.assertEqual(len(raw_names), 36)
        observed_shards = []
        for shard_index, selected in enumerate((range(0, 2), range(2, 4))):
            shard_id = f"shard_{shard_index:03d}"
            manifest_rows = []
            for index in selected:
                source, struct = stage_rows[index], structure_rows[index]
                manifest_rows.append({
                    "candidate_id": source["candidate_id"], "sequence_sha256": source["sequence_sha256"],
                    "parent_framework_cluster": source["parent_framework_cluster"],
                    "monomer_pdb": struct["monomer_path"], "monomer_sha256": struct["monomer_sha256"],
                    "cdr1_range": "1-2", "cdr2_range": "3-4", "cdr3_range": "5-6", "claim_boundary": "label-free",
                })
            manifest = plan_root / "manifests" / f"{shard_id}.tsv"; write_tsv(manifest, manifest_rows)
            ids = [row["candidate_id"] for row in manifest_rows]
            shards.append({"shard_id": shard_id, "relative_path": f"manifests/{shard_id}.tsv",
                           "sha256": sha(manifest), "rows": 2,
                           "ordered_candidate_id_sha256": MODULE.ordered_id_sha256(ids)})
            out = raw_root / shard_id; out.mkdir(parents=True)
            raw_rows = [{"candidate_id": row["candidate_id"], "monomer_sha256": row["monomer_sha256"],
                         "feature_schema": MODULE.RAW_SCHEMA, **{name:"0.5" for name in raw_names}}
                        for row in manifest_rows]
            raw_table = out / "coarse_pose_features_36d.tsv"; write_tsv(raw_table, raw_rows)
            raw_receipt = {
                "schema_version": MODULE.RAW_RECEIPT_SCHEMA, "status": MODULE.RAW_RECEIPT_STATUS,
                "candidate_count": 2, "feature_count": 36, "pose_count_per_receptor": 300,
                "all_features_finite": True,
                "sealed_boundary": {"candidate_docking_pose_files_opened":0,"teacher_label_files_opened":0,"v4_f_files_opened":0},
                "inputs": {"candidate_manifest":{"path":str(manifest.resolve()),"sha256":sha(manifest)},
                           **{role:{"path":str(path.resolve()),"sha256":digest}
                              for role,(path,digest) in (("target_npz",assets["target_npz"]),("target_pdb8",assets["target_pdb8"]),("target_pdb9",assets["target_pdb9"]))}},
                "outputs": {str(raw_table.resolve()): sha(raw_table)},
            }
            raw_receipt_path = out / "FEATURE_RECEIPT.json"; raw_receipt_path.write_text(json.dumps(raw_receipt))
            observed_shards.append({"shard_id":shard_id,"rows":2,"feature_sha256":sha(raw_table),"receipt_sha256":sha(raw_receipt_path)})
        plan = {
            "schema_version": MODULE.PLAN_SCHEMA, "status": MODULE.PLAN_STATUS,
            "counts":{"rows":4,"shards":2},
            "inputs":{"preliminary_sha256":sha(stage),"structure_manifest_sha256":sha(structure)},
            "candidate_set_sha256":MODULE.ordered_id_sha256(sorted(row["candidate_id"] for row in stage_rows)),
            "ordered_candidate_id_sha256":MODULE.ordered_id_sha256([row["candidate_id"] for row in stage_rows]),
            "shards":shards,
            "invariants":{"truth_columns_read":0,"candidate_docking_pose_files_opened":0},
        }
        plan_path = plan_root / "SHARD_PLAN.json"; plan_path.write_text(json.dumps(plan))

        c2_root = self.root / "c2_top30k_32d_v1"; c2_root.mkdir()
        c2_rows = [{"candidate_id":row["candidate_id"],"sequence_sha256":row["sequence_sha256"],
                    "parent_framework_cluster":row["parent_framework_cluster"],
                    **{name:"0.5" for name in MODULE.EXPECTED_C2_FEATURES}} for row in stage_rows]
        c2_table = c2_root / "TOP30000_C2_32D.tsv"; write_tsv(c2_table,c2_rows)
        c2_receipt = {"status":MODULE.C2_STATUS,"counts":{"rows":4,"raw_features":36,"model_features":32,"shards":2},
                      "inputs":{"plan_sha256":sha(plan_path),"target_npz_sha256":assets["target_npz"][1],
                                "target_pdb8_sha256":assets["target_pdb8"][1],"target_pdb9_sha256":assets["target_pdb9"][1]},
                      "feature_names":MODULE.EXPECTED_C2_FEATURES,"predeclared_exclusions":sorted(MODULE.EXCLUSIONS),
                      "shards":observed_shards,"output":{"path":str(c2_table.resolve()),"sha256":sha(c2_table)},
                      "invariants":{"candidate_docking_pose_files_opened":0,"teacher_label_values_read":0}}
        c2_rp=c2_root/"RUN_RECEIPT.json";c2_rp.write_text(json.dumps(c2_receipt));write_sums(c2_root/"SHA256SUMS",[c2_table,c2_rp])

        base_root=self.root/"s0_m2_predictions_full150k_v1";base_root.mkdir();base=base_root/"PRODUCTION_PREDICTIONS_RANK_READY.tsv";write_tsv(base,[{"candidate_id":"C0"}])
        adapter_root=self.root/"c2_top30k_multimodal_predictions_v1";adapter_root.mkdir()
        adapter_rows=[]
        for index,row in enumerate(stage_rows):
            item={"candidate_id":row["candidate_id"],"sequence_sha256":row["sequence_sha256"],"parent_framework_cluster":row["parent_framework_cluster"]}
            for lane in MODULE.LANES:
                rank=index+1;pct=1-index/3;score=1-index/10
                item.update({f"{lane}__R8":str(score),f"{lane}__R9":str(score+.01),f"{lane}__Rdual_exact_min":str(score),
                             f"{lane}__Rdual_rank":str(rank),f"{lane}__Rdual_rank_percentile":str(pct)})
            adapter_rows.append(item)
        adapter_table=adapter_root/"TOP30000_C2_MULTIMODAL_PREDICTIONS.tsv";write_tsv(adapter_table,adapter_rows)
        adapter_receipt={"status":MODULE.ADAPTER_STATUS,"counts":{"rows":4,"lanes":4,"c2_features":32},"lanes":list(MODULE.LANES),
                         "inputs":{"vendor_adapter":{"sha256":assets["vendor_adapter"][1]},"artifact":{"sha256":assets["model_artifact"][1]},
                                   "c2_features":{"sha256":sha(c2_table)},"stage1_sha256":sha(stage),"base_predictions_sha256":sha(base)},
                         "output":{"path":str(adapter_table.resolve()),"sha256":sha(adapter_table)},
                         "invariants":{"candidate_docking_pose_files_opened":0,"teacher_label_values_read":0}}
        adapter_rp=adapter_root/"RUN_RECEIPT.json";adapter_rp.write_text(json.dumps(adapter_receipt));write_sums(adapter_root/"SHA256SUMS",[adapter_table,adapter_rp])

        final_root=self.root/"c2_refined_top7500_docking_handoff_v1";final_root.mkdir()
        final_rows=[]
        channels=("C2_REFINED_CONSENSUS","TARGET_MODEL_C2_SUPPORTED_RESCUE")
        for rank,index in enumerate((0,1),1):
            row=dict(stage_rows[index]);row.update({"selection_channel":channels[index],"final_c2_refined_rank":str(rank),
                                                    "high_confidence_core_flag":"true" if index==0 else "false"})
            final_rows.append(row)
        final_table=final_root/"TOP7500_C2_REFINED.tsv";write_tsv(final_table,final_rows)
        core=final_root/"TOP7500_C2_REFINED_HIGH_CONFIDENCE_CORE.tsv";write_tsv(core,[final_rows[0]])
        fasta=final_root/"TOP7500_C2_REFINED.fasta";fasta.write_text("".join(f">{r['candidate_id']} rank={r['final_c2_refined_rank']}\n{r['sequence']}\n" for r in final_rows))
        final_receipt={"status":MODULE.FINAL_STATUS,"rows":2,"channels":{"C2_REFINED_CONSENSUS":1,"TARGET_MODEL_C2_SUPPORTED_RESCUE":1},
                       "high_confidence_core_rows":1,"inputs":{"stage1_sha256":sha(stage),"c2_sha256":sha(adapter_table)},
                       "outputs":{p.name:sha(p) for p in (final_table,fasta,core)},
                       "invariants":{"candidate_docking_pose_files_opened":0,"teacher_label_values_read":0}}
        final_rp=final_root/"RUN_RECEIPT.json";final_rp.write_text(json.dumps(final_receipt));write_sums(final_root/"SHA256SUMS",[final_table,fasta,core,final_rp])

        return argparse.Namespace(runtime_root=self.root,output_json=self.root/"verified.json",stage1_rows=4,shards=2,final_rows=2,
                                  expected_channels_json=json.dumps(final_receipt["channels"]),
                                  **{role:path for role,(path,_digest) in assets.items()},
                                  **{role+"_sha256":digest for role,(_path,digest) in assets.items()})

    def test_complete_recursive_chain_passes(self) -> None:
        args=self.fixture();result=MODULE.run(args)
        self.assertEqual(result["status"],MODULE.STATUS)
        self.assertEqual(result["counts"]["final_rows"],2)
        self.assertTrue(args.output_json.is_file())

    def test_tampered_raw_feature_fails_closed(self) -> None:
        args=self.fixture();path=self.root/"c2_top30k_shard_outputs_v1/shard_000/raw_features_missing.tsv"
        target=self.root/"c2_top30k_shard_outputs_v1/shard_000/coarse_pose_features_36d.tsv"
        target.write_text(target.read_text()+"\n")
        with self.assertRaisesRegex(MODULE.VerificationError,"raw_output_hash"):
            MODULE.run(args)
        self.assertFalse(args.output_json.exists())

    def test_nonzero_truth_access_fails_closed(self) -> None:
        args=self.fixture();rp=self.root/"c2_refined_top7500_docking_handoff_v1/RUN_RECEIPT.json"
        receipt=json.loads(rp.read_text());receipt["invariants"]["teacher_label_values_read"]=1;rp.write_text(json.dumps(receipt))
        write_sums(self.root/"c2_refined_top7500_docking_handoff_v1/SHA256SUMS",[
            self.root/"c2_refined_top7500_docking_handoff_v1/TOP7500_C2_REFINED.tsv",
            self.root/"c2_refined_top7500_docking_handoff_v1/TOP7500_C2_REFINED.fasta",
            self.root/"c2_refined_top7500_docking_handoff_v1/TOP7500_C2_REFINED_HIGH_CONFIDENCE_CORE.tsv",rp])
        with self.assertRaisesRegex(MODULE.VerificationError,"final_nonzero"):
            MODULE.run(args)


if __name__ == "__main__":
    unittest.main()
