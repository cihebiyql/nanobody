import inspect
import pathlib
import sys
import unittest

import torch
from torch import nn


ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))
import residue_model_v2 as mod


class FrozenBackbone(nn.Module):
    def __init__(self, hidden=12):
        super().__init__()
        self.embedding = nn.Embedding(32, hidden)

    def forward(self, input_ids, attention_mask):
        del attention_mask
        return type("Output", (), {"last_hidden_state": self.embedding(input_ids)})()


def sequence_edges(batch, length, valid_length, edge_dim):
    edges = []
    for item in range(batch):
        offset = item * length
        for index in range(valid_length - 1):
            edges.extend(((offset + index, offset + index + 1), (offset + index + 1, offset + index)))
    edge_index = torch.tensor(edges, dtype=torch.long).T.contiguous()
    edge_features = torch.zeros((len(edges), edge_dim), dtype=torch.float32)
    edge_features[:, 0] = 1.0
    edge_features[:, -6] = 1.0
    return edge_index, edge_features


def target_graph(nodes, node_dim, edge_dim, offset):
    edges = []
    for index in range(nodes - 1):
        edges.extend(((index, index + 1), (index + 1, index)))
    edge_index = torch.tensor(edges, dtype=torch.long).T.contiguous()
    edge_features = torch.zeros((len(edges), edge_dim), dtype=torch.float32)
    edge_features[:, 0] = 1.0
    return {
        "node_features": torch.arange(nodes * node_dim, dtype=torch.float32).reshape(nodes, node_dim) / 100.0 + offset,
        "edge_index": edge_index,
        "edge_features": edge_features,
        "interface_mask": torch.tensor([(index % 2) == 0 for index in range(nodes)]),
        "hotspot_mask": torch.tensor([index in {1, 2} for index in range(nodes)]),
    }


