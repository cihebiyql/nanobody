import csv
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

import torch
from torch import nn


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import augment_target_graph_esm2_v2 as mod


class FakeTokenizer:
    def __init__(self):
        alphabet = "ACDEFGHIKLMNPQRSTVWY"
        self.vocab = {aa: index + 1 for index, aa in enumerate(alphabet)}
        self.bos, self.eos = 101, 102
        self.all_special_ids = [self.bos, self.eos]

    def __call__(
        self,
        text,
        *,
        add_special_tokens=True,
        return_attention_mask=True,
        return_tensors=None,
    ):
        residues = text.replace(" ", "")
        ids = [self.vocab[aa] for aa in residues]
        if add_special_tokens:
            ids = [self.bos] + ids + [self.eos]
        if return_tensors == "pt":
            result = {"input_ids": torch.tensor([ids], dtype=torch.long)}
            if return_attention_mask:
                result["attention_mask"] = torch.ones((1, len(ids)), dtype=torch.long)
            return result
        result = {"input_ids": ids}
        if return_attention_mask:
            result["attention_mask"] = [1] * len(ids)
        return result

    def get_special_tokens_mask(self, ids, already_has_special_tokens=True):
        assert already_has_special_tokens
        return [int(value in self.all_special_ids) for value in ids]


class BadTokenizer(FakeTokenizer):
    def __call__(self, text, **kwargs):
        if not kwargs.get("add_special_tokens", True):
            return super().__call__(text, **kwargs)
        ids = [self.bos, 99, self.eos]
        if kwargs.get("return_tensors") == "pt":
            return {"input_ids": torch.tensor([ids]), "attention_mask": torch.ones((1, 3), dtype=torch.long)}
        return {"input_ids": ids, "attention_mask": [1, 1, 1]}


class FakeBackbone(nn.Module):
    def __init__(self, hidden=4):
        super().__init__()
        self.hidden = hidden
        self.scale = nn.Parameter(torch.arange(1, hidden + 1, dtype=torch.float32))

    def forward(self, input_ids, attention_mask):
        del attention_mask
        states = input_ids.to(torch.float32).unsqueeze(-1) * self.scale.view(1, 1, -1)
        return type("Output", (), {"last_hidden_state": states})()


def base_graph(nodes):
    edges = []
    for index in range(nodes - 1):
        edges.extend(((index, index + 1), (index + 1, index)))
    return {
        "node_features": torch.arange(nodes * 30, dtype=torch.float32).reshape(nodes, 30) / 100.0,
        "edge_index": torch.tensor(edges, dtype=torch.long).T.contiguous(),
        "edge_features": torch.ones((len(edges), 26), dtype=torch.float32),
        "interface_mask": torch.tensor([(index % 2) == 0 for index in range(nodes)]),
        "hotspot_mask": torch.tensor([index == 1 for index in range(nodes)]),
    }


