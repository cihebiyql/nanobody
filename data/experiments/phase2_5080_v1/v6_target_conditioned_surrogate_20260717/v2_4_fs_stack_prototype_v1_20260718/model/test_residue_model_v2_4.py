import inspect
import pathlib
import sys
import unittest

import torch
from torch import nn


HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import residue_model_v2_4 as mod


class FrozenBackbone(nn.Module):
    def __init__(self, hidden: int = 12) -> None:
        super().__init__()
        self.embedding = nn.Embedding(32, hidden)

    def forward(self, input_ids, attention_mask):
        del attention_mask
        return type("Output", (), {"last_hidden_state": self.embedding(input_ids)})()


def sequence_edges(batch: int, length: int, valid: int, edge_dim: int):
    edges = []
    for item in range(batch):
        offset = item * length
        for index in range(valid - 1):
            edges.extend(((offset + index, offset + index + 1), (offset + index + 1, offset + index)))
    edge_index = torch.tensor(edges, dtype=torch.long).T.contiguous()
    edge_features = torch.zeros((len(edges), edge_dim), dtype=torch.float32)
    edge_features[:, 0] = 1.0
    return edge_index, edge_features


def target_graph(nodes: int, node_dim: int, edge_dim: int, offset: float):
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


class TestResidueModelV24(unittest.TestCase):
    def make_model_and_inputs(self):
        torch.manual_seed(7)
        config = mod.ResidueV24Config(
            backbone_hidden_size=12,
            target_node_dim=7,
            graph_hidden_dim=32,
            dropout=0.0,
        )
        model = mod.FeatureSeparatedResidueSurrogate(
            FrozenBackbone(hidden=12), mod.FeatureSeparatedTargetHead(config),
        )
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
        }
        return config, model, inputs

    def test_split_terminals_are_independent_and_pair_rank_is_implicit(self):
        config, model, inputs = self.make_model_and_inputs()
        interaction = model.head.interaction
        self.assertFalse(interaction.materializes_rank4_pair_tensor)
        self.assertEqual(interaction.attention_terminal.shape, (config.interaction_rank,))
        self.assertEqual(interaction.contact_terminal.shape, (config.interaction_rank,))
        self.assertNotEqual(interaction.attention_terminal.data_ptr(), interaction.contact_terminal.data_ptr())
        self.assertFalse(hasattr(model.head.contact_calibration, "raw_scale"))
        self.assertFalse(any("scale" in name for name, _ in model.head.contact_calibration.named_parameters()))
        self.assertEqual(set(dict(model.head.contact_calibration.named_parameters())), {"bias"})
        output = model(**inputs)
        self.assertEqual(output["attention_logits_8x6b"].ndim, 3)
        self.assertEqual(output["contact_logits_8x6b"].ndim, 3)
        self.assertFalse(torch.equal(output["attention_logits_8x6b"], output["contact_logits_8x6b"]))
        contract = mod.model_contract(config)
        self.assertFalse(contract["rank4_pair_tensor_materialized"])
        self.assertEqual(contract["contact_calibration"], "fixed_scale_1_plus_receptor_specific_bias")

    def test_feature_firewall_excludes_m2_and_126d_from_forward_signatures(self):
        config, model, inputs = self.make_model_and_inputs()
        for callable_object in (model.forward, model.head.forward):
            parameters = set(inspect.signature(callable_object).parameters)
            self.assertNotIn("m2_base", parameters)
            self.assertNotIn("structure", parameters)
            self.assertNotIn("structure_features", parameters)
        self.assertFalse(hasattr(config, "structure_dim"))
        self.assertFalse(hasattr(model.head, "structure_projection"))
        self.assertFalse(any("m2" in name.lower() for name, _ in model.named_parameters()))
        with self.assertRaises(TypeError):
            model(**inputs, m2_base=torch.zeros(2, 3))

    def test_direct_r8_r9_and_exact_min_dual(self):
        _, model, inputs = self.make_model_and_inputs()
        output = model(**inputs)
        self.assertEqual(output["receptor_predictions"].shape, (2, 2))
        expected = output["receptor_predictions"].min(dim=1).values
        self.assertTrue(torch.equal(output["exact_min_dual"], expected))
        self.assertEqual(output["prediction"].shape, (2, 3))
        self.assertTrue(torch.equal(output["prediction"][:, 2], expected))
        self.assertTrue(torch.equal(output["prediction"][:, :2], output["receptor_predictions"]))

    def test_bfloat16_endpoint_entropy_and_full_forward_are_finite(self):
        logits = {
            "8x6b": torch.tensor([[[100.0, -100.0], [80.0, -80.0]]], dtype=torch.bfloat16, requires_grad=True),
            "9e6y": torch.tensor([[[-100.0, 100.0], [-80.0, 80.0]]], dtype=torch.bfloat16, requires_grad=True),
        }
        probabilities = {name: torch.sigmoid(value) for name, value in logits.items()}
        graphs = {
            name: {
                "interface_mask": torch.tensor([True, False]),
                "hotspot_mask": torch.tensor([True, False]),
            }
            for name in mod.RECEPTOR_NAMES
        }
        summary = mod.summarize_pair_probabilities(
            probabilities,
            torch.tensor([[True, True]]),
            torch.tensor([[1, 3]]),
            graphs,
            epsilon=1e-6,
        )
        self.assertTrue(torch.isfinite(summary).all())
        summary.sum().backward()
        self.assertTrue(all(value.grad is not None and torch.isfinite(value.grad).all() for value in logits.values()))

        _, model, inputs = self.make_model_and_inputs()
        model.train()
        with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
            output = model(**inputs)
        self.assertTrue(all(torch.isfinite(value).all() for value in output.values() if isinstance(value, torch.Tensor)))
        # This CI host exposes CPU BF16 forward but its oneDNN build does not
        # support every BF16 backward kernel.  Gradient finiteness is checked
        # with the same model path in FP32; the endpoint-sensitive BF16 entropy
        # backward is already exercised above.
        output = model(**inputs)
        loss = output["prediction"].square().mean()
        loss.backward()
        gradients = [parameter.grad for parameter in model.head.parameters() if parameter.grad is not None]
        self.assertTrue(gradients)
        self.assertTrue(all(torch.isfinite(gradient).all() for gradient in gradients))

    def test_terminal_gradient_routing_is_separate(self):
        _, model, inputs = self.make_model_and_inputs()
        interaction = model.head.interaction

        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        contact_loss = output["contact_logits_8x6b"][:, :4].square().mean()
        contact_loss.backward()
        self.assertIsNotNone(interaction.contact_terminal.grad)
        self.assertIsNone(interaction.attention_terminal.grad)
        self.assertIsNotNone(interaction.vhh_left.weight.grad)

        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        attention_loss = output["attention_logits_8x6b"][:, :4].square().mean()
        attention_loss.backward()
        self.assertIsNotNone(interaction.attention_terminal.grad)
        self.assertIsNone(interaction.contact_terminal.grad)
        self.assertIsNotNone(interaction.target_right.weight.grad)

        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        output["receptor_predictions"].sum().backward()
        self.assertIsNotNone(interaction.attention_terminal.grad)
        self.assertIsNotNone(model.head.scalar_head[-1].weight.grad)
        self.assertIsNone(model.backbone.embedding.weight.grad)

    def test_m2_free_vhh_only_matched_head(self):
        config, _, target_inputs = self.make_model_and_inputs()
        model = mod.M2FreeVHHOnlySurrogate(FrozenBackbone(hidden=12), mod.M2FreeVHHOnlyHead(config))
        inputs = {key: value for key, value in target_inputs.items() if key != "target_graphs"}
        output = model(**inputs)
        self.assertEqual(output["receptor_predictions"].shape, (2, 2))
        self.assertTrue(torch.equal(output["exact_min_dual"], output["receptor_predictions"].min(1).values))
        for callable_object in (model.forward, model.head.forward):
            parameters = set(inspect.signature(callable_object).parameters)
            self.assertNotIn("m2_base", parameters)
            self.assertNotIn("structure_features", parameters)

    def test_stable_softmin_is_bfloat16_finite_and_differentiable(self):
        left = torch.tensor([0.1, 100.0], dtype=torch.bfloat16, requires_grad=True)
        right = torch.tensor([0.2, -100.0], dtype=torch.bfloat16, requires_grad=True)
        result = mod.stable_softmin(left, right, tau=0.01)
        self.assertEqual(result.dtype, torch.float32)
        self.assertTrue(torch.isfinite(result).all())
        result.sum().backward()
        self.assertTrue(torch.isfinite(left.grad).all())
        self.assertTrue(torch.isfinite(right.grad).all())


if __name__ == "__main__":
    unittest.main()
