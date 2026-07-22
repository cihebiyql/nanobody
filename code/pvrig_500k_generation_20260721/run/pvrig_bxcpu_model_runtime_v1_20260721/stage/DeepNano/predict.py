import numpy as np
import torch
import pandas as pd
from torch.utils.data import DataLoader
import argparse
import logging
# from torch.utils.tensorboard import SummaryWriter 
import random
import os
from torch.utils.data import Dataset
# from torch.nn import functional as F
import warnings
warnings.filterwarnings("ignore")
import torch.nn as nn
# from transformers import AutoTokenizer, AutoModel
from Bio import SeqIO
from tqdm import tqdm
from models.models import DeepNano_seq,DeepNano
import json

from torch.utils.data import Dataset
import pandas as pd
import numpy as np
from Bio import SeqIO
import random
import torch
# from torch import nn


fasta_path = './data/screening_run/screening_input.fasta'
pair_path = './data/screening_run/screening_pairs.tsv'
output_path = './output/screening_results.csv'


'''
python predict.py --model 0 --esm2 8M &
'''

def get_args():
    parser = argparse.ArgumentParser(description='Demo',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    
    parser.add_argument('--model', dest='model', type=int, default=0,
                        help='model',metavar='E')
    
    parser.add_argument('--esm2', dest='esm2', type=str, default='8M',
                        help='esm2',metavar='E')
    
    parser.add_argument('--fasta_path', type=str, default=fasta_path, help='Path to fasta file')
    parser.add_argument('--pair_path', type=str, default=pair_path, help='Path to pair file')
    parser.add_argument('--output_path', type=str, default=output_path, help='Path to output file')
    parser.add_argument('--esm2_path', type=str, default=None, help='Path to ESM2 model directory')
    parser.add_argument('--json_path', type=str, default=None, help='Path to JSON file with nanobody sequences')
    parser.add_argument('--antigen_id', type=str, default='Q9BXC0', help='Antigen ID to pair with nanobodies')
    parser.add_argument('--antigen_seq', type=str, default='MERSPPAAPWSGPRLPARGFLSLLLLLLPLLLLLLLLPAACAPGAPAVAGADTRDRAGGRGGPGGVDVGPGGARGPSGRSGPAGPARGPGSRERAPGPRGPRGPQGRDGDPGPPGPPGPPGPPGLGGAPEGPLGPRGFPGAPGPRGPPGPPGPAGARGEPGAVGPAGPPGFPGARGPAGERGERGPPGPAGPPGARGAPGERGEQGAPGPPGFQGLPGPAGPPGEAGKPGEQGVPGDPGPPGPPGPPGPPGIPGAPGPRGEPGPPGPRGPPGPVGPSGPRGSPGPQGPSGPPGPPGPPGLSGGASRASPGRSRRSRGVRGGRGGGGDPRA', help='Antigen sequence')
   
    return parser.parse_args()

def predicting(model, device, loader, Model_type):
    model.eval()
    total_preds_ave = torch.Tensor()
    total_preds_min = torch.Tensor()
    total_preds_max = torch.Tensor()
    total_labels = torch.Tensor()

    logging.info('Make prediction for {} samples...'.format(len(loader.dataset)))
    with torch.no_grad():
        for data in tqdm(loader):
        # for data in loader:
            #Get input
            seqs_nanobody = data[0]
            seqs_antigen = data[1]

            #Calculate output
            g = data[2]

            p_ave, p_min, p_max = model(seqs_nanobody,seqs_antigen,device)

            total_preds_ave = torch.cat((total_preds_ave, p_ave.cpu()), 0)
            total_preds_min = torch.cat((total_preds_min, p_min.cpu()), 0)
            total_preds_max = torch.cat((total_preds_max, p_max.cpu()), 0)

            total_labels = torch.cat((total_labels, g), 0)
            
            

    return total_labels.numpy().flatten(),total_preds_ave.numpy().flatten(),total_preds_min.numpy().flatten(),total_preds_max.numpy().flatten()

class seqData(Dataset):
    def __init__(self,fasta_path = '', pair_path = '', json_path=None, antigen_id=None, antigen_seq=None):
        super(seqData,self).__init__()
        
        self.seq_data = list()
        self.pair_data = list()

        if json_path:
            with open(json_path, 'r') as f:
                nb_data = json.load(f)

            sequence_list = None
            if 'sequences' in nb_data:
                sequence_list = nb_data['sequences']
            elif 'data' in nb_data:
                sequence_list = nb_data['data']
            else:
                sequence_list = nb_data
            
            for item in sequence_list:
                nb_id = item['id']
                nb_seq = item['sequence']
                self.seq_data.append([nb_seq, antigen_seq, -1])
                self.pair_data.append([nb_id, antigen_id])

        else:
            ##Load sequence data
            seq_list = dict()
            # for fa in SeqIO.parse('./data/Sabdab/sabdab_valdata.seqs.fasta','fasta'):
            for fa in SeqIO.parse(fasta_path,'fasta'):
                ID = fa.description
                seq = ''.join(list(fa.seq))
                seq_list[ID] = seq

            self.pair_data = pd.read_csv(pair_path,header=0,sep='	').values.tolist()
            for n,item in enumerate(self.pair_data):
                if len(item) == 3:
                    ID1,ID2,label = item
                else:
                    ID1, ID2 = item
                    label = -1
                seq1 = seq_list[ID1]
                seq2 = seq_list[ID2]

                self.seq_data.append([seq1,seq2,label])

    def __len__(self):
        return len(self.seq_data)
    def __getitem__(self,i):
        seq1,seq2,label = self.seq_data[i]
       
        return seq1,seq2,label




args = get_args()
fasta_path = args.fasta_path
pair_path = args.pair_path
output_path = args.output_path


###装载训练好的模型
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

esm2_dict = {'8M':'esm2_t6_8M_UR50D','35M':'esm2_t12_35M_UR50D','150M':'esm2_t30_150M_UR50D','650M':'esm2_t33_650M_UR50D',
             '3B':'esm2_t36_3B_UR50D','15B':'esm2_t48_15B_UR50D'}
hiddenDim_dict = {'8M':320,'35M':480,'150M':640,'650M':1280,'3B':2560,'15B':5120}
ESM2_MODEL = esm2_dict[args.esm2]
hiddenDim = hiddenDim_dict[args.esm2]

if args.esm2_path:
    pretrained_model_path = args.esm2_path
elif ESM2_MODEL == 'esm2_t33_650M_UR50D':
    pretrained_model_path = '/home/qlyu/workdata/esm2_t33_650M_UR50D/'
else:
    pretrained_model_path = os.path.join(os.getcwd(), 'models', ESM2_MODEL) + '/'

if args.model == 0:
    print('##########################Load DeepNano-seq(PPI)-{}模型：'.format(args.esm2))
    model = DeepNano_seq(pretrained_model=pretrained_model_path,hidden_size=hiddenDim, finetune=0).to(device)

    model_dir = './output/checkpoint/'
    model_name = 'DeepNano-seq_PPI_{}.model'.format(args.esm2)
    model_path = model_dir + model_name
    weights = torch.load(model_path,map_location=torch.device('cpu')) # map_location=torch.device('cpu')
    model.load_state_dict(weights, strict=False)
    # model.load_state_dict({k.replace('module.',''):v for k,v in weights.items()})
elif args.model == 1:
    print('##########################Load DeepNano-seq(NAI)-{}模型：'.format(args.esm2))
    model = DeepNano_seq(pretrained_model=pretrained_model_path,hidden_size=hiddenDim, finetune=0).to(device)

    model_dir = './output/checkpoint/'
    if args.esm2 in ['8M', '650M']:
        model_name = 'DeepNano_seq({})_SabdabData_finetune1_TF0_best.model'.format(ESM2_MODEL)
    else:
        model_name = 'DeepNano-seq_NAI_{}.model'.format(args.esm2)
    
    model_path = model_dir + model_name
    weights = torch.load(model_path,map_location=torch.device('cpu')) # map_location=torch.device('cpu')
    model.load_state_dict(weights, strict=False)
    # model.load_state_dict({k.replace('module.',''):v for k,v in weights.items()})
elif args.model == 2:
    print('##########################在Load DeepNano(NAI)-{}模型：'.format(ESM2_MODEL))
    ###装载训练好的模型
    site_model_name = 'DeepNano-site_{}.model'.format(args.esm2)
    model = DeepNano(pretrained_model=pretrained_model_path,hidden_size=hiddenDim, finetune=0,
                        Model_BSite_path=os.path.join('./output/checkpoint/', site_model_name)).to(device)

    model_dir = './output/checkpoint/'
    model_name = 'DeepNano_NAI_{}.model'.format(args.esm2)
    model_path = model_dir + model_name
    weights = torch.load(model_path,map_location=torch.device('cpu'))
    model.load_state_dict(weights, strict=False)
    # model.load_state_dict({k.replace('module.',''):v for k,v in weights.items()})



###装载测试数据background
testDataset = seqData(fasta_path=fasta_path,
                      pair_path=pair_path,
                      json_path=args.json_path,
                      antigen_id=args.antigen_id,
                      antigen_seq=args.antigen_seq)
test_loader = DataLoader(testDataset, batch_size=32, shuffle=False)
#Test
g,p_ave,p_min,p_max = predicting(model, device, test_loader,Model_type=3)
p = (p_ave+p_min+p_max)/3
print(len(p))


##Save to local 
output = list()
for n in range(len(p)):
    output.append([testDataset.pair_data[n][0],testDataset.pair_data[n][1],p[n]])
output = pd.DataFrame(columns=['Nanobody ID','Antigen ID','Prediction'],data=output)
output.to_csv(output_path,index = None)

if len(testDataset.pair_data[0]) == 3:
    from utils.evaluate import evaluate
    precision,recall,accuracy,F1_score,Top10,Top20,Top50,AUC_ROC,AUC_PR = evaluate(g,p)
    print('precision={:.4f},recall={:.4f},accuracy={:.4f},F1_score={:.4f},AUC_ROC={:.4f},AUC_PR={:.4f}'.format(precision,recall,accuracy,F1_score,AUC_ROC,AUC_PR))