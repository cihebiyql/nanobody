import torch
import argparse
import warnings
import pandas as pd
warnings.filterwarnings("ignore")
from models.NanoBind_seq import NanoBind_seq
from Bio import SeqIO

def get_args():
    parser = argparse.ArgumentParser(description='Demo',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--nb', dest='nanobody_fasta', help='Path to the nanobody FASTA file')    
    parser.add_argument('--ag', dest='antigen_fasta', help='Path to the antigen FASTA file')
    parser.add_argument('--output', dest='output_path', default='./output/prediction_results/predictions_NanoBind_seq.csv',
                       help='Path to save prediction results')   
    return parser.parse_args()

def read_fasta(fasta_path):
    records = list(SeqIO.parse(fasta_path, "fasta"))
    if not records:
        raise ValueError("No sequences found in the FASTA file.")
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
            p = model(nb_seq, ag_seq, device)
            probability = p.cpu().item() if p.numel() == 1 else p.cpu().numpy().flatten()[0]

            pred = 1 if probability > 0.3 else 0
            
            results.append({
                'pair_id': i + 1,
                'probability': probability,
                'prediction': pred
            })

    return results

def main():
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    model = NanoBind_seq(pretrained_model=r'./models/esm2_t6_8M_UR50D', hidden_size=320, finetune=0).to(device)
    model_dir = './output/checkpoint/'
    model_name = 'NanoBind_seq(esm2_t6_8M_UR50D)_SabdabData_finetune1_TF0_good.model'
    model_path = model_dir + model_name
    weights = torch.load(model_path, map_location=device)
    model.load_state_dict(weights)

    args = get_args()
    nb_records = read_fasta(args.nanobody_fasta)
    ag_records = read_fasta(args.antigen_fasta)
    results = predicting(model, device, nb_records, ag_records)

    df = pd.DataFrame(results)
    columns_order = ['pair_id', 'probability', 'prediction']
    df = df[columns_order]
    
    df.to_csv(args.output_path, index=False)

if __name__ == "__main__":
    main()