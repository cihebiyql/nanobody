import numpy as np
import torch
import pandas as pd
from torch.utils.data import DataLoader
import argparse
from sklearn.metrics import roc_auc_score,accuracy_score,f1_score,precision_score,recall_score,precision_recall_curve,auc
import logging
# from torch.utils.tensorboard import SummaryWriter 
import random
import os
from torch.utils.data import Dataset
from torch.nn import functional as F
import warnings
warnings.filterwarnings("ignore")
import torch.nn as nn
from transformers import AutoTokenizer, AutoModel
from Bio import SeqIO
from tqdm import tqdm
from models.NanoBind_seq import NanoBind_seq
from utils.dataloader import seqData_NBAT_Test,seqData_Sabdab
from utils.evaluate import evaluate

ESM2_MODEL = 'esm2_t6_8M_UR50D'

def predicting(model, device, loader, Model_type):
    model.eval()
    total_preds_ave = torch.Tensor()
    total_labels = torch.Tensor()

    logging.info('Make prediction for {} samples...'.format(len(loader.dataset)))
    with torch.no_grad():
        # for data in tqdm(loader):
        for data in loader:
            # Get input
            seqs_nanobody = data[0]
            seqs_antigen = data[1]

            # Calculate output
            g = data[2]
            if Model_type == 0:
                predictions = model(seqs_nanobody,seqs_antigen,device)

                total_preds_ave = torch.cat((total_preds_ave, predictions.cpu()), 0)
            elif Model_type == 1:
                p = model(seqs_nanobody,seqs_antigen,device)
                
                total_preds_ave = torch.cat((total_preds_ave, p.cpu()), 0)

            total_labels = torch.cat((total_labels, g), 0)
            
            
    if Model_type == 1:
        return total_labels.numpy().flatten(),total_preds_ave.numpy().flatten()
    else:
        return total_labels.numpy().flatten(),total_preds_ave.numpy().flatten()

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

if ESM2_MODEL == 'esm2_t6_8M_UR50D':
    model = NanoBind_seq(pretrained_model=r'./models/esm2_t6_8M_UR50D',hidden_size=320, finetune=0).to(device)

model_dir = './output/checkpoint/'
model_name = 'NanoBind_seq({})_SabdabData_finetune1_TF0_good.model'.format(ESM2_MODEL)
model_path = model_dir + model_name
weights = torch.load(model_path,map_location=torch.device('cpu')) # 
model.load_state_dict(weights)

testDataset  = seqData_NBAT_Test(seq_path='./data/sdab/NAI_test_seq.fasta',
                                pair_path = './data/sdab/NAI_test.tsv')
test_loader = DataLoader(testDataset, batch_size=32, shuffle=False)

# Test
g,p= predicting(model, device, test_loader,Model_type=1)
# np.save('./output/results_NanoBind_seq(SabdabData)_{}.npy'.format('NBAT'),[g,p1,p_ave,p_min,p_max])

# Ensemble
precision,recall,accuracy,F1_score,Top10,Top20,Top50,AUC_ROC,AUC_PR,mcc = evaluate(g,p,thresh=0.3)
# print("{}: accuracy={:.4f},Recall = {:.4f},Precision={:.4f},F1 score={:.4f},AUC_ROC={:.4f},AUC_PR={:.4f},mcc{:.4f}".format(
#     'Ensemble',accuracy,recall,precision,F1_score,AUC_ROC,AUC_PR,mcc))

# save
csv_metrics = pd.DataFrame([{
    'accuracy': f"{accuracy:.4f}",
    'precision': f"{precision:.4f}",
    'recall': f"{recall:.4f}",
    'F1_score': f"{F1_score:.4f}",
    'AUC_ROC': f"{AUC_ROC:.4f}",
    'AUC_PR': f"{AUC_PR:.4f}",
    'MCC': f"{mcc:.4f}",
}])
csv_metrics.to_csv(f'./output/test_results/NanoBind_seq_results.csv', index=False)






