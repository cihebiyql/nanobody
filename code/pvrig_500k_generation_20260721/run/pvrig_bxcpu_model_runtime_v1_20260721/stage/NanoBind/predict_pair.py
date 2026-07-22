import torch 
import argparse
import warnings
import pandas as pd
from torch.nn import functional as F
from models.NanoBind_pair import NanoBind_pair
from Bio import SeqIO

warnings.filterwarnings("ignore")

def get_args():
    parser = argparse.ArgumentParser(description='Demo',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--nb1', dest='nanobody_fasta1', help='Path to the nanobody1 FASTA file')    
    parser.add_argument('--ag1', dest='antigen_fasta1', help='Path to the antigen1 FASTA file')   
    parser.add_argument('--nb2', dest='nanobody_fasta2', help='Path to the nanobody2 FASTA file')    
    parser.add_argument('--ag2', dest='antigen_fasta2', help='Path to the antigen2 FASTA file')
    parser.add_argument('--output', dest='output_path', default='./output/prediction_results/predictions_NanoBind_pair.csv',
                       help='Path to save prediction results')
    return parser.parse_args()

def read_fasta(fasta_path):
    records = list(SeqIO.parse(fasta_path, "fasta"))
    if not records:
        raise ValueError(f"No sequences found in the FASTA file: {fasta_path}")
    return [(record.id, str(record.seq)) for record in records]

def read_all_fasta_files(args):
    nb1_records = read_fasta(args.nanobody_fasta1)
    ag1_records = read_fasta(args.antigen_fasta1)
    nb2_records = read_fasta(args.nanobody_fasta2)
    ag2_records = read_fasta(args.antigen_fasta2)

    sequence_counts = [len(nb1_records), len(ag1_records), len(nb2_records), len(ag2_records)]
    if len(set(sequence_counts)) > 1:
        raise ValueError(
            f"Number of sequences in input files do not match:\n"
            f"  Nanobody1: {sequence_counts[0]}\n"
            f"  Antigen1: {sequence_counts[1]}\n"
            f"  Nanobody2: {sequence_counts[2]}\n"
            f"  Antigen2: {sequence_counts[3]}"
        )
    
    return nb1_records, ag1_records, nb2_records, ag2_records

def predicting(model, device, nb1_records, ag1_records, nb2_records, ag2_records):
    model.eval()
    results = []
    total_preds = torch.Tensor()
    
    num_pairs = len(nb1_records)
    with torch.no_grad():
        for i in range(num_pairs):
            nb1_id, nb1_seq = nb1_records[i]
            ag1_id, ag1_seq = ag1_records[i]
            nb2_id, nb2_seq = nb2_records[i]
            ag2_id, ag2_seq = ag2_records[i]

            p = model(nb1_seq, ag1_seq, nb2_seq, ag2_seq, device)
            total_preds = torch.cat((total_preds, p.cpu()), 0)
            probability = p.cpu().item() if p.numel() == 1 else p.cpu().numpy().flatten()[0]

            if probability > 0.4:
                prediction = 1
            else:
                prediction = 0

            results.append({
                'pair_id': i + 1,
                'probability': probability,
                'prediction': prediction,
            })

    return results, total_preds.numpy().flatten()

def main():
    args = get_args()
    nb1_records, ag1_records, nb2_records, ag2_records = read_all_fasta_files(args)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = NanoBind_pair()
    model = model.to(device)
    model_path = './output/checkpoint/' + 'NanoBind_pair_100.model'
    weights = torch.load(model_path, map_location=device)
    model.load_state_dict(weights)
    
    results, probabilities = predicting(model, device, nb1_records, ag1_records, nb2_records, ag2_records)

    df = pd.DataFrame(results)
    df.to_csv(args.output_path, index=False)

if __name__ == "__main__":
    main()

