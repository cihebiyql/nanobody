import torch
import numpy as np
import logging
import warnings
warnings.filterwarnings("ignore")
from torch.utils.data import DataLoader
from utils.evaluate import  evaluate_site 
from utils.dataloader import infaData_Sabdab,collate_fn_infaData 
from models.NanoBind_site import NanoBind_site

ESM2_MODEL = 'esm2_t6_8M_UR50D'

def test(model, device, loader):
    model.eval()
    total_BSite2 = list()
    total_labels = list()

    logging.info('Make prediction for {} samples...'.format(len(loader.dataset)))
    with torch.no_grad():
        for data in loader:
            seqs_nanobody = data[0]
            seqs_antigen = data[1]
            BSite_antigen = data[3]

            BSite_output = model(seqs_nanobody, seqs_antigen, device).cpu().numpy().tolist()

            for n in range(len(seqs_antigen)):
                len_seq = len(seqs_antigen[n])
                if len_seq > len(BSite_output[n]):
                    len_seq = len(BSite_output[n])
                total_BSite2.append(BSite_output[n][:len_seq])
                total_labels.append(BSite_antigen[n][:len_seq])

    return total_labels, total_BSite2

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

if ESM2_MODEL == 'esm2_t6_8M_UR50D':
    model = NanoBind_site(pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320, finetune=0).to(device)

model_dir = './output/checkpoint/'
model_name = 'NanoBind_site({})_SabdabData_finetune1_TF0_good.model'.format(ESM2_MODEL)
model_path = model_dir + model_name
weights = torch.load(model_path,map_location=torch.device('cpu'))
model.load_state_dict(weights)

testDataset = infaData_Sabdab(pair_path='./data/Sabdab/NAI_test_pos.csv')
test_loader = DataLoader(testDataset, batch_size=32, shuffle=False,collate_fn=collate_fn_infaData)

# test
true_labels, pred_scores = test(model, device, test_loader)

accuracy, precision, recall, F1_score, auroc, auprc ,mcc= evaluate_site(true_labels, pred_scores, thresh=0.5)
# print(f"F1={F1_score:.4f},Accuracy={accuracy:.4f},Precision={precision:.4f},Recall={recall:.4f},AUROC={auroc:.4f},AUPRC={auprc:.4f},MCC={mcc:.4f}")

# save
import pandas as pd
csv_metrics = pd.DataFrame([{
    'accuracy': f"{accuracy:.4f}",
    'precision': f"{precision:.4f}",
    'recall': f"{recall:.4f}",
    'F1_score': f"{F1_score:.4f}",
    'AUC_ROC': f"{auroc:.4f}",
    'AUC_PR': f"{auprc:.4f}",
    'MCC': f"{mcc:.4f}",
}])
csv_metrics.to_csv(f'./output/test_results/NanoBind_site_results.csv', index=False)
