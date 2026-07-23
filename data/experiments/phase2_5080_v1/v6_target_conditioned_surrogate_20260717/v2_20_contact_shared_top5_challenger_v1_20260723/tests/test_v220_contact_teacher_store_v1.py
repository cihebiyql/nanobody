from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "v220_contact_teacher_store_v1.py"
SPEC = importlib.util.spec_from_file_location("v220_contact_teacher_store_v1", MODULE_PATH)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MOD
SPEC.loader.exec_module(MOD)


def sha(sequence: str) -> str:
    return hashlib.sha256(sequence.encode()).hexdigest()


def write_tsv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_release(base: Path, *, tamper_nodes: bool = False, omit_a_marginal: bool = False) -> tuple[Path, dict[str, tuple[str, str]], dict[str, dict[str, str]]]:
    release = base / "release"
    release.mkdir()
    special = {
        "A": {"sequence": "AC", "parent": "P0", "source": "V4D", "tier": "3_SEED", "seeds": "1,2,3"},
        "B": {"sequence": "DEF", "parent": "P1", "source": "V4H", "tier": "2_SEED", "seeds": "1,2"},
        "C": {"sequence": "G", "parent": "P2", "source": "V29", "tier": "3_SEED", "seeds": "BAD"},
    }
    identities: list[dict[str, str]] = []
    source_remaining = {"V4D": 112, "V4H": 319, "V29": 304}
    identities.extend({"id": key, **value} for key, value in special.items())
    for index in range(735):
        source = next(name for name in ("V4D", "V4H", "V29") if source_remaining[name])
        source_remaining[source] -= 1
        identities.append({
            "id": f"S{index:04d}",
            "sequence": "A",
            "parent": f"P{2 + (index % 51)}",
            "source": source,
            "tier": "3_SEED",
            "seeds": "BAD",
        })
    assert len(identities) == 738
    assert len({row["parent"] for row in identities}) == 53

    manifest_fields = ["candidate_id", "sequence_sha256", "sequence", "parent_framework_cluster", "model_split", "teacher_source", "reliability_tier", "observed_seed_count", "observed_seed_ids"]
    manifest = []
    for row in identities:
        observed = "3" if row["tier"] == "3_SEED" else "2"
        if row["id"] not in {"A", "B"}:
            observed = "NOT_A_NUMBER"
        manifest.append({
            "candidate_id": row["id"], "sequence_sha256": sha(row["sequence"]), "sequence": row["sequence"],
            "parent_framework_cluster": row["parent"], "model_split": "train", "teacher_source": row["source"],
            "reliability_tier": row["tier"], "observed_seed_count": observed, "observed_seed_ids": row["seeds"],
        })
    write_tsv(release / MOD.MANIFEST_NAME, manifest_fields, manifest)

    node_fields = ["receptor", "pvrig_node_index", "pvrig_uniprot_position", "pvrig_aa"]
    nodes = []
    for receptor, count in MOD.DEFAULT_TARGET_NODES.items():
        if tamper_nodes and receptor == "8x6b":
            count -= 1
        nodes.extend({"receptor": receptor, "pvrig_node_index": index, "pvrig_uniprot_position": 1000 + index, "pvrig_aa": "A"} for index in range(1, count + 1))
    write_tsv(release / MOD.NODE_CONTRACT_NAME, node_fields, nodes)

    group_fields = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier", "receptor", "observed_seed_count", "sequence_length", "target_node_count", "dense_pair_universe_size", "sparse_nonzero_pair_rows", "dense_marginal_rows", "technical_failure_zero_imputations", "pair_table_semantics"]
    groups = []
    for row in identities:
        for receptor, node_count in MOD.DEFAULT_TARGET_NODES.items():
            fit = row["id"] in {"A", "B"}
            technical = row["id"] == "B" and receptor == "8x6b"
            length = len(row["sequence"])
            groups.append({
                "candidate_id": row["id"], "sequence_sha256": sha(row["sequence"]), "parent_framework_cluster": row["parent"],
                "teacher_source": row["source"], "reliability_tier": row["tier"], "receptor": receptor,
                "observed_seed_count": (3 if row["tier"] == "3_SEED" else 2) if fit else "BAD_INT",
                "sequence_length": length if fit else "BAD_INT", "target_node_count": node_count if fit else "BAD_INT",
                "dense_pair_universe_size": length * node_count if fit else "BAD_INT",
                "sparse_nonzero_pair_rows": 0 if technical else (1 if fit else "BAD_INT"),
                "dense_marginal_rows": length if fit else "BAD_INT",
                "technical_failure_zero_imputations": 1 if technical else (0 if fit else "BAD_INT"),
                "pair_table_semantics": MOD.PAIR_SEMANTICS,
            })
    write_tsv(release / MOD.GROUP_NAME, group_fields, groups)

    marginal_fields = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier", "receptor", "observed_seed_count", "vhh_sequence_index", "vhh_aa", "vhh_region", "contact_marginal_mean", "contact_marginal_variance", "contact_marginal_uncertainty_weight", "target_mask"]
    marginal = []
    for cid, receptor in (("A", "8x6b"), ("A", "9e6y"), ("B", "9e6y")):
        row = special[cid]
        for index, aa in enumerate(row["sequence"], 1):
            if omit_a_marginal and cid == "A" and receptor == "8x6b" and index == 2:
                continue
            marginal.append({"candidate_id": cid, "sequence_sha256": sha(row["sequence"]), "parent_framework_cluster": row["parent"], "teacher_source": row["source"], "reliability_tier": row["tier"], "receptor": receptor, "observed_seed_count": 3 if cid == "A" else 2, "vhh_sequence_index": index, "vhh_aa": aa, "vhh_region": "CDR3", "contact_marginal_mean": 0.2 * index, "contact_marginal_variance": 0.0, "contact_marginal_uncertainty_weight": 1.0, "target_mask": 1})
    # Technical-NA and score rows deliberately contain unparsable numeric payloads.
    for cid, receptor in (("B", "8x6b"), ("C", "8x6b")):
        row = special[cid]
        marginal.append({"candidate_id": cid, "sequence_sha256": sha(row["sequence"]), "parent_framework_cluster": row["parent"], "teacher_source": row["source"], "reliability_tier": row["tier"], "receptor": receptor, "observed_seed_count": "BAD", "vhh_sequence_index": "BAD", "vhh_aa": "X", "vhh_region": "CDR3", "contact_marginal_mean": "NOT_A_FLOAT", "contact_marginal_variance": "NOT_A_FLOAT", "contact_marginal_uncertainty_weight": "NOT_A_FLOAT", "target_mask": "BAD"})
    write_tsv(release / MOD.MARGINAL_NAME, marginal_fields, marginal)

    pair_fields = ["candidate_id", "sequence_sha256", "parent_framework_cluster", "teacher_source", "reliability_tier", "receptor", "observed_seed_count", "vhh_sequence_index", "vhh_aa", "vhh_region", "pvrig_node_index", "pvrig_uniprot_position", "pvrig_aa", "contact_target_mean", "contact_target_variance", "contact_uncertainty_weight", "pair_table_semantics", "target_mask"]
    pairs = []
    for cid, receptor in (("A", "8x6b"), ("A", "9e6y"), ("B", "9e6y")):
        row = special[cid]
        pairs.append({"candidate_id": cid, "sequence_sha256": sha(row["sequence"]), "parent_framework_cluster": row["parent"], "teacher_source": row["source"], "reliability_tier": row["tier"], "receptor": receptor, "observed_seed_count": 3 if cid == "A" else 2, "vhh_sequence_index": 1, "vhh_aa": row["sequence"][0], "vhh_region": "CDR3", "pvrig_node_index": 1, "pvrig_uniprot_position": 1001, "pvrig_aa": "A", "contact_target_mean": 0.5, "contact_target_variance": 0.0, "contact_uncertainty_weight": 1.0, "pair_table_semantics": MOD.PAIR_SEMANTICS, "target_mask": 1})
    for cid, receptor in (("B", "8x6b"), ("C", "8x6b")):
        row = special[cid]
        pairs.append({"candidate_id": cid, "sequence_sha256": sha(row["sequence"]), "parent_framework_cluster": row["parent"], "teacher_source": row["source"], "reliability_tier": row["tier"], "receptor": receptor, "observed_seed_count": "BAD", "vhh_sequence_index": "BAD", "vhh_aa": "X", "vhh_region": "CDR3", "pvrig_node_index": "BAD", "pvrig_uniprot_position": "BAD", "pvrig_aa": "X", "contact_target_mean": "NOT_A_FLOAT", "contact_target_variance": "NOT_A_FLOAT", "contact_uncertainty_weight": "NOT_A_FLOAT", "pair_table_semantics": MOD.PAIR_SEMANTICS, "target_mask": "BAD"})
    write_tsv(release / MOD.PAIR_NAME, pair_fields, pairs)

    access = {"status": "PASS_SPLIT_BEFORE_ACCESS_TRAIN_ONLY", "development_pose_files_stat_hashed_opened": 0, "frozen_test_pose_files_stat_hashed_opened": 0, "quarantine_pose_files_stat_hashed_opened": 0, "unknown_pose_files_stat_hashed_opened": 0, "forbidden_pose_attempt_count": 0}
    (release / MOD.ACCESS_AUDIT_NAME).write_text(json.dumps(access))
    output_names = [MOD.MANIFEST_NAME, MOD.MARGINAL_NAME, MOD.PAIR_NAME, MOD.GROUP_NAME, MOD.NODE_CONTRACT_NAME, MOD.ACCESS_AUDIT_NAME]
    receipt = {"status": MOD.PACKAGE_STATUS, "oof_training_authorized": False, "counts": {"candidates": 738, "parents": 53}, "outputs": {name: MOD.sha256_file(release / name) for name in output_names}}
    (release / MOD.RECEIPT_NAME).write_text(json.dumps(receipt))
    allowed = {"A": (sha("AC"), "P0"), "B": (sha("DEF"), "P1"), "D": (sha("AA"), "P0")}
    return release, allowed, special


