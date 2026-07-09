import torch
import argparse
import warnings
import pandas as pd
import numpy as np
warnings.filterwarnings("ignore")
from models.NanoBind_site import NanoBind_site
from Bio import SeqIO

def get_args():
    parser = argparse.ArgumentParser(description='Demo',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--nb', dest='nanobody_fasta', help='Path to the nanobody FASTA file')    
    parser.add_argument('--ag', dest='antigen_fasta', help='Path to the antigen FASTA file')
    parser.add_argument('--output', dest='output_path', default='./output/prediction_results/predictions_NanoBind_site.csv',
                       help='Path to save prediction results')
    return parser.parse_args()

def read_fasta(fasta_path):
    records = list(SeqIO.parse(fasta_path, "fasta"))
    if not records:
        raise ValueError(f"No sequences found in the FASTA file: {fasta_path}")
    return [(record.id, str(record.seq)) for record in records]

def predicting(model, device, nb_records, ag_records):
    model.eval()
    results = []
    if len(nb_records) != len(ag_records):
        raise ValueError(
            f"Number of sequences in nanobody file ({len(nb_records)}) "
            f"does not match antigen file ({len(ag_records)})"
        )
    
    with torch.no_grad():
        for i, ((nb_id, nb_seq), (ag_id, ag_seq)) in enumerate(zip(nb_records, ag_records)):
            BSite_output = model(nb_seq, ag_seq, device).cpu().numpy()
            BSite_output = np.array(BSite_output, dtype=np.float64)
            if BSite_output.shape[1] != len(ag_seq):
                raise ValueError(
                    f"Output shape {BSite_output.shape} does not match antigen sequence length {len(ag_seq)} "
                    f"for pair {i+1} (nanobody: {nb_id}, antigen: {ag_id})"
                )

            binding_sites = []
            binding_residues = []
            
            for pos_idx, score in enumerate(BSite_output[0]):
                position = pos_idx + 1
                if score > 0.5:
                    amino_acid = ag_seq[pos_idx]
                    binding_sites.append(position)
                    binding_residues.append(amino_acid)

            results.append({
                'pair_id': i + 1,
                'prediction_scores': list(BSite_output[0]),
                'binding_sites': binding_sites,
                'binding_residues': binding_residues,
            })
    
    return results

def main():
    args = get_args()
    nb_records = read_fasta(args.nanobody_fasta)
    ag_records = read_fasta(args.antigen_fasta)

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = NanoBind_site(pretrained_model=r'./models/esm2_t6_8M_UR50D', hidden_size=320, finetune=0).to(device)
    model_dir = './output/checkpoint/'
    model_name = 'NanoBind_site(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model'
    model_path = model_dir + model_name
    weights = torch.load(model_path, map_location=device)
    model.load_state_dict(weights)

    results = predicting(model, device, nb_records, ag_records)
    df = pd.DataFrame(results)
    df.to_csv(args.output_path, index=False)

if __name__ == "__main__":
    main()
