import numpy as np
import torch 
import argparse
import pandas as pd
from models.NanoBind_pair import NanoBind_pair
from utils.dataloader import anli_aff
from torch.utils.data import DataLoader
from Bio import SeqIO

def get_args():
    parser = argparse.ArgumentParser(description='Demo',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--nb', dest='nanobody_fasta', help='Path to the nanobody FASTA file')    
    parser.add_argument('--ag', dest='antigen_fasta', help='Path to the antigen FASTA file')
    parser.add_argument('--output', dest='output_path', default='./output/prediction_results/predictions_NanoBind_affi.csv',
                       help='Path to save prediction results')
    return parser.parse_args()

def read_fasta(fasta_path):
    records = list(SeqIO.parse(fasta_path, "fasta"))
    if not records:
        raise ValueError(f"No sequences found in the FASTA file: {fasta_path}")
    return [(record.id, str(record.seq)) for record in records]

def predicting(model, device, loader2, nb_records, ag_records):
    model.eval()
    if len(nb_records) != len(ag_records):
        raise ValueError(
            f"Number of sequences in nanobody file ({len(nb_records)}) "
            f"does not match antigen file ({len(ag_records)})"
        )
    
    num_input_pairs = len(nb_records)
    num_reference_pairs = len(loader2.dataset)
    comparison_matrix = np.zeros((num_input_pairs, num_reference_pairs), dtype=int)
    for i, (nb_id, nb_seq) in enumerate(nb_records):
        ag_id, ag_seq = ag_records[i]
        for j, data2 in enumerate(loader2):
            ab2, ag2 = data2
            
            with torch.no_grad():
                prob = model(nb_seq, ag_seq, ab2, ag2, device)
                if hasattr(prob, 'item'):
                    prob_value = prob.item()
                else:
                    prob_value = float(prob)
                comparison_matrix[i, j] = 1 if prob_value > 0.4 else 0
    
    return comparison_matrix

def find_best_positions(matrix, intervals):
    num_rows = len(matrix)
    results = []
    
    for row_idx in range(num_rows):
        row = matrix[row_idx]
        prefix = [0] * (len(intervals) + 2)
        for i in range(1, len(intervals) + 2):
            prefix[i] = prefix[i-1] + row[i-1]
        
        suffix = [0] * (len(intervals) + 2)
        for i in range(len(intervals), -1, -1):
            suffix[i] = suffix[i+1] + (1 if row[i] == 0 else 0)
        max_sum = -1
        best_positions = []
        for i in range(len(intervals) + 2):
            current_sum = prefix[i] + suffix[i]
            if current_sum > max_sum:
                max_sum = current_sum
                best_positions = [i+1]
            elif current_sum == max_sum:
                best_positions.append(i)
        descriptions = []
        for pos in best_positions:
            if pos == 0:
                desc = "< 7.17e-12 M"
            elif pos == len(intervals) + 1:
                desc = "> 0.000696 M"
            else:
                desc = f"{intervals[pos-1]} M"
            descriptions.append(desc)
        
        results.append({
            'row_index': row_idx,
            'best_positions': best_positions,
            'descriptions': descriptions
        })
    
    return results

def main():
    args = get_args()
    nb_records = read_fasta(args.nanobody_fasta)
    ag_records = read_fasta(args.antigen_fasta)
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = NanoBind_pair().to(device)
    model_path = './output/checkpoint/NanoBind_pair_100.model'
    weights = torch.load(model_path, map_location=device)
    model.load_state_dict(weights)
    
    Dataset2 = anli_aff('./data/affinity/reference_set.csv')
    loader2 = DataLoader(Dataset2, batch_size=1, shuffle=False)
    comparison_matrix = predicting(model, device, loader2, nb_records, ag_records)

    intervals = [
        "[7.17e-12,1e-11]",
        "[1e-11,2e-11]",
        "[2e-11,3e-11]",
        "[3e-11,5.4e-11]",
        "[5.4e-11,6.697e-11]",
        "[6.697e-11,8.4e-11]",
        "[8.4e-11,1e-10]",
        "[1e-10,1.8e-10]",
        "[1.8e-10,3.2e-10]",
        "[3.2e-10,4.1e-10]",
        "[4.1e-10,5.5e-10]",
        "[5.5e-10,6.2e-10]",
        "[6.2e-10,6.9e-10]",
        "[6.9e-10,8.1e-10]",
        "[8.1e-10,9.1e-10]",
        "[9.1e-10,1e-09]",
        "[1e-09,1.8e-09]",
        "[1.8e-09,2.6e-09]",
        "[2.6e-09,3.5e-09]",
        "[3.5e-09,4e-09]",
        "[4e-09,5e-09]",
        "[5e-09,5.7e-09]",
        "[5.7e-09,7.4e-09]",
        "[7.4e-09,9e-09]",
        "[9e-09,1e-08]",
        "[1e-08,1.8e-08]",
        "[1.8e-08,2.3e-08]",
        "[2.3e-08,3.6e-08]",
        "[3.6e-08,4.4e-08]",
        "[4.4e-08,5.2e-08]",
        "[5.2e-08,6e-08]",
        "[6e-08,7.2e-08]",
        "[7.2e-08,8.4e-08]",
        "[8.4e-08,1e-07]",
        "[1e-07,1.8e-07]",
        "[1.8e-07,2.9e-07]",
        "[2.9e-07,3.8e-07]",
        "[3.8e-07,5.56e-07]",
        "[5.56e-07,6.9e-07]",
        "[6.9e-07,8.5e-07]",
        "[8.5e-07,1.1e-06]",
        "[1.1e-06,2.1e-06]",
        "[2.1e-06,5.29e-06]",
        "[5.29e-06,5.7e-06]",
        "[5.7e-06,6.8e-06]",
        "[6.8e-06,1.797e-05]",
        "[1.797e-05,0.00044]",
        "[0.00044,0.000696]"
    ]
    
    results = find_best_positions(comparison_matrix, intervals)
    output_results = []
   
    for i, res in enumerate(results):
        nb_id, nb_seq = nb_records[i]
        ag_id, ag_seq = ag_records[i]

        row_result = {
            'pair_id': i + 1,
            'best_positions': ','.join(map(str, res['best_positions'])),
            'predicted_Kd_intervals': '; '.join(res['descriptions'])
        }
        output_results.append(row_result)

    df = pd.DataFrame(output_results)
    df.to_csv(args.output_path, index=False)

if __name__ == "__main__":
    main()
