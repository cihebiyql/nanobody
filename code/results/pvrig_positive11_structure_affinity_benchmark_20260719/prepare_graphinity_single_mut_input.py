#!/usr/bin/env python3
"""Prepare Graphinity single-interface-mutation inference inputs.

Graphinity's int_mut graph mode accepts one mutation encoded at the end of the
``complex`` field (for example ``..._DA103E``).  Labels are placeholders because
experimental single-mutation ddG values are unavailable; evaluation is performed
only after additive aggregation at the parent/child pair level.
"""

from pathlib import Path

import pandas as pd
import yaml


ROOT = Path("/mnt/d/work/抗体/code/results/pvrig_positive11_structure_affinity_benchmark_20260719")
REMOTE_ROOT = Path("/data1/qlyu/model_smoke/pvrig_positive11_structure_affinity_benchmark_20260719")


def main() -> None:
    manifest = pd.read_csv(ROOT / "graphinity_single_mutation_manifest.tsv", sep="\t")
    interface = manifest.loc[manifest["is_interface_le4A"].astype(int).eq(1)].copy()

    rows = []
    for row in interface.itertuples(index=False):
        task = f"{row.pair_id}__{row.mutation}"
        task_dir = REMOTE_ROOT / "graphinity_single_mut_foldx" / task
        for replicate in range(3):
            rows.append(
                {
                    "pdb": task,
                    "complex": f"{task}_rep{replicate}_{row.mutation}",
                    "labels": 0.0,
                    "chain_prot1": "A",
                    "chain_prot2": "B",
                    "ab_chain": "A",
                    "ag_chain": "B",
                    "pdb_wt": str(task_dir / f"graphinity_wt_rep{replicate}.pdb"),
                    "pdb_mut": str(task_dir / f"graphinity_mut_rep{replicate}.pdb"),
                    "pair_id": row.pair_id,
                    "mutation": row.mutation,
                    "replicate": replicate,
                    "experimental_pair_ddg_kcal_mol": row.experimental_ddg_kcal_mol,
                }
            )

    output = pd.DataFrame(rows)
    output_path = ROOT / "graphinity_single_mutation_input.csv"
    output.to_csv(output_path, index=False)

    config = {
        "save_dir": str(REMOTE_ROOT / "graphinity_single_mutation"),
        "name": "PVRIG-positive-single-interface-mutation",
        "test": True,
        "initialize_weights": {
            "checkpoint_file": "/data1/qlyu/software/Graphinity/example/ddg_synthetic/FoldX/varying_dataset_size/model_weights/Graphinity-varying_dataset_size-full_848597.ckpt"
        },
        "model": "ddgEGNN",
        "model_params": {
            "num_node_features": 12,
            "lr": 1e-3,
            "weight_decay": 1e-16,
            "balanced_loss": False,
            "dropout": 0,
            "num_edge_features": 1,
            "egnn_layer_hidden_nfs": [128, 128, 128],
            "embedding_in_nf": 128,
            "embedding_out_nf": 128,
            "num_classes": 1,
            "attention": False,
            "residual": True,
            "normalize": False,
            "tanh": True,
            "update_coords": True,
            "scheduler": "CosineAnnealing",
            # The released checkpoint expects the literal string "None".
            "norm_nodes": "None",
        },
        "trainer_params": {"gpus": 0},
        "loader_params": {
            "batch_size": 16,
            "num_workers": 4,
            "balanced_sampling": False,
        },
        "dataset_params": {
            "rotate": False,
            "cache_frames": False,
            "graph_generation_mode": "int_mut",
            "interaction_dist": 4,
            "typing_mode": "lmg",
            "rough_search": True,
            "input_files": {"test": [str(REMOTE_ROOT / output_path.name)]},
        },
    }
    config_path = ROOT / "graphinity_single_mutation_config.yaml"
    with config_path.open("w") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)

    assert len(output) == 27
    assert output["mutation"].nunique() == 6  # RA26G and position-1 changes recur.
    print(f"Wrote {len(output)} rows for {len(interface)} pair-specific mutations")
    print(output_path)
    print(config_path)


if __name__ == "__main__":
    main()
