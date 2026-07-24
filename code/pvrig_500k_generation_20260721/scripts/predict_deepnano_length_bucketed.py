#!/usr/bin/env python3
"""Batch-composition invariant DeepNano inference by exact sequence-length buckets."""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import torch
from Bio import SeqIO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--deepnano-root', type=Path, required=True)
    parser.add_argument('--fasta', type=Path, required=True)
    parser.add_argument('--pairs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument(
        '--device',
        default='cpu',
        help='Torch device (for example cpu, cuda, or cuda:0).',
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.deepnano_root))
    from models.models import DeepNano_seq

    sequences = {record.description: str(record.seq) for record in SeqIO.parse(args.fasta, 'fasta')}
    with args.pairs.open(newline='') as handle:
        pairs = list(csv.DictReader(handle, delimiter='\t'))
    id1, id2 = list(pairs[0])[:2]
    device = torch.device(args.device)
    if device.type == 'cuda' and not torch.cuda.is_available():
        raise RuntimeError(f'CUDA device requested but CUDA is unavailable: {args.device}')
    esm = args.deepnano_root / 'models/esm2_t6_8M_UR50D'
    model = DeepNano_seq(pretrained_model=str(esm), hidden_size=320, finetune=0).to(device)
    checkpoint = args.deepnano_root / 'output/checkpoint/DeepNano_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_best.model'
    model.load_state_dict(torch.load(checkpoint, map_location=device), strict=False)
    model.eval()

    buckets = defaultdict(list)
    for index, row in enumerate(pairs):
        nb_id, ag_id = row[id1], row[id2]
        buckets[len(sequences[nb_id])].append((index, nb_id, ag_id))
    predictions = [None] * len(pairs)
    with torch.no_grad():
        for length in sorted(buckets):
            items = buckets[length]
            for start in range(0, len(items), args.batch_size):
                batch = items[start:start + args.batch_size]
                nb = [sequences[item[1]] for item in batch]
                ag = [sequences[item[2]] for item in batch]
                ave, minimum, maximum = model(nb, ag, device)
                values = ((ave + minimum + maximum) / 3).cpu().numpy().reshape(-1)
                for item, value in zip(batch, values):
                    predictions[item[0]] = float(value)
    if any(value is None for value in predictions):
        raise RuntimeError('missing prediction')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        'Nanobody ID': [row[id1] for row in pairs],
        'Antigen ID': [row[id2] for row in pairs],
        'Prediction': predictions,
    }).to_csv(args.output, index=False)


if __name__ == '__main__':
    main()