class TestAugmentTargetGraphESM2V2(unittest.TestCase):
    def manifest(self):
        result = {}
        for receptor, sequence, pdb_id, chain in (
            ("8x6b", "ACDE", "8X6B", "B"),
            ("9e6y", "FGHIK", "9E6Y", "A"),
        ):
            result[receptor] = {
                "receptor": receptor,
                "pdb_id": pdb_id,
                "pvrig_chain": chain,
                "sequence": sequence,
                "sequence_sha256": hashlib.sha256(sequence.encode()).hexdigest(),
                "node_count": str(len(sequence)),
            }
        return result

    def test_exact_token_alignment_and_float32_storage(self):
        tokenizer = FakeTokenizer()
        ids, mask, positions, mode = mod.exact_tokenize_sequence(tokenizer, "ACDE")
        self.assertEqual(ids.shape, (1, 6))
        self.assertEqual(mask.shape, ids.shape)
        self.assertEqual(positions.tolist(), [1, 2, 3, 4])
        self.assertIn(mode, {"raw", "space_separated"})
        embedding, _ = mod.embed_observed_sequence(
            tokenizer, FakeBackbone(4), "ACDE",
            device=torch.device("cpu"), expected_hidden_dim=4,
            inference_dtype=torch.bfloat16,
        )
        self.assertEqual(embedding.shape, (4, 4))
        self.assertEqual(embedding.dtype, torch.float32)

    def test_alignment_failure_is_fail_closed(self):
        with self.assertRaisesRegex(mod.TargetPLMError, "token_residue_alignment_failed"):
            mod.exact_tokenize_sequence(BadTokenizer(), "ACDE")

    def test_augmentation_appends_embeddings_and_preserves_graph_tensors(self):
        manifest = self.manifest()
        base = {receptor: base_graph(len(row["sequence"])) for receptor, row in manifest.items()}
        augmented, audit = mod.augment_graphs(
            base, manifest, FakeTokenizer(), FakeBackbone(4),
            device=torch.device("cpu"), expected_hidden_dim=4,
            inference_dtype=torch.bfloat16,
        )
        for receptor in mod.RECEPTORS:
            nodes = len(manifest[receptor]["sequence"])
            self.assertEqual(augmented[receptor]["node_features"].shape, (nodes, 34))
            self.assertTrue(torch.equal(augmented[receptor]["node_features"][:, :30], base[receptor]["node_features"]))
            for field in ("edge_index", "edge_features", "interface_mask", "hotspot_mask"):
                self.assertTrue(torch.equal(augmented[receptor][field], base[receptor][field]))
            self.assertEqual(audit[receptor]["embedding_dtype_stored"], "float32")
        self.assertFalse(any("teacher_source" in key for graph in augmented.values() for key in graph))

    def write_base_delivery(self, root):
        manifest = self.manifest()
        base = {receptor: base_graph(len(row["sequence"])) for receptor, row in manifest.items()}
        pt = root / "target_graphs_v2.pt"
        torch.save(base, pt)
        manifest_path = root / "target_graph_manifest_v2.tsv"
        fields = ["receptor", "pdb_id", "pvrig_chain", "sequence", "sequence_sha256", "node_count"]
        with manifest_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(manifest.values())
        receipt = {
            "status": "PASS_FIXED_TARGET_GRAPHS_MATERIALIZED",
            "node_feature_dim": 30,
            "outputs": {
                pt.name: mod.sha256_file(pt),
                manifest_path.name: mod.sha256_file(manifest_path),
            },
            "targets": {
                receptor: {"sequence_sha256": row["sequence_sha256"], "nodes": int(row["node_count"])}
                for receptor, row in manifest.items()
            },
        }
        receipt_path = root / "target_graph_receipt_v2.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return pt, manifest_path, receipt_path, base, manifest

    def test_base_receipt_and_sequence_identity_are_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            pt, manifest_path, receipt_path, _, _ = self.write_base_delivery(root)
            graphs, manifest, receipt = mod.load_base_graphs(pt, manifest_path, receipt_path)
            self.assertEqual(set(graphs), set(mod.RECEPTORS))
            self.assertEqual(set(manifest), set(mod.RECEPTORS))
            self.assertEqual(receipt["node_feature_dim"], 30)
            payload = json.loads(receipt_path.read_text())
            payload["targets"]["8x6b"]["sequence_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(mod.TargetPLMError, "receipt_sequence"):
                mod.load_base_graphs(pt, manifest_path, receipt_path)

    def test_content_addressed_delivery_is_weights_only_and_hash_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            manifest = self.manifest()
            base = {receptor: base_graph(len(row["sequence"])) for receptor, row in manifest.items()}
            augmented, audit = mod.augment_graphs(
                base, manifest, FakeTokenizer(), FakeBackbone(4),
                device=torch.device("cpu"), expected_hidden_dim=4,
                inference_dtype=torch.bfloat16,
            )
            identity_file = root / "fake.safetensors"
            identity_file.write_bytes(b"fake-model")
            output = root / "delivery"
            receipt = mod.write_content_addressed_delivery(
                augmented_graphs=augmented, audit=audit, output_dir=output,
                input_hashes={"model_identity_file": mod.sha256_file(identity_file)},
                model_identity={"model_identity_sha256": mod.sha256_file(identity_file), "network_disabled": True},
                implementation_path=pathlib.Path(mod.__file__),
            )
            current = json.loads((output / mod.CURRENT_NAME).read_text())
            artifact = output / current["artifact_relative_path"]
            self.assertEqual(current["artifact_sha256"], mod.sha256_file(artifact))
            self.assertEqual(receipt["output"]["sha256"], current["artifact_sha256"])
            payload = torch.load(artifact, map_location="cpu", weights_only=True)
            self.assertEqual(set(payload["target_graphs"]), set(mod.RECEPTORS))
            self.assertFalse(mod._contains_forbidden_source_key(payload))
            receipt_path = output / current["receipt_relative_path"]
            self.assertEqual(current["receipt_sha256"], mod.sha256_file(receipt_path))

    def test_production_loader_rejects_cpu_before_transformers_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            model = root / "model"
            model.mkdir()
            identity = model / "model.safetensors"
            identity.write_bytes(b"fake")
            with self.assertRaisesRegex(mod.TargetPLMError, "requires_cuda"):
                mod.load_frozen_esm2(model, identity, device=torch.device("cpu"), expected_hidden_dim=4)


if __name__ == "__main__":
    unittest.main()