class ContactTeacherStoreTests(unittest.TestCase):
    def load(self, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        release, allowed, special = make_release(Path(tmp.name), **kwargs)
        return MOD.ContactTeacherStore.from_release(release, allowed), release, allowed, special

    def test_release_api_freezes_allowlist_before_numeric_parse(self):
        store, _, _, _ = self.load()
        audit = store.audit
        self.assertEqual(audit["access_order"][:3], ["outer_fit_candidate_allowlist_received", "outer_fit_parent_allowlist_frozen", "allowed_candidate_identity_strings_frozen_without_numeric_parse"])
        self.assertEqual(audit["score_parent_numeric_float_parse_count"], 0)
        self.assertEqual(audit["score_parent_numeric_int_parse_count"], 0)
        self.assertEqual(audit["counts"]["teacher_candidates_total"], 738)
        self.assertEqual(audit["target_nodes"], {"8x6b": 103, "9e6y": 108})

    def test_dense_exact_zero_and_technical_na(self):
        store, _, _, _ = self.load()
        a8 = store.groups[("A", "8x6b")]
        self.assertEqual(a8.pair_target.shape, (2, 103))
        self.assertTrue(a8.pair_mask.all())
        self.assertEqual(float(a8.pair_target[0, 1]), 0.0)
        self.assertEqual(float(a8.pair_uncertainty[0, 1]), 1.0)
        b8 = store.groups[("B", "8x6b")]
        self.assertFalse(b8.marginal_mask.any())
        self.assertFalse(b8.pair_mask.any())

    def test_augment_batch_v25_keys_shapes_weights_and_token_mapping(self):
        store, _, allowed, _ = self.load()
        rows = [
            {"candidate_id": "A", "sequence": "AC", "sequence_sha256": allowed["A"][0], "parent": "P0"},
            {"candidate_id": "B", "sequence": "DEF", "sequence_sha256": allowed["B"][0], "parent_framework_cluster": "P1"},
            {"candidate_id": "D", "sequence": "AA", "sequence_sha256": allowed["D"][0], "parent": "P0"},
        ]
        residue_mask = torch.tensor([[0,1,1,0,0], [1,0,1,1,0], [0,1,0,1,0]], dtype=torch.bool)
        original = {"x": torch.ones(3, 1)}
        result = store.augment_batch(original, rows, residue_mask)
        self.assertNotIn("marginal_targets", original)
        self.assertEqual(result["marginal_targets"].shape, (3, 5, 2))
        self.assertEqual(result["pair_targets_8x6b"].shape, (3, 5, 103))
        self.assertEqual(result["pair_targets_9e6y"].shape, (3, 5, 108))
        torch.testing.assert_close(result["marginal_tier_weights"], torch.tensor([1.0, 0.8, 0.0]))
        self.assertTrue(result["marginal_mask"][0, 1, 0])
        self.assertFalse(result["marginal_mask"][0, 0, 0])
        self.assertFalse(result["pair_mask_8x6b"][1].any())
        self.assertTrue(result["pair_mask_9e6y"][1, 0].all())

    def test_allowed_source_filter_is_masked_before_numeric_parse(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        release, allowed, _ = make_release(Path(tmp.name))
        store = MOD.ContactTeacherStore.from_release(release, allowed, allowed_sources=["V4D"])
        self.assertEqual(store.teacher_metadata["B"].role, "source_excluded")
        self.assertNotIn(("B", "9e6y"), store.groups)
        self.assertGreater(store.audit["source_rows_skipped_before_numeric_parse"]["group_audit"], 0)

    def test_target_node_contract_fails_closed(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        release, allowed, _ = make_release(Path(tmp.name), tamper_nodes=True)
        with self.assertRaisesRegex(MOD.ContactTeacherStoreError, "target_node_index_closure"):
            MOD.ContactTeacherStore.from_release(release, allowed)

    def test_marginal_sequence_closure_fails_closed(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        release, allowed, _ = make_release(Path(tmp.name), omit_a_marginal=True)
        with self.assertRaisesRegex(MOD.ContactTeacherStoreError, "marginal_sequence_index_closure"):
            MOD.ContactTeacherStore.from_release(release, allowed)

    def test_hash_tamper_fails_closed(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        release, allowed, _ = make_release(Path(tmp.name))
        with gzip.open(release / MOD.PAIR_NAME, "at", encoding="utf-8") as handle:
            handle.write("tamper\n")
        with self.assertRaisesRegex(MOD.ContactTeacherStoreError, "teacher_output_sha256"):
            MOD.ContactTeacherStore.from_release(release, allowed)

    def test_shuffle_seed_rejected(self):
        with self.assertRaisesRegex(MOD.ContactTeacherStoreError, "shuffle_seed_not_supported"):
            MOD.ContactTeacherStore.from_release("unused", {"A": ("0"*64, "P0")}, shuffle_seed=1)


if __name__ == "__main__":
    unittest.main()