class TestResidueModelV2(unittest.TestCase):
    def test_bfloat16_saturated_pair_entropy_is_finite_and_differentiable(self):
        logits = {
            "8x6b": torch.tensor(
                [[[100.0, -100.0, 0.0], [80.0, -80.0, 2.0]]],
                dtype=torch.bfloat16,
                requires_grad=True,
            ),
            "9e6y": torch.tensor(
                [[[-100.0, 100.0, 0.0], [-80.0, 80.0, -2.0]]],
                dtype=torch.bfloat16,
                requires_grad=True,
            ),
        }
        probabilities = {name: torch.sigmoid(value) for name, value in logits.items()}
        residue_mask = torch.tensor([[True, True]])
        region_index = torch.tensor([[1, 3]])
        target_graphs = {
            "8x6b": {
                "interface_mask": torch.tensor([True, True, False]),
                "hotspot_mask": torch.tensor([True, False, False]),
            },
            "9e6y": {
                "interface_mask": torch.tensor([True, False, True]),
                "hotspot_mask": torch.tensor([False, True, False]),
            },
        }

        summary = mod.summarize_pair_probabilities(
            probabilities,
            residue_mask,
            region_index,
            target_graphs,
            epsilon=1e-6,
        )

        self.assertEqual(summary.shape, (1, 14))
        self.assertTrue(torch.isfinite(summary).all())
        summary.sum().backward()
        self.assertTrue(all(value.grad is not None for value in logits.values()))
        self.assertTrue(all(torch.isfinite(value.grad).all() for value in logits.values()))

    def test_invariant_graph_encoder_supports_bfloat16_autocast(self):
        encoder = mod.InvariantGraphEncoder(
            input_dim=8, hidden_dim=16, edge_feature_dim=4, layers=2, dropout=0.0,
        )
        nodes = torch.randn(6, 8)
        edges = torch.tensor([[0, 1, 2, 3, 4], [1, 2, 3, 4, 5]], dtype=torch.long)
        edge_features = torch.randn(5, 4)
        with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
            output = encoder(nodes, edges, edge_features)
        self.assertEqual(output.shape, (6, 16))
        self.assertTrue(torch.isfinite(output).all())

    def make_model_and_inputs(self):
        config = mod.ResidueV2Config(
            backbone_hidden_size=12,
            target_node_dim=7,
            structure_dim=4,
            graph_hidden_dim=32,
            dropout=0.0,
        )
        head = mod.TargetConditionedResidueV2Head(config)
        model = mod.ResidueV2Surrogate(FrozenBackbone(hidden=12), head)
        batch, length, valid = 2, 5, 4
        edge_index, edge_features = sequence_edges(batch, length, valid, config.edge_feature_dim)
        inputs = {
            "input_ids": torch.tensor([[1, 2, 3, 4, 0], [5, 6, 7, 8, 0]], dtype=torch.long),
            "attention_mask": torch.tensor([[1, 1, 1, 1, 0], [1, 1, 1, 1, 0]], dtype=torch.long),
            "residue_mask": torch.tensor([[1, 1, 1, 1, 0], [1, 1, 1, 1, 0]], dtype=torch.bool),
            "vhh_aa_index": torch.tensor([[0, 1, 2, 3, 0], [4, 5, 6, 7, 0]], dtype=torch.long),
            "vhh_region_index": torch.tensor([[0, 1, 2, 3, 0], [0, 1, 2, 3, 0]], dtype=torch.long),
            "vhh_confidence": torch.full((batch, length), 0.85),
            "vhh_edge_index": edge_index,
            "vhh_edge_features": edge_features,
            "target_graphs": {
                "8x6b": target_graph(5, config.target_node_dim, config.edge_feature_dim, 0.0),
                "9e6y": target_graph(6, config.target_node_dim, config.edge_feature_dim, 0.2),
            },
            "structure_features": torch.randn(batch, config.structure_dim),
            "m2_base": torch.tensor([[0.50, 0.52, 0.50], [0.55, 0.51, 0.51]]),
        }
        return config, model, inputs

    def test_forward_has_dual_pair_logits_and_exact_bounded_m2_residual(self):
        config, model, inputs = self.make_model_and_inputs()
        model.eval()
        output = model(**inputs)
        self.assertEqual(output["prediction"].shape, (2, 3))
        self.assertEqual(output["pair_logits_8x6b"].shape, (2, 5, 5))
        self.assertEqual(output["pair_logits_9e6y"].shape, (2, 5, 6))
        self.assertEqual(output["marginal_contact_logits"].shape, (2, 5, 2))
        self.assertEqual(output["pair_summary"].shape, (2, 14))
        self.assertTrue(torch.all(output["residual"].abs() <= 0.0200001))
        self.assertTrue(torch.allclose(output["prediction"], inputs["m2_base"] + output["residual"]))
        self.assertEqual(len(model.head.vhh_graph_encoder.layers), 3)
        self.assertEqual(len(model.head.target_graph_encoder.layers), 2)
        self.assertEqual(model.head.interaction.rank, 64)
        self.assertAlmostEqual(config.residual_scale, 0.02)

    def test_shared_target_encoder_and_source_or_absolute_coordinates_are_not_features(self):
        config, model, _ = self.make_model_and_inputs()
        contract = mod.model_contract(config)
        self.assertIn("teacher_source", contract["forbidden_features"])
        signature = inspect.signature(model.head.forward)
        self.assertNotIn("teacher_source", signature.parameters)
        self.assertNotIn("atom_ca", signature.parameters)
        self.assertNotIn("coordinates", signature.parameters)
        target_encoder_modules = [name for name, _ in model.head.named_modules() if name == "target_graph_encoder"]
        self.assertEqual(target_encoder_modules, ["target_graph_encoder"])

    def test_gradients_reach_graph_pair_and_residual_heads_but_not_backbone(self):
        _, model, inputs = self.make_model_and_inputs()
        model.train()
        output = model(**inputs)
        loss = output["prediction"].square().mean()
        loss = loss + 1e-3 * output["pair_logits_8x6b"][:, :4].square().mean()
        loss.backward()
        self.assertIsNone(model.backbone.embedding.weight.grad)
        self.assertIsNotNone(model.head.vhh_graph_encoder.layers[0].message[0].weight.grad)
        self.assertIsNotNone(model.head.target_graph_encoder.layers[0].message[0].weight.grad)
        self.assertIsNotNone(model.head.interaction.vhh_left.weight.grad)
        self.assertIsNotNone(model.head.interaction.target_fusion[1].weight.grad)
        self.assertIsNotNone(model.head.residual_head[-1].weight.grad)
        checkpoint = mod.trainable_checkpoint_state(model)
        self.assertTrue(checkpoint)
        self.assertTrue(all(name.startswith("head.") for name in checkpoint))

    def test_padding_content_cannot_change_prediction(self):
        _, model, inputs = self.make_model_and_inputs()
        model.eval()
        first = model(**inputs)["prediction"]
        modified = dict(inputs)
        modified["input_ids"] = inputs["input_ids"].clone()
        modified["input_ids"][:, -1] = torch.tensor([19, 23])
        modified["vhh_aa_index"] = inputs["vhh_aa_index"].clone()
        modified["vhh_aa_index"][:, -1] = torch.tensor([19, 20])
        modified["vhh_region_index"] = inputs["vhh_region_index"].clone()
        modified["vhh_region_index"][:, -1] = 4
        modified["vhh_confidence"] = inputs["vhh_confidence"].clone()
        modified["vhh_confidence"][:, -1] = -100.0
        second = model(**modified)["prediction"]
        self.assertTrue(torch.allclose(first, second, atol=1e-7, rtol=1e-7))

    def test_edge_touching_padding_fails_closed(self):
        _, model, inputs = self.make_model_and_inputs()
        modified = dict(inputs)
        extra = torch.tensor([[0], [4]], dtype=torch.long)
        modified["vhh_edge_index"] = torch.cat((inputs["vhh_edge_index"], extra), dim=1)
        modified["vhh_edge_features"] = torch.cat(
            (inputs["vhh_edge_features"], torch.zeros((1, inputs["vhh_edge_features"].shape[1]))), dim=0,
        )
        with self.assertRaisesRegex(mod.ResidueV2ModelError, "touches_padding"):
            model(**modified)


if __name__ == "__main__":
    unittest.main()
