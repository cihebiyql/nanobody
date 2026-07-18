import inspect
import pathlib
import sys
import unittest

import torch
from torch import nn


HERE = pathlib.Path(__file__).resolve()
MODEL_DIR = HERE.parents[1] / "model"
sys.path.insert(0, str(MODEL_DIR))
import residue_model_v2_5_ortho as mod


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


def make_model_and_inputs(lane: str, gradient_mode: str = "detached"):
    torch.manual_seed(17)
    config = mod.ResidueV25OrthoConfig.for_lane(
        lane,
        backbone_hidden_size=12,
        target_node_dim=7,
        graph_hidden_dim=32,
        dropout=0.0,
        contact_encoder_gradient=gradient_mode,
    )
    model = mod.OrthogonalResidueSurrogate(FrozenBackbone(12), mod.OrthogonalTargetHead(config))
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


class TestResidueModelV25Ortho(unittest.TestCase):
    def test_b_clean_attention_has_no_contact_modules_or_outputs(self):
        config, model, inputs = make_model_and_inputs(mod.LANE_B)
        self.assertFalse(config.enable_contact_evidence)
        self.assertIsNone(model.head.contact_interaction)
        self.assertIsNone(model.head.contact_calibration)
        output = model(**inputs)
        self.assertEqual(output["receptor_predictions"].shape, (2, 2))
        self.assertTrue(torch.equal(output["exact_min_dual"], output["receptor_predictions"].min(1).values))
        self.assertFalse(any("contact" in key for key in output))
        self.assertFalse(any("contact" in name for name, _ in model.named_parameters()))
        contract = mod.model_contract(config, mod.LANE_B)
        self.assertFalse(contract["contact_feedback_to_scalar"])
        self.assertEqual(contract["contact_path"], "disabled")

    def test_e_terminals_pair_projections_and_scalar_path_are_disjoint(self):
        config, model, inputs = make_model_and_inputs(mod.LANE_E)
        attention = model.head.attention_interaction
        contact = model.head.contact_interaction
        self.assertIsNotNone(contact)
        self.assertNotEqual(attention.terminal.data_ptr(), contact.terminal.data_ptr())
        self.assertNotEqual(attention.vhh_left.weight.data_ptr(), contact.vhh_left.weight.data_ptr())
        self.assertNotEqual(attention.target_right.weight.data_ptr(), contact.target_right.weight.data_ptr())
        self.assertFalse(attention.materializes_rank4_pair_tensor)
        self.assertFalse(contact.materializes_rank4_pair_tensor)

        model.eval()
        before = model(**inputs)
        scalar_before = before["prediction"].clone()
        contact_before = before["contact_logits_8x6b"].clone()
        with torch.no_grad():
            for parameter in contact.parameters():
                parameter.mul_(0.0).add_(7.0)
            model.head.contact_calibration.bias.add_(4.0)
        after = model(**inputs)
        self.assertTrue(torch.equal(scalar_before, after["prediction"]))
        self.assertFalse(torch.equal(contact_before, after["contact_logits_8x6b"]))
        contract = mod.model_contract(config, mod.LANE_E)
        self.assertFalse(contract["attention_contact_pair_projections_shared"])
        self.assertFalse(contract["contact_feedback_to_scalar"])

    def test_scalar_loss_never_gradients_contact_parameters(self):
        _, model, inputs = make_model_and_inputs(mod.LANE_E, "shared")
        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        output["receptor_predictions"].square().mean().backward()
        self.assertIsNotNone(model.head.attention_interaction.terminal.grad)
        self.assertIsNotNone(model.head.scalar_head[-1].weight.grad)
        for parameter in model.head.contact_interaction.parameters():
            self.assertIsNone(parameter.grad)
        self.assertIsNone(model.head.contact_calibration.bias.grad)
        self.assertIsNone(model.backbone.embedding.weight.grad)

    def test_detached_contact_loss_only_updates_contact_terminal_branch(self):
        _, model, inputs = make_model_and_inputs(mod.LANE_E, "detached")
        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        output["contact_logits_8x6b"][:, :4].square().mean().backward()
        self.assertIsNotNone(model.head.contact_interaction.terminal.grad)
        self.assertIsNotNone(model.head.contact_interaction.vhh_left.weight.grad)
        self.assertIsNotNone(model.head.contact_calibration.bias.grad)
        self.assertIsNone(model.head.attention_interaction.terminal.grad)
        self.assertIsNone(model.head.scalar_head[-1].weight.grad)
        self.assertTrue(all(parameter.grad is None for parameter in model.head.vhh_graph_encoder.parameters()))
        self.assertTrue(all(parameter.grad is None for parameter in model.head.target_graph_encoder.parameters()))

    def test_shared_contact_loss_updates_encoder_but_not_attention_or_scalar(self):
        _, model, inputs = make_model_and_inputs(mod.LANE_E, "shared")
        model.zero_grad(set_to_none=True)
        output = model(**inputs)
        output["contact_logits_9e6y"][:, :4].square().mean().backward()
        self.assertTrue(any(parameter.grad is not None for parameter in model.head.vhh_graph_encoder.parameters()))
        self.assertTrue(any(parameter.grad is not None for parameter in model.head.target_graph_encoder.parameters()))
        self.assertIsNone(model.head.attention_interaction.terminal.grad)
        self.assertIsNone(model.head.scalar_head[-1].weight.grad)

    def test_forbidden_inputs_absent_and_direct_injection_fails(self):
        config, model, inputs = make_model_and_inputs(mod.LANE_E)
        forbidden = {
            "m2_base", "m2_outputs", "structure", "structure_features", "candidate_id",
            "candidate_ids", "parent_framework_cluster", "campaign_id", "docking_pose", "pose_features",
        }
        for callable_object in (model.forward, model.head.forward):
            self.assertFalse(set(inspect.signature(callable_object).parameters) & forbidden)
        self.assertFalse(any("m2" in name.lower() or "pose" in name.lower() for name, _ in model.named_parameters()))
        with self.assertRaises(TypeError):
            model(**inputs, m2_base=torch.zeros(2, 3))
        contract = mod.model_contract(config, mod.LANE_E)
        self.assertTrue(forbidden <= set(contract["forbidden_neural_inputs"]))

    def test_bfloat16_endpoint_entropy_forward_and_softmin_are_finite(self):
        logits = {
            "8x6b": torch.tensor([[[100.0, -100.0], [80.0, -80.0]]], dtype=torch.bfloat16, requires_grad=True),
            "9e6y": torch.tensor([[[-100.0, 100.0], [-80.0, 80.0]]], dtype=torch.bfloat16, requires_grad=True),
        }
        probabilities = {name: torch.sigmoid(value) for name, value in logits.items()}
        graphs = {
            name: {"interface_mask": torch.tensor([True, False]), "hotspot_mask": torch.tensor([True, False])}
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

        _, model, inputs = make_model_and_inputs(mod.LANE_E)
        model.train()
        with torch.autocast(device_type="cpu", dtype=torch.bfloat16):
            output = model(**inputs)
            smooth = mod.stable_softmin(
                output["receptor_predictions"][:, 0], output["receptor_predictions"][:, 1], 0.02,
            )
        self.assertTrue(all(torch.isfinite(value).all() for value in output.values()))
        self.assertEqual(smooth.dtype, torch.float32)
        self.assertTrue(torch.isfinite(smooth).all())
        equal = torch.tensor([0.4, -0.2])
        self.assertTrue(torch.allclose(mod.stable_softmin(equal, equal, 0.02), equal, atol=1e-6))


if __name__ == "__main__":
    unittest.main()

